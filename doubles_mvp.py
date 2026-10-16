"""Individual doubles standings, rebuilt from public CueScore results."""
PARTNERSHIP_VERSION = '2026-10-13.1'
PARTNERSHIP_MIN_MATCHES = 5

NAME_MATCHING_VERSION = '2026-10-13.1'

from fixture_filter import fixtures_to_check
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fractions import Fraction
import re
import unicodedata
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

# User-confirmed historical spelling, attached to a stable CueScore identity.
# Applied only when that identity is already in the team's roster/history.
PLAYER_ALIASES = {'1163808': ('M.Yağlı',)}

RACES = {'Eerste klasse': 5, 'Tweede klasse': 5, 'Derde klasse': 4}


def normalise(name):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', name).casefold())


# Team-scoped decisions confirmed by the league administrator.
CONFIRMED_NAMES = [{'team': '46648447', 'alias': 'M.', 'playerId': '3369296', 'name': 'Mostafa Hosny'}, {'team': '46648447', 'alias': 'M.H', 'playerId': '3369296', 'name': 'Mostafa Hosny'}, {'team': '62160400', 'alias': 'G.Richiuso', 'playerId': '19517899', 'name': 'Greg Richiuso'}, {'team': '29599939', 'alias': 'T.', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '29599939', 'alias': 'T..', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '29599939', 'alias': 'T.B', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '29599939', 'alias': 'T.B.', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '29599939', 'alias': 'T.O.', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '29599939', 'alias': 'T.Tolga', 'playerId': '1702384', 'name': 'T. Olga'}, {'team': '1176481', 'alias': 'J.Torres', 'playerId': '1559251', 'name': 'Jun Torres'}, {'team': '64354837', 'alias': 'B.blem', 'playerId': '1163470', 'name': 'Bob B.'}, {'team': '63569641', 'alias': 'V.van den Berg', 'playerId': '62590984', 'name': 'Vanessa'}, {'team': '6096494', 'alias': 'G.Richiuso', 'playerId': '19517899', 'name': 'Greg Richiuso'}, {'team': '46515838', 'alias': 'T.WH', 'playerId': '34200361', 'name': 'Tofail Wagid Hosain'}, {'team': '6229472', 'alias': 'J.DOLLFUS', 'playerId': '17878582', 'name': 'J-P D'}, {'team': '17953762', 'alias': 'A.".L', 'playerId': '37771660', 'name': 'A. "Sakalam"'}, {'team': '17953762', 'alias': 'A.“.Lugtu', 'playerId': '37771660', 'name': 'A. "Sakalam"'}, {'team': '9200494', 'alias': 'M.A', 'playerId': '52502593', 'name': 'Moudar Ali'}, {'team': '1176664', 'alias': 'H.Vink', 'playerId': '1162875', 'name': 'Harmen V'}, {'team': '8092256', 'alias': 'A.Wever', 'playerId': '9703372', 'name': 'Anthony Wever'}, {'team': '8092256', 'alias': 'M.A', 'playerId': '52502593', 'name': 'Moudar Ali'}, {'team': '64056430', 'alias': 'C.Sarbanescu', 'playerId': '6783906', 'name': 'Cosmin Sarbanescu'}, {'team': '3596529', 'alias': 'K.Steffen', 'playerId': '5216947', 'name': 'Steffen Klein'}, {'team': '2926212', 'alias': 'M.Yağlı', 'playerId': '1163808', 'name': 'Muhsin Yagli'}, {'team': '1176481', 'alias': 'R.C.Torres', 'playerId': '40296037', 'name': 'Renato Torres'}, {'team': '1176481', 'alias': 'R.Castañeda', 'playerId': '40296037', 'name': 'Renato Torres'}, {'team': '1176481', 'alias': 'R.Torres Jr.', 'playerId': '40296037', 'name': 'Renato Torres'}, {'team': '63272905', 'alias': 'A.A.Ferreira', 'playerId': '5450329', 'name': 'Antonio.♎️ Alexander ferreira.'}, {'team': '63272905', 'alias': 'A.Ferreira', 'playerId': '5450329', 'name': 'Antonio.♎️ Alexander ferreira.'}, {'team': '63272905', 'alias': 'F.k.Antonio  A🐑🦁', 'playerId': '5450329', 'name': 'Antonio.♎️ Alexander ferreira.'}, {'team': '63272905', 'alias': 'F.k.Antonio alexander', 'playerId': '5450329', 'name': 'Antonio.♎️ Alexander ferreira.'}, {'team': '64354837', 'alias': 'H.Wagid Hosain', 'playerId': '34200361', 'name': 'Tofail Wagid Hosain'}, {'team': '46515838', 'alias': 'H.Wagid Hosain', 'playerId': '34200361', 'name': 'Tofail Wagid Hosain'}, {'team': '46620241', 'alias': 'M.Konijnenberg', 'playerId': '30252431', 'name': 'Michelle Konynenberg-Harrison'}]
UNRESOLVED_NAMES = [['2806543', 'J.TSANG'], ['27817732', 'M..'], ['27817732', 'M.Valk'], ['1176481', 'K.Oei'], ['2852247', 'M.Donini'], ['1176605', 'B.Rossmark']]


