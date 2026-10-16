import streamlit as st
import streamlit.components.v1 as components
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from contextlib import contextmanager
from service import TOURNAMENTS, check_league
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from html import escape
import doubles_mvp
from doubles_mvp import load_league as load_doubles_league
ISSUE_TITLES = {
    'format_issues': 'Format issue', 'race_to_issues': 'Race-to issue',
    'score_issues': 'Score issue', 'player_issues': 'Player participation issue',
    'missing_player_issues': 'Missing player issue', 'special_scores': 'Special result',
}
ERROR_KEYS = tuple(key for key in ISSUE_TITLES if key != 'special_scores')


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


def get_scheduled_matches(day_offset=0, now=None, progress=None):
    progress = progress or (lambda value, label: None)
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
        progress((list(TOURNAMENTS).index(league) + 1) / len(TOURNAMENTS), f'Read {league} schedule')
    result['matches'].sort(key=lambda match: (match['league'], match['time'], str(match['match_no'])))
    return result



def next_loading_theme():
    count = st.session_state.get('loading_animation_count', 0)
    st.session_state.loading_animation_count = count + 1
    return ('beer', 'pool', 'coffee')[count % 3]


@contextmanager
def loading_indicator(detail, theme=None, progress=None, retain=False):
    """Show a lightweight animation and always remove it when loading ends."""
    theme = theme or next_loading_theme()
    placeholder = st.empty()
    message = {'beer': 'Pulling a fresh round of results…',
               'pool': 'Racking up the results…', 'coffee': 'Brewing your results… Lekker bij de coffee'}[theme]
    scene = {'beer': '<div class="pour"></div><div class="glass"><div class="beer"></div></div>',
             'pool': '<div class="pocket"></div><div class="ball ball-one">8</div><div class="ball ball-two">1</div><div class="ball ball-three">3</div>',
             'coffee': '<div class="coffee-drip"></div><div class="cup"><div class="coffee-fill"></div></div><div class="cup-handle"></div><div class="saucer"></div>'}[theme]
    line_style = '' if progress is None else f'animation:none;width:{max(0, min(1, progress)) * 100:.1f}%;transform:none;transition:width .3s'
    placeholder.markdown('''<style>
    .mvp-loading{position:fixed;top:70px;left:50%;transform:translateX(-50%);z-index:999990;box-sizing:border-box;width:min(540px,calc(100vw - 24px));display:flex;align-items:center;gap:12px;padding:10px 14px 17px;border:1px solid #46515f;border-radius:14px;background:#20252D;color:#f5f1e8;box-shadow:0 5px 24px #0004;pointer-events:none}
    .mvp-loading{--loading-accent:#e9a621}
    .mvp-loading.pool{--loading-accent:#49ba8a}
    .mvp-loading.coffee{--loading-accent:#c58b57}
    .mvp-loading .loading-track{position:absolute;bottom:0;left:0;right:0;height:5px;overflow:hidden;border-radius:0 0 14px 14px;background:#ffffff15}
    .mvp-loading .loading-line{display:block;height:100%;width:35%;background:var(--loading-accent);animation:mvp-travel 1.6s ease-in-out infinite}
    @keyframes mvp-travel{from{transform:translateX(-110%)}to{transform:translateX(390%)}}
    .mvp-loading .scene{position:relative;width:150px;height:94px;overflow:hidden;flex-shrink:0}
    .mvp-loading .glass{position:absolute;left:47px;top:22px;width:49px;height:63px;border:3px solid #9aaebc;border-radius:3px 3px 13px 13px;overflow:hidden;background:#ffffff18}
    .mvp-loading .beer{position:absolute;bottom:0;width:100%;height:0;background:#e9a621;border-top:9px solid #fff4dc;animation:mvp-fill 3s ease-in-out infinite}
    .mvp-loading .pour{position:absolute;left:69px;top:0;width:7px;height:77px;background:#e9a621;border-radius:4px;animation:mvp-pour 3s infinite}
    @keyframes mvp-fill{0%,10%{height:0}75%,95%{height:48px}100%{height:0}}
    @keyframes mvp-pour{0%,75%{opacity:1}80%,100%{opacity:0}}
    .mvp-loading.pool .scene{background:#17664d;border:5px solid #68432b;border-radius:10px}
    .mvp-loading .pocket{position:absolute;right:7px;top:28px;width:34px;height:34px;background:#101516;border-radius:50%;box-shadow:0 0 0 3px #0e4636}
    .mvp-loading .ball{position:absolute;left:-25px;top:32px;width:25px;height:25px;border-radius:50%;background:#17191d;color:white;text-align:center;font:bold 13px/25px sans-serif;animation:mvp-roll 3.6s linear infinite}
    .mvp-loading .ball-two{background:#e9bb26;color:#17202a;animation-delay:1.2s}
    .mvp-loading .ball-three{background:#c44343;animation-delay:2.4s}
    @keyframes mvp-roll{0%{transform:translateX(0) rotate(0);opacity:0}8%{opacity:1}68%{transform:translateX(130px) rotate(300deg) scale(1);opacity:1}80%,100%{transform:translateX(137px) rotate(360deg) scale(0);opacity:0}}
    .mvp-loading strong{font-size:18px}.mvp-loading small{display:block;margin-top:5px;opacity:.88}
    .mvp-loading .cup{position:absolute;left:42px;top:31px;width:58px;height:48px;border:4px solid #c8b9a5;border-radius:3px 3px 20px 20px;overflow:hidden;background:#fff}
    .mvp-loading .coffee-fill{position:absolute;bottom:0;width:100%;background:#714324;animation:mvp-coffee 3s infinite}
    .mvp-loading .coffee-drip{position:absolute;left:69px;top:5px;width:5px;height:63px;background:#714324;animation:mvp-pour 3s infinite}
    .mvp-loading .cup-handle{position:absolute;left:104px;top:40px;width:15px;height:24px;border:4px solid #c8b9a5;border-left:0;border-radius:0 14px 14px 0}
    .mvp-loading .saucer{position:absolute;left:31px;top:86px;width:84px;height:5px;border-radius:50%;background:#c8b9a5}
    @keyframes mvp-coffee{0%,10%{height:0}75%,95%{height:36px}100%{height:0}}
    @media(max-width:600px){.mvp-loading .scene{zoom:.65}.mvp-loading strong{font-size:16px}.mvp-loading small{font-size:14px}}
    @media(prefers-reduced-motion:reduce){.mvp-loading *{animation:none!important}.mvp-loading .beer{height:40px}.mvp-loading .coffee-fill{height:36px}.mvp-loading .coffee-drip{display:none}.mvp-loading .pour{display:none}.mvp-loading .ball{left:10px}.mvp-loading .ball-two{left:42px}.mvp-loading .ball-three{left:74px}}
    </style>''' + '<div class="mvp-loading ' + theme + '" role="status" aria-live="polite">'
        + '<div class="scene" aria-hidden="true">' + scene + '</div><div><strong>'
        + escape(message) + '</strong><small>' + escape(detail)
        + '</small></div><div class="loading-track" aria-hidden="true"><span class="loading-line" style="' + line_style + '"></span></div></div>', unsafe_allow_html=True)
    try:
        yield
    finally:
        if not retain:
            placeholder.empty()


