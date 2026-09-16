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