def spelling_key(value):
    value = unicodedata.normalize('NFKD', value.casefold().replace('ı', 'i'))
    return ''.join(c for c in value if c.isalnum())


def prepare_rosters(fixtures, rosters):
    # Include explicitly confirmed former/guest players even if no longer members.
    prepared = {team: [dict(p) for p in roster] for team, roster in rosters.items() if isinstance(roster, list)}
    teams = {str((f.get('player'+side) or {}).get('teamId')) for f in fixtures for side in ('A','B')}
    for team in teams:
        roster = prepared.setdefault(team, [])
        for person in roster:
            person['_confirmed_aliases'] = []
            person['_blocked_aliases'] = [alias for tid, alias in UNRESOLVED_NAMES if tid == team]
        for rule in CONFIRMED_NAMES:
            if rule['team'] != team: continue
            person = next((p for p in roster if str(p.get('playerId')) == rule['playerId']), None)
            if person is None:
                person = {'playerId': rule['playerId'], 'name': rule['name'], 'firstname': '', 'lastname': '',
                          '_confirmed_aliases': [], '_blocked_aliases': [alias for tid,alias in UNRESOLVED_NAMES if tid==team]}
                roster.append(person)
            person['_confirmed_aliases'].append(rule['alias'])
    return prepared


def resolve_pair(label, roster):
    """Only accept a unique exact full-name or explicit first-initial/surname match."""
    parts = [part.strip() for part in label.split(' & ')]
    if len(parts) != 2:
        raise ValueError('Two doubles partners could not be identified.')
    resolved = []
    for part in parts:
        if any(normalise(part) == normalise(a) for p in roster for a in p.get('_blocked_aliases', [])):
            raise ValueError(f'Player “{part}” remains unresolved by administrator decision.')
        explicit = {str(p['playerId']):p for p in roster if any(normalise(part)==normalise(a) for a in p.get('_confirmed_aliases', []))}
        if len(explicit) == 1:
            resolved.append(next(iter(explicit.values())))
            continue
        candidates = {}
        for person in roster:
            if not person.get('playerId') or not person.get('name'):
                continue
            aliases = {normalise(person['name'])}
            aliases.update(normalise(alias) for alias in PLAYER_ALIASES.get(str(person['playerId']), ()))
            first, last = person.get('firstname', '').strip(), person.get('lastname', '').strip()
            if first:
                aliases.add(normalise(first[0] + '.' + last))
                initials = '.'.join(word[0] for word in first.split()) + '.'
                aliases.add(normalise(initials + last))
            if normalise(part) in aliases or (len(spelling_key(part)) >= 4 and spelling_key(part) in {spelling_key(a) for a in aliases}):
                candidates[str(person['playerId'])] = person
        if len(candidates) != 1:
            raise ValueError(f'Player “{part}” is missing from the roster or cannot be identified uniquely.')
        resolved.append(next(iter(candidates.values())))
    if str(resolved[0]['playerId']) == str(resolved[1]['playerId']):
        raise ValueError('The same player appears twice in a doubles pair.')
    return resolved


