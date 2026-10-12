"""Shared, durable ignores. Only the server talks to Supabase."""
import hashlib
import hmac
import json
from datetime import datetime, timezone
import requests

ISSUE_TITLES = {
    'format_issues': 'Format issue', 'race_to_issues': 'Race-to issue',
    'score_issues': 'Score issue', 'player_issues': 'Player participation issue',
    'missing_player_issues': 'Missing player issue', 'special_scores': 'Special result',
}
ERROR_KEYS = tuple(key for key in ISSUE_TITLES if key != 'special_scores')


class StoreError(Exception):
    pass


def canonical(value):
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if key != 'finished'}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def finding_id(league, tournament_id, kind, issue):
    # Include the observed details, not just a fixture ID: changed findings resurface.
    value = {'version': 1, 'league': league, 'tournament': tournament_id,
             'kind': kind, 'issue': canonical(issue)}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def finding_record(league, tournament_id, kind, issue, reason=''):
    title = 'Forfeit notice' if issue.get('kind') == 'forfeit' else ISSUE_TITLES[kind]
    return {'fingerprint': finding_id(league, tournament_id, kind, issue),
            'league': league, 'kind': kind, 'title': title,
            'snapshot': canonical(issue), 'reason': reason.strip(),
            'ignored_at': datetime.now(timezone.utc).isoformat()}


class ReviewStore:
    def __init__(self, url='', key='', admin_password=''):
        self.url = url.rstrip('/')
        self.key = key
        self.admin_password = admin_password

    @property
    def configured(self):
        return bool(self.url and self.key)

    @property
    def writable(self):
        return self.configured and bool(self.admin_password)

    def authorized(self, password):
        return self.writable and hmac.compare_digest(
            str(password).encode(), self.admin_password.encode())

    def _request(self, method, **kwargs):
        if not self.configured:
            raise StoreError('Shared storage is not configured.')
        headers = {'apikey': self.key, 'Content-Type': 'application/json'}
        # Legacy service-role JWTs require Authorization; new secret keys do not.
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + self.key
        headers.update(kwargs.pop('headers', {}))
        try:
            response = requests.request(method, self.url + '/rest/v1/pool_ignored_findings',
                                        headers=headers, timeout=15, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            # Never expose URLs with credentials, headers, or backend error bodies.
            raise StoreError('Shared ignored results could not be updated or loaded. Please retry.') from None

    def load(self):
        records = {}
        offset = 0
        while True:
            response = self._request('GET', params={
                'select': '*', 'order': 'fingerprint.asc', 'offset': offset, 'limit': 500})
            try:
                page = response.json()
                if not isinstance(page, list):
                    raise ValueError()
                for row in page:
                    if not isinstance(row, dict) or not all(k in row for k in (
                            'fingerprint', 'league', 'kind', 'title', 'snapshot', 'ignored_at')):
                        raise ValueError()
                    records[row['fingerprint']] = row
            except (ValueError, TypeError):
                raise StoreError('Shared storage returned an unreadable response. No findings were hidden.') from None
            if not page:
                return records
            offset += len(page)

    def ignore(self, record, password):
        if not self.authorized(password):
            raise StoreError('Enter the administrator password to ignore findings.')
        response = self._request('POST', params={'on_conflict': 'fingerprint'},
                                headers={'Prefer': 'resolution=merge-duplicates,return=representation'},
                                json=record)
        try:
            rows = response.json()
            if not rows or rows[0]['fingerprint'] != record['fingerprint']:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise StoreError('The save could not be confirmed. Refresh shared ignores before retrying.') from None

    def restore(self, record, password):
        if not self.authorized(password):
            raise StoreError('Enter the administrator password to restore findings.')
        self._request('DELETE', params={'fingerprint': 'eq.' + record['fingerprint'],
                                       'ignored_at': 'eq.' + record['ignored_at']})
