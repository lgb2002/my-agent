"""v0.37 signed identity, cookie isolation, replay, consent and no-secret tests."""
import base64
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
import tempfile
import time
from datetime import datetime, timezone, timedelta
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

from core.oauth_broker import BrokerReauth, BrokerError, BROKER_SCOPE
from core.unified_login import (UnifiedStore, UnifiedClient, cookie_binding,
                                verify_signed_identity, token_hash, _validate_auth_url)


def b64u(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def signed_token(private, claims, kid='test-kid'):
    a=b64u(json.dumps({'alg':'RS256','kid':kid,'typ':'JWT'}).encode())
    b=b64u(json.dumps(claims).encode())
    content=(a+'.'+b).encode('ascii')
    c=b64u(private.sign(content,padding.PKCS1v15(),hashes.SHA256()))
    return a+'.'+b+'.'+c


class FakeBroker:
    def __init__(self, user=None, scope=BROKER_SCOPE):
        self.user=user or str(uuid.uuid4())
        self.scope=scope
        self.calls=0

    def exchange(self,ticket,state,proof):
        self.calls+=1
        return {'broker_session':'b'*64,'sub':self.user,'scope':self.scope,
                'expires_at':(datetime.now(timezone.utc)+timedelta(days=25)).isoformat(),
                'id_token':'dummy-signed-jwt','identity_token_type':'JWT'}

    def begin(self,state,proof,scope):
        self.last_state=state
        return 'https://projectagain.kr/api/v1/oauth/authorize?response_type=code&state='+state


class UnifiedLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path=str(Path(self.tmp.name)/'auth.sqlite')
        @contextmanager
        def connect():
            conn=sqlite3.connect(path)
            try:
                yield conn
            finally:
                conn.close()
        self.db=connect
        self.store=UnifiedStore('',Fernet.generate_key().decode(),connection_factory=self.db)
        self.cookie=secrets.token_urlsafe(48)
        self.state=secrets.token_urlsafe(32)
        self.proof=secrets.token_urlsafe(48)
        self.nonce=secrets.token_urlsafe(48)
        self.user=str(uuid.uuid4())
        self.broker=FakeBroker(self.user)

    def _start(self):
        self.store.start(self.cookie,self.state,self.proof,self.nonce)

    def _finish(self,cookie=None,state=None):
        return self.store.finish(cookie or self.cookie,state or self.state,'ticket'*10,self.broker,
                     validate_identity=lambda token,client,nonce,proof,state,uid: uid)

    def test_cookie_binding_never_exposes_cookie(self):
        self.assertEqual(len(cookie_binding(self.cookie)),64)
        self.assertNotEqual(cookie_binding(self.cookie),self.cookie)
        self.assertEqual(cookie_binding('test'), '')

    def test_valid_broker_exchange_persists_user(self):
        self._start(); self.assertEqual(self._finish(),self.user)
        self.assertEqual(self.store.lookup_identity(cookie_binding(self.cookie)),self.user)
        record=self.store.session(cookie_binding(self.cookie),self.user)
        self.assertEqual(record['sub'],self.user)
        self.assertEqual(set(record['scope'].split()),set(BROKER_SCOPE.split()))
        self.assertNotIn(self.proof,str(record['broker_session']))

    def test_other_browser_cannot_exchange_ticket(self):
        self._start()
        with self.assertRaises(BrokerReauth):
            self._finish(cookie=secrets.token_urlsafe(48))
        self.assertEqual(self.broker.calls,0)

    def test_wrong_state_cannot_exchange_ticket(self):
        self._start()
        with self.assertRaises(BrokerReauth):
            self._finish(state=secrets.token_urlsafe(32))
        self.assertEqual(self.broker.calls,0)

    def test_replay_rejected(self):
        self._start();self._finish()
        with self.assertRaises(BrokerReauth):
            self._finish()
        self.assertEqual(self.broker.calls,1)

    def test_no_identity_token_denied(self):
        self._start()
        self.broker.exchange=lambda a,b,c: {'sub':self.user,'scope':BROKER_SCOPE,'broker_session':'b'*50}
        with self.assertRaises(BrokerReauth):
            self._finish()
        self.assertIsNone(self.store.lookup_identity(cookie_binding(self.cookie)))

    def test_initial_draft_scope_disallowed(self):
        self._start();self.broker.scope=BROKER_SCOPE+' offer:draft'
        with self.assertRaises(BrokerReauth):
            self._finish()

    def test_incremental_draft_requires_old_session(self):
        with self.assertRaises(BrokerReauth):
            self.store.begin_incremental(self.cookie,self.broker)
        self._start();self._finish()
        next_url=self.store.begin_incremental(self.cookie,self.broker)
        self.assertIn('/oauth/authorize?',next_url)
        with self.db() as conn:
            row=conn.execute('SELECT state_hash,proof_cipher FROM agent_unified_login_pending').fetchone()
        # Explicit consent request is saved but its secret proof remains sealed.
        self.assertTrue(row)
        self.assertNotIn(self.proof,row[1])

    def test_incremental_consent_stores_new_scope_without_initial_jwt(self):
        self._start();self._finish()
        self.broker.scope=BROKER_SCOPE+' offer:draft'
        self.store.begin_incremental(self.cookie,self.broker)
        self.broker.exchange=lambda ticket,state,proof: {
            'broker_session':'c'*64,'sub':self.user,'scope':self.broker.scope,
            'expires_at':(datetime.now(timezone.utc)+timedelta(days=25)).isoformat()}
        # v0.25 incremental exchange carries no signed identity token. It is
        # allowed ONLY with an already browser-bound signed identity session.
        self.store.finish(self.cookie,self.broker.last_state,'ticket'*10,self.broker)
        record=self.store.session(cookie_binding(self.cookie),self.user)
        self.assertIn('offer:draft',record['scope'].split())

    def test_clear_session(self):
        self._start();self._finish()
        self.store.clear(cookie_binding(self.cookie))
        self.assertIsNone(self.store.lookup_identity(cookie_binding(self.cookie)))

    def test_strict_authorize_domain(self):
        ok='https://projectagain.kr/api/v1/oauth/authorize?response_type=code'
        self.assertEqual(_validate_auth_url(ok,'https://projectagain.kr'),ok)
        for bad in ('https://evil.test/api/v1/oauth/authorize?x=y',
                    'http://projectagain.kr/api/v1/oauth/authorize?x=y',
                    'https://projectagain.kr@evil.test/api/v1/oauth/authorize?x=y',
                    'https://projectagain.kr/api/v1/oauth/authorize'):
            with self.assertRaises(BrokerError):
                _validate_auth_url(bad,'https://projectagain.kr')

    def test_signed_identity_claims_and_signature(self):
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pub=private.public_key().public_numbers()
        jwks={'keys':[{'kid':'test-kid','kty':'RSA','use':'sig','alg':'RS256',
                       'n':b64u(pub.n.to_bytes((pub.n.bit_length()+7)//8,'big')),
                       'e':b64u(pub.e.to_bytes((pub.e.bit_length()+7)//8,'big'))}]}
        now=int(time.time())
        claims={'iss':'https://projectagain.kr','aud':'projectagain-streamlit-broker',
                'iat':now,'exp':now+300,'auth_time':now-20,'token_use':'broker_unified_identity',
                'nonce':self.nonce,'session_binding_hash':token_hash(self.proof),
                'client_state_hash':token_hash(self.state),'sub':self.user}
        token=signed_token(private,claims)
        kwargs=dict(issuer=claims['iss'],audience=claims['aud'],nonce=self.nonce,
                    proof=self.proof,state=self.state,expected_sub=self.user,jwks=jwks,now=now)
        self.assertEqual(verify_signed_identity(token,**kwargs),self.user)
        for change in ({'aud':'bad'},{'nonce':'bad'},{'exp':now-360},{'sub':str(uuid.uuid4())},
                       {'token_use':'access'},{'auth_time':now+100}):
            changed=claims.copy();changed.update(change)
            with self.assertRaises(BrokerReauth):
                verify_signed_identity(signed_token(private,changed),**kwargs)
        # Tampering with signed payload without recomputing signature is rejected.
        a,b,c=token.split('.')
        changed=claims.copy();changed['sub']=str(uuid.uuid4())
        tampered=a+'.'+b64u(json.dumps(changed).encode())+'.'+c
        with self.assertRaises(BrokerReauth):
            verify_signed_identity(tampered,**kwargs)
        # Cryptographic algorithm confusion is rejected even if JWT looks valid.
        new_header=b64u(json.dumps({'alg':'none','kid':'test-kid'}).encode())
        with self.assertRaises(BrokerReauth):
            verify_signed_identity(new_header+'.'+b+'.'+c,**kwargs)

    def test_no_token_leak_in_database(self):
        self._start();self._finish()
        with self.db() as conn:
            row=conn.execute('SELECT broker_cipher,proof_cipher FROM agent_unified_login_sessions').fetchone()
        self.assertNotIn(self.proof,' '.join(row))
        self.assertNotIn('b'*64,' '.join(row))


if __name__=='__main__':
    unittest.main()

class UnifiedWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_sets_only_secure_httponly_cookie(self):
        from unittest.mock import patch
        from starlette.requests import Request
        from core.unified_web import login_start
        sid=secrets.token_urlsafe(48)
        scope={'type':'http','method':'GET','path':'/pa-agent/auth/start',
               'headers':[(b'sec-fetch-site',b'same-origin')], 'query_string':b''}
        request=Request(scope)
        with patch('core.unified_web._start_sync',return_value=(
                'https://projectagain.kr/api/v1/oauth/authorize?state=s',sid)):
            result=await login_start(request)
        cookie=result.headers['set-cookie']
        self.assertIn('HttpOnly',cookie)
        self.assertIn('Secure',cookie)
        self.assertIn('SameSite=lax',cookie)
        self.assertNotIn('session_proof',cookie)
        self.assertEqual(result.status_code,303)

    async def test_external_site_cannot_force_logout(self):
        from starlette.requests import Request
        from core.unified_web import login_logout
        scope={'type':'http','method':'GET','path':'/pa-agent/auth/logout',
               'headers':[(b'sec-fetch-site',b'cross-site')],'query_string':b''}
        response=await login_logout(Request(scope))
        self.assertEqual(response.status_code,403)

    async def test_callback_without_cookie_fails_closed(self):
        from starlette.requests import Request
        from core.unified_web import process_callback
        scope={'type':'http','method':'GET','path':'/',
               'headers':[],'query_string':b'pa_broker_ticket=some-ticket&pa_broker_state=abc'}
        with patch('core.unified_web._read_enabled',return_value=True):
            response=await process_callback(Request(scope))
        self.assertEqual(response.status_code,303)
        self.assertIn('pa_login_notice=failed',response.headers['location'])
        self.assertNotIn('some-ticket',response.headers['location'])

    async def test_disabled_middleware_preserves_legacy_callback(self):
        from core.unified_web import BrokerReturnMiddleware
        observed=[]
        async def app(scope,receive,send):
            observed.append(scope['path'])
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'legacy'})
        m=BrokerReturnMiddleware(app)
        scope={'type':'http','method':'GET','path':'/', 'headers':[],
               'query_string':b'pa_broker_ticket=existing&pa_broker_state=old'}
        async def receive():return {'type':'http.request','body':b''}
        messages=[]
        async def send(message):messages.append(message)
        with patch('core.unified_web._read_enabled',return_value=False):
            await m(scope,receive,send)
        self.assertEqual(observed,['/'])
        self.assertEqual(messages[0]['status'],200)


if __name__=='__main__':
    unittest.main()