def read_doubles(html):
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('tr.match.public')
    if not rows:
        raise ValueError('No individual match rows were returned.')
    result = []
    for row in rows:
        if row.get('data-match-type') != '2':
            continue
        game = {'id': row.get('id'), 'number': row.get('data-matchno', '?'),
                'finished': 'finished' in row.get('class', []),
                'discipline': row.get('data-discipline'), 'race': row.get('data-race-to')}
        for side in ('A', 'B'):
            name = row.select_one(f'.player{side} .name')
            score = row.select_one(f'.score{side} input')
            game['player' + side] = name.get_text(' ', strip=True) if name else ''
            game['score' + side] = score.get('value', '').strip() if score else ''
        result.append(game)
    return result


def aggregate(league, fixtures, details, rosters):
    rosters = prepare_rosters(fixtures, rosters)
    stats = {}
    partnerships = {}
    warnings, forfeits, history = [], [], []
    counted = 0
    seen = set()
    team_fixtures = defaultdict(set)
    for fixture in fixtures:
        if fixture.get('matchstatus') == 'finished':
            for side in ('A', 'B'):
                team_fixtures[str((fixture.get('player' + side) or {}).get('teamId'))].add(str(fixture['matchId']))
    for fixture in fixtures:
        fixture_id = str(fixture['matchId'])
        context = {'Date': fixture.get('starttime', ''), 'Match': fixture.get('matchno', '?'),
                   'Teams': f"{(fixture.get('playerA') or {}).get('name', '?')} vs {(fixture.get('playerB') or {}).get('name', '?')}"}
        try:
            payload = details[fixture_id]
            if isinstance(payload, Exception):
                raise ValueError('Fixture could not be retrieved; retry to complete the standings.')
            games = read_doubles(payload)
            if not games and fixture.get('matchstatus') == 'finished':
                raise ValueError('Completed fixture contains no doubles game; check its format.')
        except (ValueError, KeyError) as error:
            warnings.append(dict(context, Problem=str(error)))
            continue
        for game in games:
            if not game['finished']:
                continue
            for side in ('A', 'B'):
                team_fixtures[str((fixture.get('player' + side) or {}).get('teamId'))].add(fixture_id)
            info = dict(context, **{'Individual match': game['number']})
            try:
                if not game['id']:
                    raise ValueError('The game has no identifier.')
                if game['id'] in seen:
                    continue
                seen.add(game['id'])
                a, b = game['scoreA'].upper(), game['scoreB'].upper()
                ff = (a == 'FF') != (b == 'FF') and all(x in ('FF', '', '-') or x.isdigit() for x in (a, b))
                if game['discipline'] != '4' or game['race'] != str(RACES[league]):
                    raise ValueError('Doubles discipline or race length differs from this league’s rules.')
                if not ff and not (a.isdigit() and b.isdigit()):
                    raise ValueError('Unrecognised special score; not counted.')
                if not ff:
                    x, y = int(a), int(b)
                    race = RACES[league]
                    if not ((x == race and 0 <= y < race) or (y == race and 0 <= x < race)):
                        raise ValueError('Invalid final score; not counted.')
                pairs = []
                for side in ('A', 'B'):
                    team = fixture.get('player' + side) or {}
                    roster = rosters.get(str(team.get('teamId')))
                    if not isinstance(roster, list):
                        raise ValueError(f"Roster unavailable for {team.get('name', 'team')}.")
                    pairs.append(resolve_pair(game['player' + side], roster))
                if len({str(p['playerId']) for pair in pairs for p in pair}) != 4:
                    raise ValueError('A player appears on both sides; not counted.')
                # Resolve and validate all four players before changing any totals.
                winner = (1 if a == 'FF' else 0) if ff else (0 if x > y else 1)
                if ff:
                    forfeits.append(dict(info, **{'Pair A': ' & '.join(p['name'] for p in pairs[0]),
                                                  'Score': a + '–' + b,
                                                  'Pair B': ' & '.join(p['name'] for p in pairs[1])}))
                    continue
                for side_index, pair in enumerate(pairs):
                    team_name = (fixture.get('player' + ('A' if side_index == 0 else 'B')) or {}).get('name', '?')
                    identity = tuple(sorted(str(p['playerId']) for p in pair))
                    partnership = partnerships.setdefault(identity, {
                        'Partnership': ' + '.join(p['name'] for p in sorted(pair, key=lambda p: str(p['playerId']))),
                        'teams': set(), 'Played': 0, 'Won': 0, 'Lost': 0,
                        'Racks won': 0, 'Racks lost': 0})
                    partnership['teams'].add(team_name)
                    partnership['Played'] += 1
                    partnership['Won' if side_index == winner else 'Lost'] += 1
                    partnership['Racks won'] += x if side_index == 0 else y
                    partnership['Racks lost'] += y if side_index == 0 else x
                    for person in pair:
                        identity = str(person['playerId'])
                        stat = stats.setdefault(identity, {'Player': person['name'], 'teams': set(), 'team_ids': set(),
                            'Played': 0, 'Won': 0, 'Lost': 0, 'Racks won': 0, 'Racks lost': 0})
                        stat['teams'].add(team_name)
                        won = side_index == winner
                        stat['team_ids'].add(str((fixture.get('player' + ('A' if side_index == 0 else 'B')) or {}).get('teamId')))
                        stat['Played'] += 1
                        stat['Won' if won else 'Lost'] += 1
                        stat['Racks won'] += x if side_index == 0 else y
                        stat['Racks lost'] += y if side_index == 0 else x
                entry = dict(info, **{'Pair A': ' & '.join(p['name'] for p in pairs[0]),
                                     'Score': a + '–' + b, 'Pair B': ' & '.join(p['name'] for p in pairs[1])})
                counted += 1
                history.append(entry)
            except (ValueError, KeyError, TypeError) as error:
                warnings.append(dict(info, Problem=str(error)))
    def participation(stat):
        opportunities = set().union(*(team_fixtures[team] for team in stat['team_ids']))
        return Fraction(stat['Played'], len(opportunities)) if opportunities else Fraction(0)

    def rank_key(stat):
        return (stat['Won'], Fraction(stat['Won'], stat['Played']),
                stat['Racks won'] - stat['Racks lost'], participation(stat))
    ordered = sorted(stats.values(), key=lambda row: (*(-v for v in rank_key(row)), row['Player'].casefold()))
    table, unranked = [], []
    previous = None
    rank = 0
    for stat in ordered:
        key = rank_key(stat)
        if stat['Played']:
            if key != previous:
                rank = len(table) + 1
            previous = key
        row = {'Rank': rank if stat['Played'] else None, 'Player': stat['Player'],
               'Team': ', '.join(sorted(stat['teams'])),
               **{k:stat[k] for k in ('Played','Won','Lost')},
               'Win %': round(100 * stat['Won'] / stat['Played'], 1) if stat['Played'] else 0.0,
               **{k:stat[k] for k in ('Racks won','Racks lost')},
               'Difference': stat['Racks won']-stat['Racks lost'],
               'Participation %': round(float(participation(stat)) * 100, 1)}
        (table if stat['Played'] else unranked).append(row)
    def partnership_key(stat):
        return (Fraction(stat['Won'], stat['Played']), stat['Won'],
                stat['Racks won'] - stat['Racks lost'])

    partnership_table = []
    previous, rank, qualified_count = None, 0, 0
    for stat in sorted(partnerships.values(), key=lambda row: (
            *(-v for v in partnership_key(row)), row['Partnership'].casefold())):
        qualified = stat['Played'] >= PARTNERSHIP_MIN_MATCHES
        if qualified:
            qualified_count += 1
            key = partnership_key(stat)
            if key != previous:
                rank = qualified_count
            previous = key
        partnership_table.append({
            'Rank': rank if qualified else '—', 'Partnership': stat['Partnership'],
            'Team': ', '.join(sorted(stat['teams'])),
            **{k: stat[k] for k in ('Played', 'Won', 'Lost')},
            'Win %': round(100 * stat['Won'] / stat['Played'], 1),
            **{k: stat[k] for k in ('Racks won', 'Racks lost')},
            'Difference': stat['Racks won'] - stat['Racks lost'],
            'Status': 'Qualified' if qualified else 'Provisional'})
    top_partnerships = [row for row in partnership_table if row['Status'] == 'Qualified'][:3]
    return {'partnerships': partnership_table, 'top_partnerships': top_partnerships,
            'table': table, 'forfeit_only': unranked, 'warnings': warnings, 'forfeits': forfeits,
            'history': history, 'counted': counted,
            'checked_at': datetime.now(ZoneInfo('Europe/Amsterdam')).strftime('%d %B %Y %H:%M')}


