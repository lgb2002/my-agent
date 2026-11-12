"""Remote Replit adapter; no local mock HTTP server required."""
import time
import uuid
import requests
from .config import MARKETPLACE_BASE_URL, AGENT_MODE, MARKETPLACE_AUTH_SCHEME


class MarketplaceError(Exception):
    def __init__(self, status, message, code='REMOTE_ERROR'):
        self.status = status
        self.code = code
        super().__init__(message)


class MarketplaceClient:
    def __init__(self, token, base_url=None, auth_scheme=None):
        self.base_url = (base_url or MARKETPLACE_BASE_URL).rstrip('/')
        self.token = token
        # Mock always honors the supplied OpenAPI Bearer JWT shape.
        self.auth_scheme = auth_scheme or ('bearer' if AGENT_MODE == 'mock' else MARKETPLACE_AUTH_SCHEME)
        if self.auth_scheme not in ('bearer', 'x-api-key'):
            raise ValueError('허용되지 않은 플랫폼 인증 방식')

    def request(self, method, path, payload=None, params=None, key=None):
        headers = {'X-Request-ID': str(uuid.uuid4()), 'Accept': 'application/json'}
        if self.auth_scheme == 'bearer':
            headers['Authorization'] = 'Bearer ' + self.token
        else:
            headers['X-API-Key'] = self.token
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if not key:
                raise ValueError('변경 API는 Idempotency-Key가 필요합니다.')
            headers['Idempotency-Key'] = key
        # Only retry idempotent GET requests. Never auto-retry uncertain POST.
        tries = 3 if method == 'GET' else 1
        for attempt in range(tries):
            try:
                response = requests.request(method, self.base_url + path,
                    headers=headers, json=payload, params=params, timeout=(3, 7), allow_redirects=False)
            except requests.RequestException as exc:
                if attempt < tries - 1:
                    time.sleep(0.2 * (2 ** attempt))
                    continue
                raise MarketplaceError(503, '플랫폼 통신 실패: ' + type(exc).__name__)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(0.2 * (2 ** attempt))
                continue
            if response.status_code >= 400:
                try:
                    error = response.json().get('error', {})
                    message = error.get('message', '플랫폼 API 오류')
                    code = error.get('code', 'REMOTE_ERROR')
                except (ValueError, AttributeError):
                    message, code = '플랫폼 오류 HTTP {}'.format(response.status_code), 'REMOTE_ERROR'
                raise MarketplaceError(response.status_code, message, code)
            try:
                return response.json()
            except ValueError:
                raise MarketplaceError(502, '플랫폼이 JSON이 아닌 응답을 반환했습니다.')

        raise MarketplaceError(503, '플랫폼 요청 실패')

    def me(self):
        return self.request('GET', '/api/v1/auth/me')

    def listings(self, **params):
        return self.request('GET', '/api/v1/listings', params=params)

    def listing(self, listing_id):
        return self.request('GET', '/api/v1/listings/' + listing_id)

    def reports(self, listing_id):
        return self.request('GET', '/api/v1/listings/' + listing_id + '/inspection-reports')

    def publish_report(self, listing_id, report, key):
        return self.request('POST', '/api/v1/listings/' + listing_id + '/inspection-reports', report, key=key)

    def create_action(self, action, key):
        return self.request('POST', '/api/v1/agent-actions', action, key=key)

    def action(self, action_id):
        return self.request('GET', '/api/v1/agent-actions/' + action_id)

    def action_approve(self, action_id, key):
        return self.request('POST', '/api/v1/agent-actions/' + action_id + '/approve', key=key)

    def action_reject(self, action_id, key):
        return self.request('POST', '/api/v1/agent-actions/' + action_id + '/reject', key=key)

    def action_execute(self, action_id, key):
        return self.request('POST', '/api/v1/agent-actions/' + action_id + '/execute', key=key)

    def offers(self, listing_id):
        return self.request('GET', '/api/v1/offers', params={'listing_id': listing_id})

    def accept_offer(self, offer_id, version, key):
        return self.request('POST', '/api/v1/offers/' + offer_id + '/accept',
                            {'expected_version': version}, key=key)

    def handover_checks(self, tx_id):
        return self.request('GET', '/api/v1/transactions/' + tx_id + '/handover-checks')

    def create_handover_check(self, tx_id, payload, key):
        return self.request('POST', '/api/v1/transactions/' + tx_id + '/handover-checks', payload, key=key)