st.set_page_config(page_title='Pool Noord-Holland checker ☕', page_icon='🎱', layout='wide')
st.markdown('''<style>
[data-testid="stCaptionContainer"] {font-size:15px!important;opacity:1;}
[data-testid="stCaptionContainer"] p {font-size:15px!important;line-height:1.5;color:color-mix(in srgb, var(--text-color, #c9ced6) 82%, transparent);}
</style>''', unsafe_allow_html=True)
st.markdown('''<style>
.app-header h1 {padding-bottom:0!important;margin-bottom:4px!important;}
.app-header p {font-size:15px;line-height:1.45;margin:2px 0;color:color-mix(in srgb, var(--text-color, #c9ced6) 82%, transparent);}
.app-header {margin-bottom:8px;}
</style><div class="app-header">
<h1>🎱 Pool Noord-Holland checker ☕</h1>
<p>App last updated: 16 October 2026, 13:13 (Amsterdam)</p>
<p>Have an issue or an idea for improvement? Please contact <a href="mailto:mishtershinclair@gmail.com">Matt Sinclair</a>.</p>
</div>''', unsafe_allow_html=True)



def fixture_context(league, fixture):
    st.caption(f"{league} · {fixture['date']} · Match {fixture['match_no']}")
    st.subheader(f"{fixture['team_a']} vs {fixture['team_b']}")


