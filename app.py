import streamlit as st
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
import streamlit.components.v2 as components
from service import TOURNAMENTS, check_league
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from html import escape
import doubles_partnerships as doubles_mvp
from doubles_partnerships import load_league as load_doubles_league
from review_store import (ReviewStore, StoreError, ISSUE_TITLES, ERROR_KEYS,
                          finding_id, finding_record)




SCROLL_JS = "\nexport default function(component) {\n    const {data} = component;\n    if (!data || !data.target || !data.nonce) return;\n    let observer, timer;\n    function reveal() {\n        const target = document.getElementById(data.target);\n        if (!target || target.getClientRects().length === 0) return false;\n        if (target.dataset.lastScroll !== data.nonce) {\n            target.dataset.lastScroll = data.nonce;\n            target.focus({preventScroll:true});\n            target.scrollIntoView({block:'start', behavior:\n                matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});\n        }\n        if (observer) observer.disconnect();\n        if (timer) clearTimeout(timer);\n        return true;\n    }\n    if (!reveal()) {\n        observer = new MutationObserver(reveal);\n        observer.observe(document.body, {childList:true, subtree:true, attributes:true});\n        timer = setTimeout(() => observer.disconnect(), 8000);\n    }\n    return () => { if (observer) observer.disconnect(); if (timer) clearTimeout(timer); };\n}\n"

def scroll_to_results(request):
    scroll_component = components.component('pool_results_scroll', js=SCROLL_JS)
    scroll_component(key='results_scroll', data=request)

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



def next_loading_theme():
    count = st.session_state.get('loading_cycle_index', 0)
    st.session_state.loading_cycle_index = count + 1
    return ('coffee', 'beer', 'pool')[count % 3]


@contextmanager
def loading_indicator(detail, theme=None, keep=False):
    """Show a lightweight animation and always remove it when loading ends."""
    theme = theme or 'coffee'
    placeholder = st.empty()
    message = {'beer': 'Pulling a fresh round of results…',
               'pool': 'Racking up the results…', 'coffee': 'Brewing your results… Lekker bij de coffee',
               'smoking': 'Still loading—please wait.'}[theme]
    scene = {'beer': '<div class="pour"></div><div class="glass"><div class="beer"></div></div>',
             'pool': '<div class="pocket"></div><div class="ball ball-one">8</div><div class="ball ball-two">1</div><div class="ball ball-three">3</div>',
             'smoking': '<div class="cigarette"><div class="ember"></div></div><div class="smoke smoke-one"></div><div class="smoke smoke-two"></div><div class="smoke smoke-three"></div>',
             'coffee': '<div class="coffee-drip"></div><div class="cup"><div class="coffee-fill"></div></div><div class="cup-handle"></div><div class="saucer"></div>'}[theme]
    placeholder.markdown('''<style>
    .mvp-loading{position:fixed;top:70px;left:50%;transform:translateX(-50%);z-index:999990;box-sizing:border-box;width:min(540px,calc(100vw - 24px));display:flex;align-items:center;gap:12px;padding:10px 14px;border:1px solid #9aaebc;border-radius:14px;background:#fffdf7;color:#182235;box-shadow:0 5px 24px #0004;pointer-events:none}
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
    .mvp-loading strong{font-size:18px}.mvp-loading small{display:block;margin-top:5px;opacity:.75}
    .mvp-loading .cup{position:absolute;left:42px;top:31px;width:58px;height:48px;border:4px solid #c8b9a5;border-radius:3px 3px 20px 20px;overflow:hidden;background:#fff}
    .mvp-loading .coffee-fill{position:absolute;bottom:0;width:100%;background:#714324;animation:mvp-coffee 3s infinite}
    .mvp-loading .coffee-drip{position:absolute;left:69px;top:5px;width:5px;height:63px;background:#714324;animation:mvp-pour 3s infinite}
    .mvp-loading .cup-handle{position:absolute;left:104px;top:40px;width:15px;height:24px;border:4px solid #c8b9a5;border-left:0;border-radius:0 14px 14px 0}
    .mvp-loading .saucer{position:absolute;left:31px;top:86px;width:84px;height:5px;border-radius:50%;background:#c8b9a5}
    @keyframes mvp-coffee{0%,10%{height:0}75%,95%{height:36px}100%{height:0}}
    .mvp-loading .cigarette{position:absolute;left:25px;top:66px;width:96px;height:12px;background:linear-gradient(to right,#c39656 0 25%,#eee 25% 94%,#555 94%);border:1px solid #aaa;border-radius:3px;transform:rotate(-8deg)}
    .mvp-loading .ember{position:absolute;right:0;width:6px;height:100%;background:#ed713d;box-shadow:0 0 7px #eb6a32}
    .mvp-loading .smoke{position:absolute;left:112px;top:55px;width:11px;height:11px;border-radius:50%;background:#8b949d80;animation:mvp-smoke 2.4s ease-out infinite}
    .mvp-loading .smoke-two{animation-delay:.8s}.mvp-loading .smoke-three{animation-delay:1.6s}
    @keyframes mvp-smoke{0%{transform:translate(0,0) scale(.5);opacity:0}15%{opacity:.8}100%{transform:translate(-22px,-50px) scale(2.5);opacity:0}}
    @media(max-width:600px){.mvp-loading .scene{zoom:.65}.mvp-loading strong{font-size:16px}.mvp-loading small{font-size:12px}}
    @media(prefers-reduced-motion:reduce){.mvp-loading *{animation:none!important}.mvp-loading .beer{height:40px}.mvp-loading .coffee-fill{height:36px}.mvp-loading .coffee-drip{display:none}.mvp-loading .pour{display:none}.mvp-loading .ball{left:10px}.mvp-loading .ball-two{left:42px}.mvp-loading .ball-three{left:74px}}
    </style>''' + '<div class="mvp-loading ' + theme + '" role="status" aria-live="polite">'
        + '<div class="scene" aria-hidden="true">' + scene + '</div><div><strong>'
        + escape(message) + '</strong><small>' + escape(detail)
        + '</small></div></div>', unsafe_allow_html=True)
    try:
        yield
    finally:
        if not keep:
            placeholder.empty()



