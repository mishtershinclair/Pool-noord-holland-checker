import streamlit as st
from service import TOURNAMENTS, check_league
from datetime import datetime
from zoneinfo import ZoneInfo
import requests


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


def get_todays_matches(now=None):
    """Read only the three fixture lists, independently of result validation."""
    now = now or datetime.now(AMSTERDAM)
    today = now.astimezone(AMSTERDAM).date()
    result = {'date': today.isoformat(), 'date_label': today.strftime('%d %B %Y'),
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
                if start.date() != today:
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
st.caption('2026/2027 season · Check competition entries on CueScore')


def fixture_context(league, fixture):
    st.caption(f"{league} · {fixture['date']} · Match {fixture['match_no']}")
    st.subheader(f"{fixture['team_a']} vs {fixture['team_b']}")


def game_details(match):
    st.text(f"Individual match {match['match_no']}")
    if 'player_a' in match:
        st.text(f"{match['player_a']}  {match['score_a']}–{match['score_b']}  {match['player_b']}")
    race = match.get('race_to')
    st.caption(f"{match['type']} / {match['discipline']}" + (f' / Race to {race}' if race is not None else ''))


if st.button("Today's matches", help="Show today's fixtures across all three leagues"):
    with st.spinner("Reading today's fixtures from CueScore…"):
        st.session_state.today_schedule = get_todays_matches()

schedule = st.session_state.get('today_schedule')
if schedule and schedule['date'] != datetime.now(AMSTERDAM).date().isoformat():
    st.info("The date has changed. Select Today's matches to load the new schedule.")
    schedule = None
if schedule:
    st.subheader(f"Today's matches · {schedule['date_label']}")
    st.caption('Times shown in Amsterdam local time. Click Today’s matches again to refresh.')
    if schedule['errors']:
        st.warning('Could not read fixtures for: ' + ', '.join(schedule['errors']) + '. Please retry; the schedule may be incomplete.')
    for league, count in schedule['undated'].items():
        st.caption(f'{league}: {count} fixture(s) have no usable scheduled date and could not be assigned to today.')
    if not schedule['matches']:
        if schedule['errors'] or schedule['undated']:
            st.info('No matches for today found in the available dated fixtures.')
        else:
            st.info('No matches scheduled for today in these three leagues.')
    for match in schedule['matches']:
        with st.container(border=True):
            st.caption(f"{match['league']} · {match['time']} · Match {match['match_no']}")
            st.subheader(f"{match['team_a']} vs {match['team_b']}")
            st.text('📍 ' + match['venue'])
            if match['address']:
                st.text(match['address'])
            if match['venue_source']:
                st.caption(match['venue_source'])


force_refresh = st.checkbox('Fetch fresh results (skip cache)', value=False)
st.caption('Completed checks are reused for up to 2 minutes. Select fresh results after correcting an entry.')

if st.button('Check all leagues', type='primary'):
    st.session_state.results = {}
    progress = st.progress(0, text='Connecting to CueScore…')
    for index, (league, tournament_id) in enumerate(TOURNAMENTS.items()):
        progress.progress(index / 3, text=f'Checking {league} — reading fixtures and individual matches…')
        st.session_state.results[league] = check_league(league, tournament_id, force_refresh=force_refresh)
    progress.empty()

results = st.session_state.get('results', {})
for column, league in zip(st.columns(3), TOURNAMENTS):
    with column, st.container(border=True):
        st.subheader(league)
        result = results.get(league)
        if result is None:
            st.info('Not checked yet')
        else:
            total = sum(len(result[key]) for key in ['format_issues', 'race_to_issues', 'score_issues', 'player_issues'])
            if result['incomplete']:
                st.warning('Check incomplete — retry')
            elif total:
                st.error(f'{total} issue(s) detected')
            else:
                st.success('No invalid entries found')
            st.caption(f"Format: {len(result['format_issues'])} · Race-to: {len(result['race_to_issues'])} · Scores: {len(result['score_issues'])} · Players: {len(result['player_issues'])}")
            st.caption(f"Special results: {len(result['special_scores'])}")
            if result.get("from_cache"):
                st.caption("Using a recent completed check")
            st.caption(f"Last checked: {result['checked_at']} (Amsterdam)")

if not results:
    st.info('Select “Check all leagues” to retrieve the latest results. A full check can take a few minutes.')
else:
    for league, result in results.items():
        if result['incomplete']:
            st.warning(f"{league}: Some CueScore data could not be read. Any findings below are partial; this league has not received a complete check. Please try again.")
        for key, title in [('format_issues', 'Format issue'), ('race_to_issues', 'Race-to issue'), ('score_issues', 'Score issue'), ('player_issues', 'Player participation issue'), ('special_scores', 'Special result')]:
            for issue in result[key]:
                with st.container(border=True):
                    st.markdown(f'**{title}**')
                    fixture_context(league, issue['fixture'])
                    if key in ('race_to_issues', 'score_issues', 'special_scores'):
                        match = issue['match']
                        game_details(match)
                        if key == 'race_to_issues':
                            actual = issue['actual_race_to']
                            actual_text = str(actual) if actual is not None else 'missing or invalid'
                            st.error(f"Problem: Expected Race to {issue['expected_race_to']}; actual Race to {actual_text}.")
                        elif key == 'score_issues':
                            st.error(f"Problem: Neither player has a valid Race to {match['race_to']} winning score.")
                        else:
                            st.info('A non-numeric result (such as FF or WD) was recorded. Review it manually; it is not counted as an invalid entry.')
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
                                for (kind, discipline), count in issue.get(field, {}).items():
                                    st.text(f'{label}: {count} × {kind} / {discipline}')
                            # Only show configured games when reviewing a format mismatch.
                            # Missing-player reports identify the affected slots above.
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

st.caption('Uses league-specific formats and race lengths: untouched fixtures are skipped; participation is checked when all six games are configured; Straightpool is excluded from ordinary race-to score checks. Special results are reported separately.')
