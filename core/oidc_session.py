"""Strict ProjectAgain OIDC → API principal binding for Streamlit native login.

The Streamlit framework validates OIDC authentication. We additionally check its
short-lived access token against ProjectAgain UserInfo and /auth/me before any
private API request or metered AI call. Tokens are never persisted/logged.

Streamlit st.login currently does NOT expose refresh tokens; do not fake renewal.
"""
from dataclasses import dataclass, field
import hashlib
import time
import uuid
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class LoginState:
    status: str
    user_id: str = ''
    access_token: str = field(default='', repr=False)
    owner_key: str = ''
    ai_identity: str = ''
    scopes: tuple = ()
    message: str = ''

    @property
    def connected(self):
        return self.status == 'connected'

    def has_scope(self, scope):
        return self.connected and scope in self.scopes


def _user_claims(user):
    try:
        if not bool(user.is_logged_in):
            return None
        data = user.to_dict()
        return data if isinstance(data, dict) else None
    except (AttributeError, TypeError, ValueError):
        return None


def _access_token(user):
    try:
        tokens = user.tokens
        token = tokens.get('access') if hasattr(tokens, 'get') else None
        if not token:
            token = getattr(tokens, 'access', '')
        return token.strip() if isinstance(token, str) else ''
    except (AttributeError, TypeError, KeyError):
        return ''


def _trusted_origin(value):
    parsed = urlsplit((value or '').strip())
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ''
    if parsed.path.rstrip('/') not in ('', '/api/v1'):
        return ''
    return 'https://' + parsed.netloc


def _fetch_identity(url, token):
    try:
        response = requests.get(url, headers={'Authorization': 'Bearer ' + token,
                                               'Accept': 'application/json'},
                                timeout=(3, 7), allow_redirects=False)
        if response.status_code == 401:
            return 'expired', None
        if response.status_code != 200:
            return 'unavailable', None
        body = response.json()
        return ('ok', body) if isinstance(body, dict) else ('unavailable', None)
    except (requests.RequestException, ValueError, TypeError):
        return 'unavailable', None


def resolve_login(user, platform_url, *, fetch=None, now=None, expected_issuer=None):
    """Fail closed unless signed OIDC sub matches BOTH API-authenticated identities.

    The optional fetch hook is strictly for deterministic unit testing; the app
    uses _fetch_identity. Never pass user-supplied endpoints to this function.
    """
    claims = _user_claims(user)
    if claims is None:
        return LoginState('guest')
    base = _trusted_origin(platform_url)
    configured = _trusted_origin(expected_issuer or platform_url)
    if not base or base != configured:
        return LoginState('invalid', message='ProjectAgain 인증 제공자 주소와 API 주소를 확인해 주세요.')
    subject = str(claims.get('sub') or '')
    issuer = str(claims.get('iss') or '').rstrip('/')
    try:
        uid = str(uuid.UUID(subject))
    except (TypeError, ValueError, AttributeError):
        return LoginState('invalid', message='ProjectAgain 계정 식별자를 확인할 수 없습니다.')
    if not issuer or issuer != configured:
        return LoginState('invalid', message='로그인 제공자 정보가 플랫폼 설정과 일치하지 않습니다.')
    raw_exp = claims.get('exp')
    try:
        if raw_exp is not None and float(raw_exp) <= (time.time() if now is None else now):
            return LoginState('expired', message='로그인 확인 시간이 지났습니다. 다시 로그인해 주세요.')
    except (TypeError, ValueError):
        return LoginState('invalid', message='로그인 유효기간을 확인할 수 없습니다.')
    token = _access_token(user)
    if not token:
        return LoginState('expired', message='API 연결 정보가 없습니다. 다시 로그인해 주세요.')
    fetcher = fetch or _fetch_identity
    status, info = fetcher(base + '/api/v1/oauth/userinfo', token)
    if status == 'expired':
        return LoginState('expired', message='API 사용 시간이 만료됐습니다. 다시 로그인해 주세요.')
    if status != 'ok' or not isinstance(info, dict):
        return LoginState('unavailable', message='플랫폼 로그인 확인에 실패했어요. 잠시 뒤 다시 확인해 주세요.')
    if info.get('sub') != uid:
        return LoginState('invalid', message='로그인 계정 정보가 일치하지 않습니다.')
    status, me = fetcher(base + '/api/v1/auth/me', token)
    if status == 'expired':
        return LoginState('expired', message='API 사용 시간이 만료됐습니다. 다시 로그인해 주세요.')
    if status != 'ok' or not isinstance(me, dict):
        return LoginState('unavailable', message='플랫폼 계정 권한을 확인하지 못했어요.')
    if me.get('id') != uid:
        return LoginState('invalid', message='API 계정과 로그인 계정이 일치하지 않습니다.')
    scopes = me.get('scopes')
    scopes = tuple(sorted(set(scopes))) if isinstance(scopes, list) and all(isinstance(s, str) for s in scopes) else ()
    owner = hashlib.sha256((platform_url.rstrip('/') + '::' + uid).encode('utf-8')).hexdigest()
    # Backward-compatible with the owner hash used by saved workflows.
    # Normalized origin avoids double /api/v1 in the hash in new deployments.
    return LoginState('connected', user_id=uid, access_token=token,
                      owner_key=owner, ai_identity='platform:' + owner, scopes=scopes)


def revoke_access(access_token, issuer, client_id, client_secret, *, send=None):
    """Best-effort revocation before logout; never leak tokens in URLs or errors."""
    base = _trusted_origin(issuer)
    if not base or not access_token or not client_id or not client_secret:
        return False
    try:
        if send is None:
            response = requests.post(base + '/api/v1/oauth/revoke',
                                     auth=(client_id, client_secret),
                                     data={'token': access_token}, timeout=(3, 7),
                                     allow_redirects=False)
            return response.status_code == 200
        return bool(send(base + '/api/v1/oauth/revoke', access_token, client_id, client_secret))
    except (requests.RequestException, TypeError, ValueError):
        return False