def action_button(*args, **kwargs):
    clicked = st.button(*args, **kwargs)
    if clicked and st.session_state.get('pending_load'):
        st.session_state.smoking_until = monotonic() + 4
        return False
    return clicked


def start_load(kind, detail, jobs, season=None):
    if st.session_state.get('pending_load'):
        st.session_state.smoking_until = monotonic() + 4
        return
    def run():
        results = {}
        for label, function, args, kwargs in jobs:
            try:
                results[label] = (True, function(*args, **kwargs))
            except Exception:
                results[label] = (False, None)
        return results
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(run)
    executor.shutdown(wait=False)
    st.session_state.pending_load = {'future': future, 'kind': kind,
        'detail': detail, 'season': season, 'theme': next_loading_theme()}


@st.fragment(run_every=1)
def poll_load():
    pending = st.session_state.get('pending_load')
    if not pending:
        return
    if pending['future'].done():
        results = pending['future'].result()
        failures = []
        for label, (ok, value) in results.items():
            if pending['kind'] == 'doubles':
                target = st.session_state.setdefault('doubles_results', {}).setdefault(pending['season'], {})
                target[label] = value if ok else {'error': True}
            elif ok and pending['kind'] == 'schedule':
                st.session_state.match_schedule = value
            elif ok:
                st.session_state.setdefault('results', {})[label] = value
            if not ok:
                failures.append(label)
        st.session_state.load_failure = ', '.join(failures)
        target = {'doubles': 'doubles-results', 'schedule': 'schedule-results', 'checks': 'competition-results'}[pending['kind']]
        if failures and pending['kind'] == 'schedule':
            target = 'load-feedback'
        st.session_state.scroll_request = {'target': target, 'nonce': str(monotonic())}
        st.session_state.pop('pending_load', None)
        st.session_state.pop('smoking_until', None)
        st.rerun()
    else:
        theme = 'smoking' if monotonic() < st.session_state.get('smoking_until', 0) else pending['theme']
        with loading_indicator(pending['detail'], theme, keep=True):
            # Keep the placeholder until the next fragment refresh.
            st.empty()