def load_league(league, tournament_id, progress=None):
    progress = progress or (lambda value, label: None)
    progress(None, "Reading fixture list…")
    def get(url):
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response
    data = get(f'https://api.cuescore.com/tournament/?id={tournament_id}').json()
    fixtures = data.get('matches')
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError('CueScore returned no fixture list.')
    fixtures = fixtures_to_check(fixtures, tournament_id)
    if not fixtures:
        return aggregate(league, [], {}, {})
    teams = {str(team['teamId']) for f in fixtures for team in (f.get('playerA') or {}, f.get('playerB') or {}) if team.get('teamId')}
    jobs = [('fixture',str(f['matchId']), f'https://cuescore.com/ajax/match/matchDetails.php?tournamentId={tournament_id}&id={f["matchId"]}') for f in fixtures]
    jobs += [('roster',team,f'https://api.cuescore.com/participant/?id={team}') for team in teams]
    def fetch(job):
        kind, identity, url = job
        try:
            response = get(url)
            if kind == 'fixture':
                return kind, identity, response.text
            data = response.json()
            members = data.get('members')
            if not isinstance(members, list):
                raise ValueError('Missing members')
            captain = data.get('captain')
            if isinstance(captain, dict):
                members = members + [captain]
            return kind, identity, members
        except (requests.RequestException, ValueError, AttributeError) as error:
            return kind, identity, ValueError('Public data unavailable')
    details, rosters = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for completed, (kind, identity, value) in enumerate(pool.map(fetch, jobs), 1):
            (details if kind == 'fixture' else rosters)[identity] = value
            progress(.8 * completed / len(jobs), f'Read {completed} of {len(jobs)} fixture/roster records')
    progress(.8, 'Checking historical player names…')
    # The season MVP page retains public player/team associations when current
    # rosters change. Use its IDs, then the participant endpoint for name fields.
    try:
        url = data.get('url', '')
        if url.startswith('https://cuescore.com/tournament/'):
            soup = BeautifulSoup(get(url.rstrip('/') + '/mvp').text, 'html.parser')
            historical = defaultdict(set)
            for row in soup.select('tr'):
                player = row.select_one('a[href*="/player/"]')
                team = row.select_one('a[href*="/team/"]')
                if not player or not team:
                    continue
                player_id = player['href'].rstrip('/').split('/')[-1]
                team_id = team['href'].rstrip('/').split('/')[-1]
                if player_id.isdigit() and team_id in teams:
                    historical[team_id].add(player_id)
            existing = {str(person.get('playerId')) for roster in rosters.values()
                        if isinstance(roster, list) for person in roster}
            missing_ids = set().union(*historical.values()) - existing if historical else set()
            def fetch_person(identity):
                try:
                    person = get(f'https://api.cuescore.com/participant/?id={identity}').json()
                    return identity, person if str(person.get('playerId')) == identity else None
                except (requests.RequestException, ValueError, AttributeError):
                    return identity, None
            known = {str(person['playerId']): person for roster in rosters.values()
                     if isinstance(roster, list) for person in roster if person.get('playerId')}
            with ThreadPoolExecutor(max_workers=4) as pool:
                for completed, (identity, person) in enumerate(pool.map(fetch_person, missing_ids), 1):
                    if person: known[identity] = person
                    progress(.8 + .15 * completed / len(missing_ids), f'Checked {completed} of {len(missing_ids)} historical profiles')
            for team_id, player_ids in historical.items():
                if not isinstance(rosters.get(team_id), list):
                    continue
                included = {str(person.get('playerId')) for person in rosters[team_id]}
                rosters[team_id].extend(known[identity] for identity in player_ids - included if identity in known)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass  # Any unresolved scored pair is explicitly reported by aggregate.
    progress(.95, 'Calculating standings…')
    result = aggregate(league, fixtures, details, rosters)
    progress(1.0, 'Standings ready')
    return result
