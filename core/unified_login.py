"""ProjectAgain v0.37 unified-login verifier and browser-bound persistent store.

Only a secure same-origin ASGI route may issue the HttpOnly browser cookie.
Never treat query parameters, Streamlit session_state, or an unverified JWT as identity.
Legacy OIDC / Broker continues to work when this integration is disabled.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from core.oauth_broker import BrokerClient, BrokerError, BrokerReauth, BROKER_SCOPE, _scopes, _iso_expiry
from core.oidc_session import _trusted_origin

COOKIE_NAME = 'pa_agent_session'
COOKIE_MAX_AGE = 30 * 86400
CLIENT_STATE_PATTERN = re.compile(r'^[A-Za-z0-9_~.\-]{16,256}$')
COOKIE_PATTERN = re.compile(r'^[A-Za-z0-9_-]{40,128}$')
DEFAULT_ISSUER = 'https://projectagain.kr'
DEFAULT_AUDIENCE = 'projectagain-streamlit-broker'


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def cookie_binding(raw: str) -> str:
    if not isinstance(raw, str) or not COOKIE_PATTERN.fullmatch(raw):
        return ''
    return token_hash(raw)


def _validate_auth_url(url: str, origin: str) -> str:
    parsed = urlsplit(url or '')
    trusted = _trusted_origin(origin)
    if not trusted or parsed.scheme != 'https' or f'https://{parsed.netloc}' != trusted or parsed.path != '/api/v1/oauth/authorize' or parsed.username or parsed.password or parsed.fragment:
        raise BrokerError('invalid_redirect', '플랫폼 로그인 주소가 올바르지 않아요.')
    if not parsed.query or len(url) > 4096:
        raise BrokerError('invalid_redirect', '플랫폼 로그인 요청이 올바르지 않아요.')
    return url


class UnifiedClient(BrokerClient):
    """Server-to-server Basic auth for the v0.37 extension; never from JS."""

    def capabilities(self):
        try:
            response = requests.get(
                self.origin + '/api/v1/oauth/broker/unified/capabilities',
                auth=(self.client_id, self.client_secret), timeout=(3, 9),
                allow_redirects=False, headers={'Accept': 'application/json'},
            )
            if response.status_code != 200:
                raise BrokerError('unified_unavailable', '통합 로그인을 아직 사용할 수 없어요.')
            data = response.json()
            if not isinstance(data, dict) or data.get('unified_login_enabled') is not True or data.get('flow') != 'BROKER_CONSENT_AND_SIGNED_IDENTITY':
                raise BrokerError('unified_unavailable', '통합 로그인 설정이 아직 준비되지 않았어요.')
            return True
        except (requests.RequestException, ValueError):
            raise BrokerError('unified_unavailable', '플랫폼 인증 서버를 확인하지 못했어요.') from None

    def begin_unified(self, state, proof, nonce):
        if not CLIENT_STATE_PATTERN.fullmatch(state or '') or len(nonce or '') < 32:
            raise BrokerError('invalid_state', '로그인 요청 값이 올바르지 않아요.')
        payload = {
            'client_state': state,
            'session_binding_hash': token_hash(proof),
            'login_nonce': nonce,
            'scope': BROKER_SCOPE,
        }
        url_data = self._unified_post(payload)
        if url_data.get('flow') != 'unified_login':
            raise BrokerError('invalid_response', '플랫폼 로그인 응답을 확인하지 못했어요.')
        return _validate_auth_url(url_data.get('authorization_url'), self.origin)

    def _unified_post(self, payload):
        try:
            r = requests.post(
                self.origin + '/api/v1/oauth/broker/unified/intents',
                json=payload, auth=(self.client_id, self.client_secret),
                headers={'Accept': 'application/json'}, timeout=(3, 9),
                allow_redirects=False,
            )
            if r.status_code != 200:
                raise BrokerError('unified_denied', '로그인 요청을 시작하지 못했어요.')
            result = r.json()
            if not isinstance(result, dict):
                raise BrokerError('invalid_response', '플랫폼 로그인 응답이 올바르지 않아요.')
            return result
        except (requests.RequestException, ValueError, TypeError):
            raise BrokerError('unified_unavailable', '플랫폼 로그인 서버에 연결하지 못했어요.') from None


def _b64u(text):
    import base64
    if not isinstance(text,str) or not re.fullmatch(r'[A-Za-z0-9_-]+', text):
        raise ValueError('invalid base64url')
    return base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_',validate=True)


def verify_signed_identity(token: str, *, issuer: str, audience: str, nonce: str,
                           proof: str, state: str, expected_sub: str,
                           jwks: dict, now: float | None = None) -> str:
    """Verify RS256 JWS with the trusted issuer JWKS; enforce all v0.37 claims."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    try:
        if not isinstance(token,str) or len(token)>12000 or token.count('.')!=2:
            raise ValueError
        a,b,c=token.split('.')
        header=json.loads(_b64u(a))
        if not isinstance(header,dict) or header.get('alg')!='RS256' or header.get('crit'):
            raise ValueError
        kid=header.get('kid')
        if not isinstance(kid,str) or not (1<=len(kid)<=128):
            raise ValueError
        keys=jwks.get('keys') if isinstance(jwks,dict) else None
        if not isinstance(keys,list):
            raise ValueError
        matches=[key for key in keys if isinstance(key,dict) and key.get('kid')==kid
                 and key.get('kty')=='RSA' and key.get('use','sig')=='sig'
                 and key.get('alg','RS256')=='RS256']
        if len(matches)!=1:
            raise ValueError
        k=matches[0]
        n,e=int.from_bytes(_b64u(k['n']),'big'),int.from_bytes(_b64u(k['e']),'big')
        if not 2048<=n.bit_length()<=8192 or not 3<=e<=65537 or e%2==0:
            raise ValueError
        pub=rsa.RSAPublicNumbers(e,n).public_key()
        pub.verify(_b64u(c),(a+'.'+b).encode('ascii'),padding.PKCS1v15(),hashes.SHA256())
        claims=json.loads(_b64u(b))
        if not isinstance(claims,dict):
            raise ValueError
        now_ts=time.time() if now is None else now
        exp,issued=claims.get('exp'),claims.get('iat')
        if type(exp) not in (float,int) or type(issued) not in (float,int):
            raise ValueError
        if issued>now_ts+30 or exp<=now_ts-30 or exp-issued>330 or issued<now_ts-360:
            raise ValueError
        if claims.get('iss')!=issuer or claims.get('aud')!=audience:
            raise ValueError
        if claims.get('token_use')!='broker_unified_identity':
            raise ValueError
        auth_time = claims.get('auth_time')
        if type(auth_time) not in (int,float) or auth_time < 0 or auth_time > issued + 30:
            raise ValueError
        if not isinstance(claims.get('nonce'),str) or not secrets.compare_digest(claims['nonce'],nonce):
            raise ValueError
        if not isinstance(claims.get('session_binding_hash'),str) or not secrets.compare_digest(claims['session_binding_hash'],token_hash(proof)):
            raise ValueError
        if not isinstance(claims.get('client_state_hash'),str) or not secrets.compare_digest(claims['client_state_hash'],token_hash(state)):
            raise ValueError
        sub=str(uuid.UUID(str(claims.get('sub') or '')))
        if sub!=str(uuid.UUID(str(expected_sub or ''))):
            raise ValueError
        return sub
    except Exception:
        # Never render JWT contents, JWKS values, or original exception text.
        raise BrokerReauth('invalid_identity','계정 인증을 검증하지 못했어요. 다시 시작해 주세요.') from None