st.set_page_config(page_title='Pool Noord-Holland checker ☕', page_icon='🎱', layout='wide')
st.title('🎱 Pool Noord-Holland checker ☕')
st.caption('If you encounter any issues, please contact Matt Sinclair.')
st.markdown('<div id="load-feedback" tabindex="-1" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
if st.session_state.get('load_failure'):
    st.warning('Could not load: ' + st.session_state.load_failure + '. Please retry.')
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
        show_today = action_button("📅 See today's matches", type='primary', use_container_width=True)
    with tomorrow_column:
        show_tomorrow = action_button("📅 See tomorrow's matches", type='primary', use_container_width=True)

if show_today or show_tomorrow:
    day_offset = 1 if show_tomorrow else 0
    day_label = 'tomorrow' if day_offset else 'today'
    start_load('schedule', f"Reading {day_label}'s fixtures from CueScore…",
               [('schedule', get_scheduled_matches, (day_offset,), {})])

schedule = st.session_state.get('match_schedule')
if schedule and schedule['base_date'] != datetime.now(AMSTERDAM).date().isoformat():
    st.info('The date has changed. Select a schedule button to refresh the fixtures.')
    schedule = None
if schedule:
    st.markdown('<div id="schedule-results" tabindex="-1" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
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
                if column == 'Partnership':
                    partners = row.get('Partners') or str(value).split(' + ', 1)
                    content = '<span class="partnership-plus" aria-hidden="true">+</span>'.join(
                        '<div class="partnership-player">' + escape(str(name)) + '</div>' for name in partners)
                else:
                    content = '<div class="doubles-player">' + escape(str(value)) + '</div>'
                content += '<div class="doubles-team">' + escape(str(row.get('Team', ''))) + '</div>'
                cells.append('<td class="doubles-person">' + content + '</td>')
            else:
                if standings and column in ('Win %', 'Participation %'):
                    value = f'{float(value):.1f}%'
                cells.append('<td>' + escape(str(value)) + '</td>')
        body_rows.append('<tr>' + ''.join(cells) + '</tr>')
    table_class = 'doubles-large doubles-standings' if standings else 'doubles-large'
    if partnerships:
        table_class += ' partnership-standings'
    elif standings:
        table_class += ' individual-standings'
    st.markdown('<style>.doubles-scroll {overflow-x:auto;} '
                '.doubles-scroll .doubles-large {width:auto;border-collapse:collapse;font-size:18px;line-height:1.3;}'
                '.doubles-scroll .doubles-large th,.doubles-scroll .doubles-large td {padding:6px 8px;text-align:left;border-bottom:1px solid #8885;white-space:nowrap;}'
                '.doubles-scroll .doubles-large th {font-size:15px;font-weight:700;vertical-align:bottom;}'
                '.doubles-scroll .doubles-standings th,.doubles-scroll .doubles-standings td {text-align:center;}'
                '.doubles-scroll .doubles-standings th:nth-child(2),.doubles-scroll .doubles-standings td.doubles-person {text-align:left;}'
                '.doubles-player {font-size:18px;} '
                '.individual-standings td.doubles-person{width:170px;max-width:170px;white-space:normal!important;}'
                '.individual-standings .doubles-player,.individual-standings .doubles-team{max-width:170px;white-space:normal;overflow-wrap:anywhere;}'
                '.doubles-team {font-size:13px;opacity:.75;white-space:normal;max-width:240px;margin-top:2px;}'
                '.partnership-player{white-space:normal;overflow-wrap:anywhere;font-size:18px;max-width:220px;box-sizing:border-box;padding:3px 5px;border:1px solid #8884;border-radius:5px;background:#8881;font-weight:600;}'
                '.partnership-plus{display:block;text-align:center;font-size:12px;line-height:1;margin:3px 0;opacity:.65;}'
                '.partnership-standings tbody tr:nth-child(even){background:#8881;}'
                '.partnership-standings .doubles-person{padding-top:9px!important;padding-bottom:9px!important;}'
                '@media(max-width:600px){.doubles-scroll .partnership-standings th,.doubles-scroll .partnership-standings td{padding:6px 4px;font-size:14px;}'
                '.doubles-scroll .partnership-standings td.doubles-person{min-width:96px;width:112px;max-width:128px;white-space:normal;}'
                '.partnership-player{font-size:14px;max-width:128px;}'
                '.partnership-standings .doubles-team{font-size:11px;max-width:128px;}.doubles-scroll .partnership-standings th{font-size:13px;}}'
                '@media(max-width:600px){.doubles-scroll .individual-standings th,.doubles-scroll .individual-standings td{padding:6px 4px;font-size:14px;}'
                '.doubles-scroll .individual-standings th{font-size:13px;}'
                '.doubles-scroll .individual-standings td.doubles-person{width:112px;min-width:96px;max-width:112px;}'
                '.individual-standings .doubles-player{font-size:14px;max-width:112px;line-height:1.3;}'
                '.individual-standings .doubles-team{font-size:11px;max-width:112px;}}'
                '</style><div class="doubles-scroll"><table class="' + table_class + '"><thead><tr>' + header +
                '</tr></thead><tbody>' + ''.join(body_rows) + '</tbody></table></div>', unsafe_allow_html=True)


DOUBLES_SEASONS = {
    '2026–27': dict(TOURNAMENTS),
    '2025–26': {'Eerste klasse': 61204738, 'Tweede klasse': 61204744, 'Derde klasse': 61204750},
    '2024–25': {'Eerste klasse': 46283263, 'Tweede klasse': 46283257, 'Derde klasse': 46283269},
    '2023–24': {'Eerste klasse': 29400235, 'Tweede klasse': 29400241, 'Derde klasse': 29400247},
    '2022–23': {'Eerste klasse': 17011009, 'Tweede klasse': 17011003, 'Derde klasse': 17010994},
}
matching_version = getattr(doubles_mvp, 'NAME_MATCHING_VERSION', 'older version')
matching_ready = matching_version == '2026-10-13.1' and getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None) == '2026-10-13.1'
if st.session_state.get('doubles_ranking_version') != (10, matching_version, getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None)):
    st.session_state.pop('doubles_results', None)
    st.session_state.doubles_ranking_version = (10, matching_version, getattr(doubles_mvp, 'PARTNERSHIP_VERSION', None))