def game_details(match):
    st.text(f"Individual match {match['match_no']}")
    if 'player_a' in match:
        st.text(f"{match['player_a']}  {match['score_a']}–{match['score_b']}  {match['player_b']}")
    race = match.get('race_to')
    st.caption(f"{match['type']} / {match['discipline']}" + (f' / Race to {race}' if race is not None else ''))


def queue_search(kind, season=None, leagues=None, day_offset=0):
    if st.session_state.get('active_search'):
        return
    if kind == 'mvp':
        st.session_state.doubles_active_season = season
        st.session_state.doubles_active_league = leagues[0]
    st.session_state.active_search = {'kind': kind, 'season': season, 'leagues': leagues,
                                      'day_offset': day_offset, 'theme': next_loading_theme()}


busy = bool(st.session_state.get('active_search'))


with st.container(border=True):
    st.subheader('📅 Match schedule')
    st.caption('See who is playing and where, across all three leagues.')
    today_column, tomorrow_column = st.columns(2)
    with today_column:
        show_today = st.button("📅 See today's matches", disabled=busy, on_click=queue_search, args=("schedule", None, None, 0), type='primary', use_container_width=True)
    with tomorrow_column:
        show_tomorrow = st.button("📅 See tomorrow's matches", disabled=busy, on_click=queue_search, args=("schedule", None, None, 1), type='primary', use_container_width=True)

schedule = st.session_state.get('match_schedule')
if schedule and schedule['base_date'] != datetime.now(AMSTERDAM).date().isoformat():
    st.info('The date has changed. Select a schedule button to refresh the fixtures.')
    schedule = None
if schedule:
    st.markdown('<div id="schedule-results" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
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
    partnerships = 'Partnership' in rows[0] and 'Win %' in rows[0]
    standings = ('Player' in rows[0] and 'Win %' in rows[0]) or partnerships
    columns = (['Rank', 'Player', 'Won', 'Played', 'Win %',
                'Racks won', 'Racks lost', 'Difference', 'Participation %']
               if standings else list(rows[0]))
    if partnerships:
        columns = ['Rank', 'Partnership', 'Won', 'Played', 'Win %', 'Racks won', 'Racks lost', 'Difference', 'Status']
    labels = {'Rank': '#', 'Racks won': 'Frames<br>won', 'Racks lost': 'Frames<br>lost',
              'Difference': 'Frame<br>difference', 'Participation %': 'Participation<br>%'}
    header = ''.join('<th>' + (labels.get(column, escape(column)) if standings else escape(column)) + '</th>' for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, '')
            if standings and column in ('Player', 'Partnership'):
                names = str(value).split(' + ') if partnerships else [str(value)]
                content = ''.join('<div class="doubles-player">' + escape(name) + '</div>' for name in names)
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
                '.doubles-scroll .doubles-large th,.doubles-scroll .doubles-large td {padding:6px 8px;text-align:left;border-bottom:1px solid #a5afbd80;white-space:nowrap;}'
                '.doubles-scroll .doubles-large th {font-size:15px;font-weight:700;vertical-align:bottom;}'
                '.doubles-scroll .doubles-standings th,.doubles-scroll .doubles-standings td {text-align:center;}'
                '.doubles-scroll .doubles-standings th:nth-child(2),.doubles-scroll .doubles-standings td.doubles-person {text-align:left;}'
                '.doubles-person {width:180px;min-width:130px;max-width:180px;white-space:normal!important;overflow-wrap:anywhere;} '
                '.doubles-player + .doubles-player {margin-top:7px;padding-top:7px;position:relative;} '
                '.doubles-player + .doubles-player::before {content:"";position:absolute;top:0;left:0;width:32px;border-top:1px solid #a5afbd80;} '
                '.doubles-player {font-size:18px;white-space:normal;max-width:180px;overflow-wrap:anywhere;} '
                '@media(max-width:600px){.doubles-person{width:130px;min-width:110px;max-width:140px}.doubles-player{font-size:16px;max-width:130px}.doubles-team{max-width:130px!important}.doubles-scroll .doubles-large th,.doubles-scroll .doubles-large td{padding:6px 5px}} '
                '.doubles-team {font-size:12px;opacity:.88;white-space:normal;max-width:240px;margin-top:2px;}'
                '</style><div class="doubles-scroll"><table class="' + table_class + '"><thead><tr>' + header +
                '</tr></thead><tbody>' + ''.join(body_rows) + '</tbody></table></div>', unsafe_allow_html=True)


