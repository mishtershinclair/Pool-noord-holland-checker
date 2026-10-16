"""Skip only clearly unplayed future fixtures in the active season."""
from datetime import datetime
from zoneinfo import ZoneInfo

ACTIVE_TOURNAMENTS = {83574424, 83574427, 83574403}
AMSTERDAM = ZoneInfo('Europe/Amsterdam')


def fixtures_to_check(fixtures, tournament_id, now=None):
    if str(tournament_id) not in {str(i) for i in ACTIVE_TOURNAMENTS}:
        return list(fixtures)
    today = (now or datetime.now(AMSTERDAM)).astimezone(AMSTERDAM).date()
    selected = []
    for fixture in fixtures:
        # Unknown statuses and incomplete dates are included conservatively.
        if fixture.get('matchstatus') != 'waiting':
            selected.append(fixture)
            continue
        if (fixture.get('stoptime') or fixture.get('frames') or fixture.get('sets')
                or any(fixture.get(k) not in (None, '', 0, '0') for k in ('scoreA', 'scoreB'))):
            selected.append(fixture)
            continue
        try:
            start = datetime.fromisoformat(fixture.get('starttime', '').replace('Z', '+00:00'))
            if start.tzinfo is None or start.astimezone(AMSTERDAM).date() <= today:
                selected.append(fixture)
        except (ValueError, TypeError, AttributeError):
            selected.append(fixture)
    return selected