with st.container(border=True):
    st.subheader('🏆 Doubles MVP')
    st.caption(f'Build: mobile-2026-10-14.5 · Name matching: {matching_version}')
    if not matching_ready:
        st.error('Partnership checker mismatch. Upload app.py and doubles_partnerships.py from the same download into the deployed app folder, then reboot.')
        st.caption(f"Loaded checker: {doubles_mvp.__file__} · Partnership version: {getattr(doubles_mvp, 'PARTNERSHIP_VERSION', 'missing')}")
    st.caption('Choose a season and league, or load all three leagues for that season.')
    mvp_selection = None
    for season, tournaments in DOUBLES_SEASONS.items():
        heading = f'{season} · Active season' if season == '2026–27' else f'*{season}*'
        st.markdown(f'### {heading}')
        for column, label in zip(st.columns(4), [*tournaments, 'All leagues']):
            with column:
                if action_button(label, key='mvp_' + season + '_' + label, disabled=not matching_ready, type='primary', use_container_width=True):
                    mvp_selection = (season, list(tournaments) if label == 'All leagues' else [label])
    if mvp_selection:
        season, leagues = mvp_selection
        st.session_state.doubles_active_season = season
        if len(leagues) == 1:
            st.session_state.doubles_active_league = leagues[0]
        start_load('doubles', season + ' · ' + ', '.join(leagues),
                   [(league, load_doubles_league, (league, DOUBLES_SEASONS[season][league]), {})
                    for league in leagues], season=season)
    st.caption('Ranked by games won, then win percentage, then frame difference, then participation percentage. Exact ties share a rank. All players remain visible; no minimum-participation cutoff is applied. Forfeits contribute nothing to player totals.')
    st.caption('Participation = played doubles / completed fixtures of the team(s) represented. Forfeits do not count as player appearances. Former members keep their recorded results. Confirmed historical names and unique spelling variants are matched automatically; ambiguous names remain excluded.')

active_season = st.session_state.get('doubles_active_season', '2026–27')
mvp_results = st.session_state.get('doubles_results', {}).get(active_season, {})
if mvp_results:
    st.markdown('<div id="doubles-results" tabindex="-1" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
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


force_refresh = st.checkbox('Fetch fresh results (skip cache)', value=False)
st.caption('Completed checks are reused for up to 2 minutes. Select fresh results after correcting an entry.')

st.subheader('🔎 Check competition results')
check_selection = None
for column, label in zip(st.columns(4), [*TOURNAMENTS, 'All leagues']):
    with column:
        if action_button(label, key='check_' + label, type='primary', use_container_width=True):
            check_selection = list(TOURNAMENTS) if label == 'All leagues' else [label]
if check_selection:
    start_load('checks', 'Checking ' + ', '.join(check_selection),
               [(league, check_league, (league, TOURNAMENTS[league]), {'force_refresh': force_refresh})
                for league in check_selection])

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
        with loading_indicator('Loading shared ignored findings…'):
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
    action_button('Refresh shared ignores')
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


st.markdown('<div id="competition-results" tabindex="-1" style="scroll-margin-top:80px"></div>', unsafe_allow_html=True)
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
                        if action_button('Ignore from now on', key='ignore_' + identity):
                            try:
                                with loading_indicator('Saving shared findings…'):
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
            if can_manage and action_button('Restore for everyone', key='restore_' + identity):
                try:
                    with loading_indicator('Saving shared findings…'):
                        store.restore(record, password)
                    st.session_state.review_feedback = 'Restore requested. If the finding still exists it will appear in the main results.'
                    st.rerun()
                except StoreError as error:
                    st.error(str(error))

st.caption('Untouched fixtures are skipped. Missing names on recorded results are flagged. Participation is checked only when all six games have complete player selections. Straightpool is excluded from numeric score checks. Forfeits are notices, not score errors.')



if st.session_state.get("pending_load"):
    poll_load()

scroll_request = st.session_state.pop("scroll_request", None)
if scroll_request:
    scroll_to_results(scroll_request)
