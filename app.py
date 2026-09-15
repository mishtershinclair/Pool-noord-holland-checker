import streamlit as st
from service import TOURNAMENTS, check_league

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
            total = sum(len(result[key]) for key in ['format_issues', 'score_issues', 'player_issues'])
            if result['incomplete']:
                st.warning('Check incomplete — retry')
            elif total:
                st.error(f'{total} issue(s) detected')
            else:
                st.success('No invalid entries found')
            st.caption(f"Format: {len(result['format_issues'])} · Scores: {len(result['score_issues'])} · Players: {len(result['player_issues'])}")
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
        for key, title in [('format_issues', 'Format issue'), ('score_issues', 'Score issue'), ('player_issues', 'Player participation issue'), ('special_scores', 'Special result')]:
            for issue in result[key]:
                with st.container(border=True):
                    st.markdown(f'**{title}**')
                    fixture_context(league, issue['fixture'])
                    if key in ('score_issues', 'special_scores'):
                        match = issue['match']
                        game_details(match)
                        if key == 'score_issues':
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

st.caption('Uses the existing checker rules: untouched fixtures are skipped; participation is checked when all six games are configured; Straightpool is excluded from ordinary race-to score checks. Special results are reported separately.')