DOUBLES_SEASONS = {
    '2026–27': dict(TOURNAMENTS),
    '2025–26': {'Eerste klasse': 61204738, 'Tweede klasse': 61204744, 'Derde klasse': 61204750},
    '2024–25': {'Eerste klasse': 46283263, 'Tweede klasse': 46283257, 'Derde klasse': 46283269},
}
matching_version = getattr(doubles_mvp, 'NAME_MATCHING_VERSION', 'older version')
matching_ready = matching_version == '2026-10-13.1' and getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None) == '2026-10-13.1'
if st.session_state.get('doubles_ranking_version') != (10, matching_version, getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None)):
    st.session_state.pop('doubles_results', None)
    st.session_state.doubles_ranking_version = (10, matching_version, getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None))


with st.container(border=True):
    st.subheader('🏆 Doubles MVP')
    if not matching_ready:
        st.error('The doubles checker file is out of date. Replace doubles_mvp.py with the matching download, then reboot the Streamlit app.')
    st.caption('Choose a season and league, or load all three leagues for that season.')
    mvp_selection = None
    for season, tournaments in DOUBLES_SEASONS.items():
        heading = f'{season} · Active season' if season == '2026–27' else f'*{season}*'
        st.markdown(f'### {heading}')
        for column, label in zip(st.columns(4), [*tournaments, 'All leagues']):
            with column:
                st.button(label, key='mvp_' + season + '_' + label, disabled=busy or not matching_ready,
                          on_click=queue_search, args=('mvp', season, list(tournaments) if label == 'All leagues' else [label]),
                          type='primary', use_container_width=True)
    st.caption('Ranked by games won, then win percentage, then frame difference, then participation percentage. Exact ties share a rank. All players remain visible; no minimum-participation cutoff is applied. Forfeits contribute nothing to player totals.')
    st.caption('Participation = played doubles / completed fixtures of the team(s) represented. Forfeits do not count as player appearances. Former members keep their recorded results. Confirmed historical names and unique spelling variants are matched automatically; ambiguous names remain excluded.')

