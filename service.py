"""Network completeness checks around the unchanged validator."""
import types
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import checker_core

TOURNAMENTS = checker_core.TOURNAMENTS


def check_league(league, tournament_id):
    failures = []
    class Transport:
        RequestException = requests.RequestException
        @staticmethod
        def get(url, **kwargs):
            try:
                response = requests.get(url, **kwargs)
                response.raise_for_status()
                if 'api.cuescore.com' in url:
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get('matches'), list) or not data['matches']:
                        raise ValueError('CueScore returned no fixture list.')
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
        result = dict(league=league, error=True, format_issues=[], score_issues=[], player_issues=[], special_scores=[])
        failures.append('Unexpected CueScore data')
    result['incomplete'] = bool(failures) or result['error']
    result['failed_requests'] = len(failures)
    result['checked_at'] = datetime.now(ZoneInfo('Europe/Amsterdam')).strftime('%d %B %Y at %H:%M:%S')
    return result
