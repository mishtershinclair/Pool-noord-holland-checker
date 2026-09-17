"""Network completeness checks around the unchanged validator."""
import types
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from time import monotonic
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import checker_core

TOURNAMENTS = checker_core.TOURNAMENTS


CACHE_SECONDS = 120
_cache = {}
_check_lock = Lock()


def clear_cache():
    with _check_lock:
        _cache.clear()


def check_league(league, tournament_id, force_refresh=False):
    # Serialize checks across browser sessions to limit load on CueScore.
    with _check_lock:
        key = (league, tournament_id)
        cached = _cache.get(key)
        if not force_refresh and cached and monotonic() - cached[0] < CACHE_SECONDS:
            result = deepcopy(cached[1])
            result["from_cache"] = True
            return result
        result = _check_league(league, tournament_id)
        result["from_cache"] = False
        if not result["incomplete"]:
            _cache[key] = (monotonic(), deepcopy(result))
        else:
            _cache.pop(key, None)
        return result


def _check_league(league, tournament_id):
    failures = []
    pending = {}
    executor = ThreadPoolExecutor(max_workers=4)
    class Transport:
        RequestException = requests.RequestException
        @staticmethod
        def get(url, **kwargs):
            try:
                response = pending[url].result() if url in pending else requests.get(url, **kwargs)
                response.raise_for_status()
                if 'api.cuescore.com' in url:
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get('matches'), list) or not data['matches']:
                        raise ValueError('CueScore returned no fixture list.')
                    # Fetch ahead; the original parser consumes responses in fixture order.
                    for fixture in data['matches']:
                        detail_url = (f'https://cuescore.com/ajax/match/matchDetails.php?'
                                      f'tournamentId={tournament_id}&id={fixture["matchId"]}')
                        if detail_url not in pending:
                            pending[detail_url] = executor.submit(requests.get, detail_url, timeout=30)
                elif not BeautifulSoup(response.text, 'html.parser').select('tr.match.public'):
                    raise ValueError('CueScore returned no individual match rows.')
                return response
            except (requests.RequestException, ValueError) as exc:
                failures.append(url)
                raise requests.RequestException(str(exc)) from exc
    # Each call has isolated globals; concurrent sessions cannot affect each other.
    namespace = dict(vars(checker_core), requests=Transport)
    check = types.FunctionType(checker_core.check_tournament.__code__, namespace)
    try:
        result = check(league, tournament_id)
    except Exception:
        result = dict(league=league, error=True, format_issues=[], race_to_issues=[], score_issues=[], player_issues=[], special_scores=[])
        failures.append('Unexpected CueScore data')
    executor.shutdown(wait=True, cancel_futures=True)
    result['incomplete'] = bool(failures) or result['error']
    result['failed_requests'] = len(failures)
    result['checked_at'] = datetime.now(ZoneInfo('Europe/Amsterdam')).strftime('%d %B %Y at %H:%M:%S')
    return result


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
