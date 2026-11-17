"""ProjectAgain v0.4 API adapter. GET only in live mode via services.marketplace.

Real tokens are user-owned opaque bearer grants, *not* JWTs or a shared app key.
No remote calls are made by importing this module.
"""
import time
import uuid
from urllib.parse import urlsplit

import requests

from .config import MARKETPLACE_BASE_URL, MARKETPLACE_AUTH_SCHEME
from .request_context import include_demo, force_refresh_for_get, ensure_broker_access


class MarketplaceError(Exception):
    def __init__(self, status, message, code='REMOTE_ERROR'):
        self.status = status
        self.code = code
        super().__init__(message)


def origin_only(raw):
    """Accept https://host or the old documented https://host/api/v1, once."""
    parsed = urlsplit((raw or '').strip())
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('플랫폼 주소는 https://호스트 형식이어야 합니다.')
    if parsed.path.rstrip('/') not in ('', '/api/v1'):
        raise ValueError('플랫폼 주소에 추가 경로를 넣을 수 없습니다.')
    return '{}://{}'.format(parsed.scheme, parsed.netloc).rstrip('/')


class MarketplaceClient:
    def __init__(self, token='', base_url=None, auth_scheme=None):
        self.base_url = origin_only(base_url if base_url is not None else MARKETPLACE_BASE_URL)
        self.token = str(token or '').strip()
        self.auth_scheme = auth_scheme or MARKETPLACE_AUTH_SCHEME
        if self.auth_scheme != 'bearer':
            raise ValueError('ProjectAgain의 위임 토큰은 Bearer 방식입니다.')

    def request(self, method, path, payload=None, params=None, key=None):
        method = method.upper()
        if not path.startswith('/api/v1/') or '://' in path or '\\' in path or '?' in path or '#' in path:
            raise MarketplaceError(400, '허용되지 않은 API 경로입니다.', 'INVALID_PATH')
        # On broker mode, every private action checks current access before use.
        # A disconnected broker blocks access rather than reusing an old token.
        try:
            fresh_access = ensure_broker_access() if self.token else None
        except Exception:
            raise MarketplaceError(401, 'ProjectAgain 연결 상태를 확인할 수 없어요.', 'BROKER_UNAVAILABLE') from None
        if fresh_access:
            self.token = fresh_access
        headers = {'X-Request-ID': str(uuid.uuid4()), 'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        elif path.startswith(('/api/v1/auth/', '/api/v1/offers', '/api/v1/buyer-preferences/', '/api/v1/agent/', '/api/v1/transactions/')):
            raise MarketplaceError(401, '개인 데이터 조회에는 ProjectAgain 계정 로그인이 필요합니다.', 'DELEGATION_REQUIRED')
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if not key:
                raise ValueError('변경 API에는 Idempotency-Key가 필요합니다.')
            headers['Idempotency-Key'] = key
        tries = 4 if method == 'GET' else 1
        refreshed_after_401 = False
        for attempt in range(tries):
            try:
                response = requests.request(method, self.base_url + path, headers=headers,
                    json=payload, params=params, timeout=(3, 7), allow_redirects=False)
            except requests.RequestException as exc:
                if attempt < tries - 1:
                    time.sleep(0.2 * (2 ** attempt))
                    continue
                raise MarketplaceError(503, '플랫폼 연결 실패: ' + type(exc).__name__, 'NETWORK_ERROR') from None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(0.2 * (2 ** attempt))
                continue
            if 300 <= response.status_code < 400:
                raise MarketplaceError(502, '예상하지 않은 API 이동 응답입니다.', 'REDIRECT_BLOCKED')
            if response.status_code == 401 and method == 'GET' and self.token and not refreshed_after_401:
                # One safe GET retry only. Broker uses the observed access-token
                # hash to avoid double rotation across concurrent requests.
                refreshed_after_401 = True
                try:
                    fresh = force_refresh_for_get(self.token)
                except Exception:
                    fresh = None
                if fresh and fresh != self.token:
                    self.token = fresh
                    headers['Authorization'] = 'Bearer ' + fresh
                    continue
            if response.status_code >= 400:
                try:
                    err = response.json().get('error', {})
                    msg = str(err.get('message') or '플랫폼 API 오류')[:300]
                    if self.token and len(self.token) > 12:
                        msg = msg.replace(self.token, '[REDACTED]')
                    code = str(err.get('code') or 'REMOTE_ERROR')[:80]
                except (ValueError, AttributeError, TypeError):
                    msg, code = '플랫폼 오류 HTTP {}'.format(response.status_code), 'REMOTE_ERROR'
                raise MarketplaceError(response.status_code, msg, code)
            try:
                return response.json()
            except ValueError:
                raise MarketplaceError(502, '플랫폼 응답이 JSON이 아닙니다.', 'INVALID_RESPONSE') from None
        raise MarketplaceError(503, '플랫폼 요청 실패', 'REMOTE_ERROR')

    def me(self):
        return self.request('GET', '/api/v1/auth/me')

    def context(self):
        return self.request('GET', '/api/v1/agent/context')

    def listings(self, **params):
        params = dict(params)
        # Explicit filter for diagnostics overrides session default.
        params.setdefault('include_demo', 'true' if include_demo() else 'false')
        if not params.get('q'):
            params.pop('q', None)
        result = self.request('GET', '/api/v1/listings', params=params)
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise MarketplaceError(502, '매물 목록 형식이 계약과 다릅니다.', 'CONTRACT_MISMATCH')
        return result

    def listing(self, listing_id):
        # Strict UUID prevents untrusted prompt values from altering routing.
        try:
            listing_id = str(uuid.UUID(str(listing_id)))
        except (ValueError, TypeError, AttributeError):
            raise MarketplaceError(422, '유효한 매물 UUID가 필요합니다.', 'INVALID_ID') from None
        params = {'include_demo': 'true'} if include_demo() else None
        return self.request('GET', '/api/v1/listings/' + listing_id, params=params)

    def buyer_preferences(self):
        return self.request('GET', '/api/v1/buyer-preferences/me')

    def reports(self, listing_id):
        return self.request('GET', '/api/v1/listings/' + str(uuid.UUID(listing_id)) + '/inspection-reports')

    def offers(self, listing_id):
        return self.request('GET', '/api/v1/offers', params={'listing_id': listing_id})

    def offer(self, offer_id):
        return self.request('GET', '/api/v1/offers/' + str(uuid.UUID(str(offer_id))))

    def action(self, action_id):
        return self.request('GET', '/api/v1/agent-actions/' + str(uuid.UUID(str(action_id))))

    def handover_checks(self, tx_id):
        return self.request('GET', '/api/v1/transactions/' + str(uuid.UUID(str(tx_id))) + '/handover-checks')