active_season = st.session_state.get('doubles_active_season', '2026–27')
mvp_results = st.session_state.get('doubles_results', {}).get(active_season, {})
if mvp_results:
    st.markdown('<div id="mvp-results" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
    season_label = f'{active_season} · Active season' if active_season == '2026–27' else f'*{active_season}*'
    st.subheader(f'Doubles standings · {season_label}')
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
                st.caption('Note: This can happen when a player changes their name or a substitute is no longer listed on the team. Other causes are possible—expand “Results requiring review” below for details.')
            st.caption(f"{standing['counted']} played doubles games counted · {len(standing['forfeits'])} forfeit notice(s) · Updated {standing['checked_at']} (Amsterdam)")
            st.subheader('Top 3 Doubles Partnerships')
            st.caption('5-match minimum · Ranked by win percentage, then wins, then frame difference. Exact ties share a rank; tied pairs are displayed by name. Top 3 shows up to three qualifying partnerships.')
            if standing['top_partnerships']:
                show_doubles_table(standing['top_partnerships'])
            else:
                st.info('No partnership has played 5 valid doubles matches together yet.')
            with st.expander('Full partnership standings', expanded=True):
                st.caption('All pairs ranked by win percentage, wins and frame difference. Provisional = fewer than 5 valid matches together; excluded from Top 3.')
                show_doubles_table(standing['partnerships'])
            st.subheader('Individual doubles standings')
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




st.subheader('🔎 Check competition results')
check_selection = None
for column, label in zip(st.columns(4), [*TOURNAMENTS, 'All leagues']):
    with column:
        st.button(label, key='check_' + label, disabled=busy, on_click=queue_search,
                  args=('check', None, list(TOURNAMENTS) if label == 'All leagues' else [label]),
                  type='primary', use_container_width=True)

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


st.markdown('<div id="check-results" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
results = st.session_state.get('results', {})
visible = results

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
            else:
                st.success('No invalid entries found')
            st.caption(f"Missing players: {len(result['missing_player_issues'])} · Format: {len(result['format_issues'])} · Race-to: {len(result['race_to_issues'])} · Scores: {len(result['score_issues'])} · Players: {len(result['player_issues'])}")
            forfeits = sum(issue.get('kind') == 'forfeit' for issue in result['special_scores'])
            st.caption(f"Forfeit notices: {forfeits} · Other special results: {len(result['special_scores']) - forfeits}")
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

st.caption('Untouched fixtures are skipped. Missing names on recorded results are flagged. Participation is checked only when all six games have complete player selections. Straightpool is excluded from numeric score checks. Forfeits are notices, not score errors.')




@st.cache_resource
def search_executor():
    return ThreadPoolExecutor(max_workers=4)


def run_search(job, events):
    """Background work has no Streamlit/session-state calls, so reruns cannot cancel it."""
    def report(value, label):
        season = job.get('season') or '2026–27'
        events.put((value, f'{season} · {label}'))
    if job['kind'] == 'schedule':
        return get_scheduled_matches(job['day_offset'], progress=report)
    output = {}
    for index, league in enumerate(job['leagues']):
        def update(value, label):
            fraction = None if value is None and index == 0 else (index + (value or 0)) / len(job['leagues'])
            report(fraction, f'{league} · {label}')
        if job['kind'] == 'mvp':
            try:
                output[league] = load_doubles_league(league, DOUBLES_SEASONS[job['season']][league], progress=update)
            except (requests.RequestException, ValueError, KeyError, TypeError):
                output[league] = {'error': True}
        else:
            output[league] = check_league(league, TOURNAMENTS[league], force_refresh=True, progress=update)
    return output


@st.fragment(run_every=.5 if busy else None)
def poll_search():
    job = st.session_state.get('active_search')
    if not job:
        return
    if 'future' not in job:
        job['events'] = Queue()
        job['progress'] = None
        season = job.get('season') or '2026–27'
        target = ', '.join(job.get('leagues') or ['Tomorrow’s matches' if job['day_offset'] else 'Today’s matches'])
        job['detail'] = f'{season} · {target} · Connecting to CueScore…'
        job['future'] = search_executor().submit(run_search, dict(job), job['events'])
    while True:
        try:
            value, label = job['events'].get_nowait()
            if value is not None:
                job['progress'] = max(job['progress'] or 0, value)
            job['detail'] = label
        except Empty:
            break
    if job['future'].done():
        try:
            result = job['future'].result()
            if job['kind'] == 'schedule':
                st.session_state.match_schedule = result
            elif job['kind'] == 'mvp':
                st.session_state.setdefault('doubles_results', {}).setdefault(job['season'], {}).update(result)
            else:
                st.session_state.setdefault('results', {}).update(result)
            st.session_state.scroll_results = job['kind'] + '-results'
        except Exception:
            st.session_state.search_error = 'Could not finish this request. Please try again.'
        finally:
            st.session_state.pop('active_search', None)
        st.rerun()
    with loading_indicator(job['detail'], job['theme'], progress=job['progress'], retain=True):
        pass


poll_search()
if st.session_state.get('search_error'):
    st.error(st.session_state.pop('search_error'))
if st.session_state.get('scroll_results'):
    target = st.session_state.pop('scroll_results')
    # Run after the result containers arrive; retry briefly for slower mobile rendering.
    components.html('''<script>
    let tries=0;
    const timer=setInterval(()=>{
      try {
        const el=window.parent.document.getElementById("''' + target + '''");
        if(el){el.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});clearInterval(timer);}
      } catch(e){clearInterval(timer);}
      if(++tries>=20)clearInterval(timer);
    },100);
    </script>''', height=0)
