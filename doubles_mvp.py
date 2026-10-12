"""Individual doubles standings, rebuilt from public CueScore results."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fractions import Fraction
import re
import unicodedata
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

RACES = {'Eerste klasse': 5, 'Tweede klasse': 5, 'Derde klasse': 4}


def normalise(name):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', name).casefold())


def resolve_pair(label, roster):
    """Only accept a unique exact full-name or explicit first-initial/surname match."""
    parts = [part.strip() for part in label.split(' & ')]
    if len(parts) != 2:
        raise ValueError('Two doubles partners could not be identified.')
    resolved = []
    for part in parts:
        candidates = {}
        for person in roster:
            if not person.get('playerId') or not person.get('name'):
                continue
            aliases = {normalise(person['name'])}
            first, last = person.get('firstname', '').strip(), person.get('lastname', '').strip()
            if first:
                aliases.add(normalise(first[0] + '.' + last))
                initials = '.'.join(word[0] for word in first.split()) + '.'
                aliases.add(normalise(initials + last))
            if normalise(part) in aliases:
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
    stats = {}
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
        return (Fraction(stat['Won'], stat['Played']), stat['Played'], participation(stat))
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
    return {'table': table, 'forfeit_only': unranked, 'warnings': warnings, 'forfeits': forfeits,
            'history': history, 'counted': counted,
            'checked_at': datetime.now(ZoneInfo('Europe/Amsterdam')).strftime('%d %B %Y %H:%M')}


def load_league(league, tournament_id):
    def get(url):
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response
    data = get(f'https://api.cuescore.com/tournament/?id={tournament_id}').json()
    fixtures = data.get('matches')
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError('CueScore returned no fixture list.')
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
        for kind, identity, value in pool.map(fetch, jobs):
            (details if kind == 'fixture' else rosters)[identity] = value
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
                known.update({identity:person for identity,person in pool.map(fetch_person, missing_ids) if person})
            for team_id, player_ids in historical.items():
                if not isinstance(rosters.get(team_id), list):
                    continue
                included = {str(person.get('playerId')) for person in rosters[team_id]}
                rosters[team_id].extend(known[identity] for identity in player_ids - included if identity in known)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass  # Any unresolved scored pair is explicitly reported by aggregate.
    return aggregate(league, fixtures, details, rosters)