class UnifiedStore:
    """Server-only pending state and session; PostgreSQL required in production.

    connection_factory is for isolated SQLite tests only. The schema is additive.
    """
    DDL = (
        '''CREATE TABLE IF NOT EXISTS agent_unified_login_pending (
            state_hash TEXT PRIMARY KEY, cookie_hash TEXT NOT NULL,
            proof_cipher TEXT NOT NULL, nonce_cipher TEXT NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
        )''',
        '''CREATE TABLE IF NOT EXISTS agent_unified_login_sessions (
            cookie_hash TEXT PRIMARY KEY, sub TEXT NOT NULL, scope TEXT NOT NULL,
            broker_cipher TEXT NOT NULL, proof_cipher TEXT NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL
        )''',
    )

    def __init__(self, database_url, encryption_key, connection_factory=None):
        if connection_factory is None and not str(database_url or '').startswith(('postgresql://', 'postgres://')):
            raise BrokerError('database_required', '서버 로그인 저장소 설정을 확인해 주세요.')
        self.database_url = database_url
        try:
            self.fernet = Fernet(encryption_key.encode('ascii'))
        except (TypeError, ValueError, AttributeError):
            raise BrokerError('invalid_encryption_key', '로그인 저장소 암호화 키가 올바르지 않아요.') from None
        self.connection_factory = connection_factory

    def _db(self):
        if self.connection_factory:
            return self.connection_factory()
        from core.pg_pool import connection
        return connection(self.database_url)

    def _sql(self, statement):
        return statement.replace('%s','?') if self.connection_factory else statement

    def _execute(self, conn, statement, args=()):
        return conn.execute(self._sql(statement), args)

    def _init(self, conn):
        for statement in self.DDL:
            conn.execute(statement)

    def _seal(self, val):
        return self.fernet.encrypt(val.encode('utf-8')).decode('ascii')

    def _unseal(self, val):
        try:
            return self.fernet.decrypt(val.encode('ascii')).decode('utf-8')
        except (InvalidToken, ValueError, TypeError, AttributeError):
            raise BrokerReauth('invalid_storage', '저장된 로그인 정보를 확인할 수 없어요.') from None

    def start(self, raw_cookie: str, state: str, proof: str, nonce: str, ttl=300):
        binding = cookie_binding(raw_cookie)
        if not binding or not CLIENT_STATE_PATTERN.fullmatch(state or '') or len(proof) < 40 or len(nonce) < 32:
            raise BrokerError('invalid_request', '로그인 요청 값이 올바르지 않아요.')
        try:
            with self._db() as conn:
                self._init(conn)
                self._execute(conn, 'INSERT INTO agent_unified_login_pending '
                              '(state_hash,cookie_hash,proof_cipher,nonce_cipher,expires_at,consumed) '
                              'VALUES (%s,%s,%s,%s,%s,0)',
                              (token_hash(state),binding,self._seal(proof),self._seal(nonce),time.time()+ttl))
                self._execute(conn,'DELETE FROM agent_unified_login_pending WHERE expires_at < %s',(time.time()-300,))
                conn.commit()
        except BrokerError:
            raise
        except Exception:
            raise BrokerError('storage_unavailable', '로그인 저장소에 연결할 수 없어요.') from None

    def begin_incremental(self, raw_cookie: str, client: BrokerClient):
        """Explicit, optional offer:draft consent using legacy v0.25 Broker intents."""
        binding = cookie_binding(raw_cookie)
        if not binding or not self.lookup_identity(binding):
            raise BrokerReauth('reauth_required','먼저 ProjectAgain에 로그인해 주세요.')
        state=secrets.token_urlsafe(32)
        proof=secrets.token_urlsafe(48)
        # A server-only flow marker in the encrypted nonce column. v0.37 id_token
        # is ONLY required for the initial unified identity proof.
        self.start(raw_cookie,state,proof,'incremental:'+secrets.token_urlsafe(40))
        try:
            return client.begin(state,proof,BROKER_SCOPE+' offer:draft')
        except BrokerError:
            self.abandon(state)
            raise

    def abandon(self, state: str):
        try:
            with self._db() as conn:
                self._init(conn)
                self._execute(conn,'DELETE FROM agent_unified_login_pending WHERE state_hash=%s',(token_hash(state),))
                conn.commit()
        except Exception:
            pass

    def finish(self, raw_cookie: str, state: str, ticket: str, client: UnifiedClient,
               *, validate_identity=None):
        binding = cookie_binding(raw_cookie)
        if not binding or not CLIENT_STATE_PATTERN.fullmatch(state or '') or not isinstance(ticket,str) or not (10 <= len(ticket) <= 4096):
            raise BrokerReauth('invalid_state', '로그인 정보가 올바르지 않아요.')
        try:
            with self._db() as conn:
                self._init(conn)
                query = '''SELECT cookie_hash,proof_cipher,nonce_cipher,expires_at,consumed
                           FROM agent_unified_login_pending WHERE state_hash=%s'''
                if not self.connection_factory:
                    query += ' FOR UPDATE'
                row = self._execute(conn,query,(token_hash(state),)).fetchone()
                if not row or row[0]!=binding or row[3]<time.time() or row[4]:
                    raise BrokerReauth('invalid_state', '다른 브라우저의 로그인 요청이거나 만료된 요청이에요.')
                proof, nonce = self._unseal(row[1]),self._unseal(row[2])
                # Exchange is once-only; any failure aborts the transaction.
                result = client.exchange(ticket,state,proof)
                uid = str(uuid.UUID(str(result.get('sub') or '')))
                scope = ' '.join(_scopes(result.get('scope')))
                if nonce.startswith('incremental:'):
                    previous=self._execute(conn,'''SELECT sub,scope,expires_at FROM
                        agent_unified_login_sessions WHERE cookie_hash=%s''',(binding,)).fetchone()
                    if (not previous or previous[0]!=uid or previous[2]<=time.time()
                            or not set(previous[1].split()).issubset(set(scope.split()))
                            or 'offer:draft' not in scope.split()):
                        raise BrokerReauth('invalid_scope','추가 권한을 확인하지 못했어요.')
                else:
                    token = result.get('id_token')
                    if result.get('identity_token_type') != 'JWT':
                        raise BrokerReauth('invalid_identity', '로그인 신원 증명이 없어요.')
                    validator = validate_identity or verify_platform_identity
                    verified_sub = validator(token, client, nonce, proof, state, uid)
                    if verified_sub != uid:
                        raise BrokerReauth('invalid_identity', '로그인 계정을 확인하지 못했어요.')
                    if 'offer:draft' in scope.split():
                        raise BrokerReauth('invalid_scope', '최초 로그인 권한이 예상 범위를 벗어났어요.')
                cred = result.get('broker_session')
                if not isinstance(cred,str) or len(cred)<20:
                    raise BrokerReauth('invalid_session','플랫폼 세션이 올바르지 않아요.')
                expires = _iso_expiry(result.get('expires_at'))
                self._execute(conn,'''INSERT INTO agent_unified_login_sessions
                      (cookie_hash,sub,scope,broker_cipher,proof_cipher,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(cookie_hash) DO UPDATE SET
                      sub=excluded.sub,scope=excluded.scope,broker_cipher=excluded.broker_cipher,
                      proof_cipher=excluded.proof_cipher,expires_at=excluded.expires_at''',
                              (binding,uid,scope,self._seal(cred),self._seal(proof),expires))
                self._execute(conn, 'DELETE FROM agent_unified_login_pending WHERE state_hash=%s',(token_hash(state),))
                conn.commit()
                return uid
        except BrokerError:
            raise
        except Exception:
            raise BrokerReauth('unified_failed','로그인 연결을 완료하지 못했어요. 다시 시작해 주세요.') from None

    def lookup_identity(self, binding):
        try:
            with self._db() as conn:
                self._init(conn)
                row = self._execute(conn,'SELECT sub,expires_at FROM agent_unified_login_sessions WHERE cookie_hash=%s',(binding,)).fetchone()
                return row[0] if row and row[1] > time.time() else None
        except Exception:
            raise BrokerError('storage_unavailable','로그인 저장소를 확인하지 못했어요.') from None

    def session(self, binding, uid):
        if not binding or not uid:
            return None
        try:
            with self._db() as conn:
                self._init(conn)
                row = self._execute(conn,'''SELECT sub,scope,broker_cipher,proof_cipher,expires_at
                      FROM agent_unified_login_sessions WHERE cookie_hash=%s''',(binding,)).fetchone()
            if not row or row[0] != uid or row[4] <= time.time():
                return None
            return {'sub':uid,'scope':row[1],'broker_session':self._unseal(row[2]),
                    'session_proof':self._unseal(row[3])}
        except BrokerError:
            raise
        except Exception:
            raise BrokerError('storage_unavailable','로그인 저장소에 접근할 수 없어요.') from None

    def clear(self, binding):
        if not binding:
            return
        try:
            with self._db() as conn:
                self._init(conn)
                self._execute(conn,'DELETE FROM agent_unified_login_sessions WHERE cookie_hash=%s',(binding,))
                self._execute(conn,'DELETE FROM agent_unified_login_pending WHERE cookie_hash=%s',(binding,))
                conn.commit()
        except Exception:
            raise BrokerError('storage_unavailable','로그인 연결 정보를 종료하지 못했어요.') from None


def verify_platform_identity(token, client, nonce, proof, state, expected_sub):
    try:
        response = requests.get(client.origin + '/api/v1/oauth/jwks', timeout=(3, 7),
                                allow_redirects=False, headers={'Accept': 'application/json'})
        if response.status_code != 200:
            raise ValueError
        keys = response.json()
    except (requests.RequestException, ValueError):
        raise BrokerReauth('jwks_unavailable','플랫폼 서명키를 확인하지 못했어요.') from None
    return verify_signed_identity(token, issuer=client.origin, audience=client.client_id,
                                  nonce=nonce, proof=proof, state=state,expected_sub=expected_sub,jwks=keys)
