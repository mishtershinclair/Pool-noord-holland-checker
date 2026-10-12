import streamlit as st
from service import TOURNAMENTS, check_league
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from html import escape
from doubles_mvp import load_league as load_doubles_league
from review_store import (ReviewStore, StoreError, ISSUE_TITLES, ERROR_KEYS,
                          finding_id, finding_record)


AMSTERDAM = ZoneInfo('Europe/Amsterdam')


def scheduled_start(value):
    """CueScore timestamps include UTC/offset; never guess for ambiguous times."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        start = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return start.astimezone(AMSTERDAM) if start.tzinfo else None
    except ValueError:
        return None


def fixture_location(fixture):
    venue = fixture.get('venue')
    source = 'Fixture venue'
    if not isinstance(venue, dict) or not venue.get('name'):
        home = fixture.get('playerA') or {}
        venue = home.get('venue') if isinstance(home, dict) else None
        source = 'Home team venue — confirm if playing elsewhere'
    if not isinstance(venue, dict) or not venue.get('name'):
        return 'Location not listed', '', ''
    return venue['name'], venue.get('address') or '', source


def get_scheduled_matches(day_offset=0, now=None):
    """Read only the three fixture lists, independently of result validation."""
    now = now or datetime.now(AMSTERDAM)
    base_date = now.astimezone(AMSTERDAM).date()
    target_date = base_date + timedelta(days=day_offset)
    result = {'date': target_date.isoformat(), 'date_label': target_date.strftime('%d %B %Y'),
              'base_date': base_date.isoformat(), 'day_offset': day_offset,
              'matches': [], 'errors': [], 'undated': {}}
    for league, tournament_id in TOURNAMENTS.items():
        try:
            response = requests.get(
                f'https://api.cuescore.com/tournament/?id={tournament_id}', timeout=30)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('matches'), list):
                raise ValueError('Missing fixture list')
            league_matches = []
            undated = 0
            for fixture in data['matches']:
                if not isinstance(fixture, dict):
                    raise ValueError('Invalid fixture')
                start = scheduled_start(fixture.get('starttime'))
                if start is None:
                    undated += 1
                    continue
                if start.date() != target_date:
                    continue
                venue, address, source = fixture_location(fixture)
                team_a = fixture.get('playerA') or {}
                team_b = fixture.get('playerB') or {}
                league_matches.append({
                    'league': league, 'match_no': fixture.get('matchno', '?'),
                    'team_a': team_a.get('name') or 'Team not listed',
                    'team_b': team_b.get('name') or 'Team not listed',
                    'time': start.strftime('%H:%M'), 'venue': venue,
                    'address': address, 'venue_source': source,
                })
            result['matches'].extend(league_matches)
            if undated:
                result['undated'][league] = undated
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            result['errors'].append(league)
    result['matches'].sort(key=lambda match: (match['league'], match['time'], str(match['match_no'])))
    return result



st.set_page_config(page_title='Pool Noord-Holland checker ☕', page_icon='🎱', layout='wide')
st.title('🎱 Pool Noord-Holland checker ☕')
st.caption('2026/2027 season · Check competition entries on CueScore · Doubles MVP compact tables')


def fixture_context(league, fixture):
    st.caption(f"{league} · {fixture['date']} · Match {fixture['match_no']}")
    st.subheader(f"{fixture['team_a']} vs {fixture['team_b']}")


def game_details(match):
    st.text(f"Individual match {match['match_no']}")
    if 'player_a' in match:
        st.text(f"{match['player_a']}  {match['score_a']}–{match['score_b']}  {match['player_b']}")
    race = match.get('race_to')
    st.caption(f"{match['type']} / {match['discipline']}" + (f' / Race to {race}' if race is not None else ''))


with st.container(border=True):
    st.subheader('📅 Match schedule')
    st.caption('See who is playing and where, across all three leagues.')
    today_column, tomorrow_column = st.columns(2)
    with today_column:
        show_today = st.button("📅 See today's matches", type='primary', use_container_width=True)
    with tomorrow_column:
        show_tomorrow = st.button("📅 See tomorrow's matches", type='primary', use_container_width=True)

if show_today or show_tomorrow:
    day_offset = 1 if show_tomorrow else 0
    day_label = 'tomorrow' if day_offset else 'today'
    with st.spinner(f"Reading {day_label}'s fixtures from CueScore…"):
        st.session_state.match_schedule = get_scheduled_matches(day_offset)

schedule = st.session_state.get('match_schedule')
if schedule and schedule['base_date'] != datetime.now(AMSTERDAM).date().isoformat():
    st.info('The date has changed. Select a schedule button to refresh the fixtures.')
    schedule = None
if schedule:
    day_label = 'tomorrow' if schedule['day_offset'] else 'today'
    st.subheader(f"{day_label.capitalize()}'s matches · {schedule['date_label']}")
    st.caption('Times shown in Amsterdam local time. Select either schedule button to refresh.')
    if schedule['errors']:
        st.warning('Could not read fixtures for: ' + ', '.join(schedule['errors']) + '. Please retry; the schedule may be incomplete.')
    for league, count in schedule['undated'].items():
        st.caption(f'{league}: {count} fixture(s) have no usable scheduled date and could not be assigned to {day_label}.')
    if not schedule['matches']:
        if schedule['errors'] or schedule['undated']:
            st.info(f'No matches for {day_label} found in the available dated fixtures.')
        else:
            st.info(f'No matches scheduled for {day_label} in these three leagues.')
    for match in schedule['matches']:
        with st.container(border=True):
            st.caption(f"{match['league']} · {match['time']} · Match {match['match_no']}")
            st.subheader(f"{match['team_a']} vs {match['team_b']}")
            st.text('📍 ' + match['venue'])
            if match['address']:
                st.text(match['address'])
            if match['venue_source']:
                st.caption(match['venue_source'])


def show_doubles_table(rows):
    if not rows:
        st.caption('No results to show.')
        return
    standings = 'Player' in rows[0] and 'Win %' in rows[0]
    columns = (['Rank', 'Player', 'Win %', 'Played', 'Won', 'Lost',
                'Racks won', 'Racks lost', 'Difference', 'Participation %']
               if standings else list(rows[0]))
    labels = {'Rank': '#', 'Racks won': 'Racks<br>won', 'Racks lost': 'Racks<br>lost',
              'Participation %': 'Participation<br>%'}
    header = ''.join('<th>' + (labels.get(column, escape(column)) if standings else escape(column)) + '</th>' for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, '')
            if standings and column == 'Player':
                content = '<div class="doubles-player">' + escape(str(value)) + '</div>'
                content += '<div class="doubles-team">' + escape(str(row.get('Team', ''))) + '</div>'
                cells.append('<td class="doubles-person">' + content + '</td>')
            else:
                if standings and column in ('Win %', 'Participation %'):
                    value = f'{float(value):.1f}%'
                cells.append('<td>' + escape(str(value)) + '</td>')
        body_rows.append('<tr>' + ''.join(cells) + '</tr>')
    table_class = 'doubles-large doubles-standings' if standings else 'doubles-large'
    st.markdown('<style>.doubles-scroll {overflow-x:auto;} '
                '.doubles-scroll .doubles-large {width:auto;border-collapse:collapse;font-size:18px;line-height:1.3;}'
                '.doubles-scroll .doubles-large th,.doubles-scroll .doubles-large td {padding:6px 8px;text-align:left;border-bottom:1px solid #8885;white-space:nowrap;}'
                '.doubles-scroll .doubles-large th {font-size:15px;font-weight:700;vertical-align:bottom;}'
                '.doubles-scroll .doubles-standings th,.doubles-scroll .doubles-standings td {text-align:right;}'
                '.doubles-scroll .doubles-standings th:nth-child(2),.doubles-scroll .doubles-standings td.doubles-person {text-align:left;}'
                '.doubles-player {font-size:18px;} '
                '.doubles-team {font-size:13px;opacity:.75;white-space:normal;max-width:240px;margin-top:2px;}'
                '</style><div class="doubles-scroll"><table class="' + table_class + '"><thead><tr>' + header +
                '</tr></thead><tbody>' + ''.join(body_rows) + '</tbody></table></div>', unsafe_allow_html=True)


if st.session_state.get('doubles_ranking_version') != 3:
    st.session_state.pop('doubles_results', None)
    st.session_state.doubles_ranking_version = 3


with st.container(border=True):
    st.subheader('🏆 Doubles MVP')
    st.caption('Load one league for a quicker check, or refresh all three.')
    mvp_selection = None
    for column, label in zip(st.columns(4), [*TOURNAMENTS, 'All leagues']):
        with column:
            if st.button(label, key='mvp_' + label, type='primary', use_container_width=True):
                mvp_selection = list(TOURNAMENTS) if label == 'All leagues' else [label]
    if mvp_selection:
        if len(mvp_selection) == 1:
            st.session_state.doubles_active_league = mvp_selection[0]
        st.session_state.setdefault('doubles_results', {})
        for league in mvp_selection:
            with st.spinner(f'Reading doubles results and player rosters for {league}…'):
                try:
                    st.session_state.doubles_results[league] = load_doubles_league(league, TOURNAMENTS[league])
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    st.session_state.doubles_results[league] = {'error': True}
    st.caption('Ranked by win percentage, then matches played, then frame difference, then participation percentage. Exact ties share a rank. All players remain visible; no minimum-participation cutoff is applied. Forfeits contribute nothing to player totals.')
    st.caption('Participation = played doubles / completed fixtures of the team(s) represented. Forfeits do not count as player appearances. Former members keep their recorded results.')

mvp_results = st.session_state.get('doubles_results', {})
if mvp_results:
    for tab, league in zip(st.tabs(list(TOURNAMENTS), key='doubles_active_league', on_change='rerun'), TOURNAMENTS):
        with tab:
            standing = mvp_results.get(league, {})
            if not standing:
                st.info('Select this league above to load its doubles table.')
                continue
            if standing.get('error'):
                st.error('Could not load this league. Please refresh the doubles tables.')
                continue
            if standing['warnings']:
                st.warning(f"Provisional standings: {len(standing['warnings'])} game or fixture problem(s) need review. Affected results have not been counted.")
            st.caption(f"{standing['counted']} played doubles games counted · {len(standing['forfeits'])} forfeit notice(s) · Updated {standing['checked_at']} (Amsterdam)")
            if standing['table']:
                show_doubles_table(standing['table'])
            else:
                st.info('No completed, valid played doubles results could be included yet.')
            with st.expander('Counted doubles results'):
                show_doubles_table(standing['history'])
            if standing['forfeits']:
                with st.expander('Forfeit results — excluded from ranking'):
                    show_doubles_table(standing['forfeits'])
            if standing['warnings']:
                with st.expander('Results requiring review'):
                    show_doubles_table(standing['warnings'])


force_refresh = st.checkbox('Fetch fresh results (skip cache)', value=False)
st.caption('Completed checks are reused for up to 2 minutes. Select fresh results after correcting an entry.')

st.subheader('🔎 Check competition results')
check_selection = None
for column, label in zip(st.columns(4), [*TOURNAMENTS, 'All leagues']):
    with column:
        if st.button(label, key='check_' + label, type='primary', use_container_width=True):
            check_selection = list(TOURNAMENTS) if label == 'All leagues' else [label]
if check_selection:
    st.session_state.setdefault('results', {})
    progress = st.progress(0, text='Connecting to CueScore…')
    for index, league in enumerate(check_selection):
        progress.progress(index / len(check_selection), text=f'Checking {league} — reading fixtures and individual matches…')
        st.session_state.results[league] = check_league(league, TOURNAMENTS[league], force_refresh=force_refresh)
    progress.empty()

# Shared ignores are loaded independently of cached CueScore checks.
try:
    review_settings = st.secrets.get('shared_ignores', {})
except FileNotFoundError:
    review_settings = {}
store = ReviewStore(review_settings.get('url', ''), review_settings.get('secret_key', ''),
                    review_settings.get('admin_password', ''))
ignored = {}
store_ready = False
if store.configured:
    try:
        ignored = store.load()
        store_ready = True
    except StoreError as error:
        st.warning(str(error) + ' All findings are shown until storage is available.')
else:
    st.info('Shared ignoring is not connected yet. Checks work normally; connect shared storage to enable ignore and restore.')

if 'review_feedback' in st.session_state:
    st.success(st.session_state.pop('review_feedback'))

with st.expander('Manage shared ignores'):
    st.caption('Ignored findings are hidden for everyone. Only the administrator can ignore or restore them. Changes appear when this page refreshes or a check runs.')
    st.button('Refresh shared ignores')
    if store.writable:
        st.text_input('Administrator password', type='password', key='review_password')
        if st.session_state.get('review_password') and not store.authorized(st.session_state.review_password):
            st.warning('The administrator password is incorrect.')
    elif store.configured:
        st.caption('Set an administrator password in app settings to enable changes.')
password = st.session_state.get('review_password', '')
can_manage = store_ready and store.authorized(password)


def render_finding(league, key, issue):
    title = 'Forfeit notice' if issue.get('kind') == 'forfeit' else ISSUE_TITLES[key]
    st.markdown(f'**{title}**')
    fixture_context(league, issue['fixture'])
    if 'match' in issue:
        match = issue['match']
        game_details(match)
        if key == 'missing_player_issues':
            st.error(issue['message'])
        elif key == 'race_to_issues':
            actual = issue['actual_race_to']
            actual_text = str(actual) if actual is not None else 'missing or invalid'
            st.error(f"Problem: Expected Race to {issue['expected_race_to']}; actual Race to {actual_text}.")
        elif key == 'score_issues':
            st.error(f"Problem: Neither player has a valid Race to {match['race_to']} winning score.")
        elif issue.get('kind') == 'forfeit':
            st.info('A forfeit (FF) was recorded. This is a valid special result and is not counted as a score error.')
        else:
            st.info('An unfamiliar non-numeric result was recorded. Review it manually; it is not counted as an invalid entry.')
    else:
        st.error('Problem: ' + issue['message'])
        if key == 'format_issues':
            matches = issue['matches']
            numbers = [str(m['match_no']) for m in matches]
            if numbers and all(n in {'1','2','3','4','5','6'} for n in numbers) and len(set(numbers)) == len(numbers):
                missing = sorted(set('123456') - set(numbers))
                if missing:
                    st.warning('Player selection missing: individual match ' + ', '.join(missing))
            for label, field in [('Missing format', 'missing'), ('Unexpected format', 'unexpected')]:
                for game_format, count in issue.get(field, {}).items():
                    # Archived snapshots stringify tuple keys for JSON storage.
                    label_format = ' / '.join(game_format) if isinstance(game_format, tuple) else game_format
                    st.text(f'{label}: {count} × {label_format}')
            if 'missing' in issue:
                st.markdown('**Configured individual matches**')
                for match in matches:
                    game_details(match)
        else:
            side = 'team_a' if issue['side'] == 'A' else 'team_b'
            st.text(f"Team: {issue['fixture'][side]} · Players used: {issue['number_of_players']}")
            if issue['player']:
                st.text('Player(s): ' + issue['player'])
            for game in issue['games']:
                game_details(game)


results = st.session_state.get('results', {})
visible = {}
hidden_counts = {}
current_ids = set()
for league, result in results.items():
    visible[league] = dict(result)
    hidden_counts[league] = 0
    for key in ISSUE_TITLES:
        visible[league][key] = []
        for issue in result.get(key, []):
            identity = finding_id(league, TOURNAMENTS[league], key, issue)
            current_ids.add(identity)
            if identity in ignored:
                hidden_counts[league] += 1
            else:
                visible[league][key].append(issue)

for column, league in zip(st.columns(3), TOURNAMENTS):
    with column, st.container(border=True):
        st.subheader(league)
        result = visible.get(league)
        if result is None:
            st.info('Not checked yet')
        else:
            total = sum(len(result[key]) for key in ERROR_KEYS)
            if result['incomplete']:
                st.warning('Check incomplete — retry')
            elif total:
                st.error(f'{total} issue(s) to review')
            elif hidden_counts[league]:
                st.success('No unignored invalid entries')
            else:
                st.success('No invalid entries found')
            st.caption(f"Missing players: {len(result['missing_player_issues'])} · Format: {len(result['format_issues'])} · Race-to: {len(result['race_to_issues'])} · Scores: {len(result['score_issues'])} · Players: {len(result['player_issues'])}")
            forfeits = sum(issue.get('kind') == 'forfeit' for issue in result['special_scores'])
            st.caption(f"Forfeit notices: {forfeits} · Other special results: {len(result['special_scores']) - forfeits}")
            st.caption(f"Ignored findings: {hidden_counts[league]}")
            if result.get('from_cache'):
                st.caption('Using a recent completed check')
            st.caption(f"Last checked: {result['checked_at']} (Amsterdam)")

if not results:
    st.info('Select a league or “All leagues” under Check competition results to retrieve results. A full check can take a few minutes.')
for league, result in visible.items():
    if result['incomplete']:
        st.warning(f'{league}: Some CueScore data could not be read. Findings are partial; please retry.')
    for key in ISSUE_TITLES:
        for issue in result[key]:
            with st.container(border=True):
                render_finding(league, key, issue)
                identity = finding_id(league, TOURNAMENTS[league], key, issue)
                if can_manage:
                    with st.expander('Ignore this finding for everyone'):
                        reason = st.text_input('Reason (optional, visible to everyone)', key='reason_' + identity, max_chars=500)
                        if st.button('Ignore from now on', key='ignore_' + identity):
                            try:
                                store.ignore(finding_record(league, TOURNAMENTS[league], key, issue, reason), password)
                                st.session_state.review_feedback = 'Finding ignored for everyone. Changed details will be shown again.'
                                st.rerun()
                            except StoreError as error:
                                st.error(str(error))

with st.expander(f'Previously ignored findings ({len(ignored)})'):
    if not ignored:
        st.caption('No saved ignored findings.' if store_ready else 'Connect shared storage to see ignored findings.')
    for identity, record in sorted(ignored.items(), key=lambda pair: pair[1]['ignored_at'], reverse=True):
        with st.container(border=True):
            render_finding(record['league'], record['kind'], record['snapshot'])
            st.caption('Ignored at: ' + record['ignored_at'])
            if record.get('reason'):
                st.text('Reason: ' + record['reason'])
            if identity in current_ids:
                st.caption('Currently present and hidden from the main results.')
            else:
                st.caption('Saved finding; no exact match in the currently loaded checks. It may have changed, been resolved, or not been checked.')
            if can_manage and st.button('Restore for everyone', key='restore_' + identity):
                try:
                    store.restore(record, password)
                    st.session_state.review_feedback = 'Restore requested. If the finding still exists it will appear in the main results.'
                    st.rerun()
                except StoreError as error:
                    st.error(str(error))

st.caption('Untouched fixtures are skipped. Missing names on recorded results are flagged. Participation is checked only when all six games have complete player selections. Straightpool is excluded from numeric score checks. Forfeits are notices, not score errors.')

st.info('If you encounter any issues, please contact Matt Sinclair.')
