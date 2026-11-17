"""Broker v0.25 contract regression tests: no external calls, no real credentials."""
import os
import sqlite3
import tempfile
import time
import uuid
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.fernet import Fernet

from core.oauth_broker import (BrokerStore,BrokerClient,BrokerError,BrokerReauth,
    _browser_identity, new_intent, resolve_broker, BROKER_SCOPE)
from core.marketplace_client import MarketplaceClient,MarketplaceError
from core.request_context import (set_request_context, set_broker_access_handler,
    set_broker_refresh_handler, delegated_token)

UID='38186cc8-934a-43ec-b8aa-e546a43d91df'
ORIGIN='https://projectagain.example'
KEY=Fernet.generate_key().decode()
CREDENTIAL='broker-opaque-credential-1234567890'
PROOF='private-proof-which-never-enters-browser'
TOKEN='oauth-access-opaque-111111111111111'


class FakeUser:
    is_logged_in=True
    def __init__(self,nonce='random-native-oidc-nonce-from-cookie-00001',sub=UID):
        self.claims={'sub':sub,'iss':ORIGIN,'nonce':nonce,'exp':int(time.time())-500}
    def to_dict(self):return self.claims


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=self.tmp.name+'/oauth.db'
        self.store=BrokerStore('sqlite-test-only',KEY,connection_factory=lambda:sqlite3.connect(self.db))
        self.binding,self.uid=_browser_identity(FakeUser(),ORIGIN,KEY)
        self.calls=[]
        self.responses=[]
        self.client=BrokerClient(ORIGIN,'projectagain-streamlit-broker','test-secret-12345678901234567890123456789',sender=self.sender)

    def tearDown(self):
        set_request_context(token='',visitor_id='')
        set_broker_refresh_handler(None)
        set_broker_access_handler(None)
        self.tmp.cleanup()

    def sender(self,path,payload,session):
        self.calls.append((path,payload,session))
        if self.responses:
            return self.responses.pop(0)
        if path=='intents':
            return 200, {'authorization_url':ORIGIN+'/api/v1/oauth/authorize?state=opaque'}
        if path=='tickets/exchange':
            return 200, {'broker_session':CREDENTIAL,'sub':UID,'scope':BROKER_SCOPE,
                         'expires_at':(datetime.now(timezone.utc)+timedelta(days=5)).isoformat()}
        if path=='access':
            return 200, {'access_token':TOKEN,'token_type':'Bearer','expires_in':900,
                         'sub':UID,'scope':BROKER_SCOPE,'refreshed':bool(payload.get('force_refresh'))}
        if path=='logout':
            return 200, {'ok':True}
        return 400, {'error':'invalid_request'}

    def link(self):
        url=new_intent(self.store,self.client,self.binding,self.uid)
        self.assertTrue(url.startswith(ORIGIN+'/api/v1/oauth/authorize'))
        # The state is not returned by the mock provider URL; inspect the DB
        # via a fixed test state to exercise exchange below.
        return url

    def session(self):
        self.store.pending_put('state-from-browser',self.binding,self.uid,PROOF)
        self.store.finish('state-from-browser',self.binding,self.uid,'ticket-once',self.client.exchange)
        return self.store.session(self.binding,self.uid)

    def test_browser_binding_uses_signed_nonce_not_user_uuid(self):
        same,_=_browser_identity(FakeUser(),ORIGIN,KEY)
        different,_=_browser_identity(FakeUser(nonce='other-native-oidc-nonce-0000002'),ORIGIN,KEY)
        self.assertEqual(self.binding,same)
        self.assertNotEqual(same,different)
        self.assertNotIn(UID,same)

    def test_unauthenticated_or_missing_nonce_fails_closed(self):
        with self.assertRaises(BrokerReauth):
            _browser_identity(SimpleNamespace(is_logged_in=False),ORIGIN,KEY)
        with self.assertRaises(BrokerReauth):
            _browser_identity(FakeUser(nonce=''),ORIGIN,KEY)

    def test_store_requires_postgres_when_no_test_factory(self):
        with self.assertRaises(BrokerError):
            BrokerStore('sqlite:///not-production',KEY)

    def test_start_intent_hash_only_sent_to_platform(self):
        self.link()
        name,data,session=self.calls[-1]
        self.assertEqual(name,'intents')
        self.assertEqual(len(data['session_binding_hash']),64)
        self.assertNotIn('session_proof',data)
        self.assertEqual(data['scope'],BROKER_SCOPE)

    def test_wrong_browser_cannot_exchange_ticket(self):
        self.store.pending_put('state-from-browser',self.binding,self.uid,PROOF)
        with self.assertRaises(BrokerReauth):
            self.store.finish('state-from-browser','f'*64,self.uid,'ticket',self.client.exchange)
        self.assertFalse(self.calls)

    def test_wrong_user_cannot_exchange_ticket(self):
        self.store.pending_put('state-from-browser',self.binding,self.uid,PROOF)
        with self.assertRaises(BrokerReauth):
            self.store.finish('state-from-browser',self.binding,str(uuid.uuid4()),'ticket',self.client.exchange)
        self.assertFalse(self.calls)

    def test_expired_pending_rejected(self):
        self.store.pending_put('state-from-browser',self.binding,self.uid,PROOF,ttl=-1)
        with self.assertRaises(BrokerReauth):
            self.store.finish('state-from-browser',self.binding,self.uid,'ticket',self.client.exchange)

    def test_replay_ticket_cannot_exchange_twice(self):
        self.session()
        count=len([x for x in self.calls if x[0]=='tickets/exchange'])
        with self.assertRaises(BrokerReauth):
            self.store.finish('state-from-browser',self.binding,self.uid,'ticket',self.client.exchange)
        self.assertEqual(count,len([x for x in self.calls if x[0]=='tickets/exchange']))

    def test_credentials_encrypted_at_rest(self):
        self.session()
        conn=sqlite3.connect(self.db)
        rows=conn.execute('SELECT broker_cipher,proof_cipher FROM agent_broker_sessions').fetchone()
        pending=conn.execute('SELECT proof_cipher FROM agent_broker_pending').fetchone()
        conn.close()
        self.assertNotIn(CREDENTIAL,str(rows))
        self.assertNotIn(PROOF,str(rows)+str(pending))
        self.assertEqual(self.store.session(self.binding,self.uid)['broker_session'],CREDENTIAL)

    def test_broker_token_not_refresh_exposed(self):
        record=self.session()
        access,scopes=self.client.access(record)
        self.assertEqual(access,TOKEN)
        self.assertIn('offer:read',scopes)
        self.assertNotIn('refresh_token',self.calls[-1][1])

    def test_one_forced_get_refresh_carries_observed_hash(self):
        record=self.session()
        self.client.access(record,force=True,observed_token=TOKEN)
        _,payload,_=self.calls[-1]
        self.assertEqual(len(payload['observed_access_token_hash']),64)
        self.assertNotIn(TOKEN,str(payload))
        self.assertTrue(payload['force_refresh'])

    def test_broker_503_fails_closed_without_reauth_or_replay(self):
        record=self.session()
        self.responses=[(503,{'error':'temporarily_unavailable'})]
        with self.assertRaises(BrokerError):
            self.client.access(record)
        self.assertIsNotNone(self.store.session(self.binding,self.uid))

    def test_explicit_reauth_clears_locally_after_error(self):
        record=self.session()
        self.responses=[(401,{'error':'reauth_required'})]
        with self.assertRaises(BrokerReauth):
            self.client.access(record)
        self.store.clear(self.binding)
        self.assertIsNone(self.store.session(self.binding,self.uid))

    def test_account_mismatch_rejected_before_profile_fetch(self):
        self.session()
        self.responses=[(200,{'access_token':TOKEN,'token_type':'Bearer','expires_in':700,
                              'sub':str(uuid.uuid4()),'scope':BROKER_SCOPE})]
        with self.assertRaises(BrokerError):
            resolve_broker(self.store,self.client,self.binding,self.uid,ORIGIN,
                           fetch=lambda *args:self.fail('must not fetch'))

    def test_verified_identity_stable_and_no_token_repr(self):
        self.session()
        def fetch(url,token):
            self.assertEqual(token,TOKEN)
            return ('ok',{'sub':UID}) if url.endswith('/userinfo') else ('ok',{'id':UID})
        state,_=resolve_broker(self.store,self.client,self.binding,self.uid,ORIGIN,fetch=fetch)
        self.assertTrue(state.connected)
        self.assertNotIn(TOKEN,repr(state))
        self.assertEqual(state.ai_identity,'platform:'+state.owner_key)

    def test_logout_removes_one_session(self):
        record=self.session()
        self.client.logout(record)
        self.store.clear(self.binding)
        self.assertIsNone(self.store.session(self.binding,self.uid))
        self.assertEqual(self.calls[-1][0],'logout')

    def test_get_401_once_broker_retry_no_post(self):
        client=MarketplaceClient(TOKEN,base_url=ORIGIN)
        attempts=[]
        def fake_req(method,url,**kw):
            attempts.append((method,kw['headers'].get('Authorization')))
            if len(attempts)==1:
                return SimpleNamespace(status_code=401,json=lambda:{'error':{'message':'expired'}},headers={})
            return SimpleNamespace(status_code=200,json=lambda:{'ok':True},headers={})
        set_broker_refresh_handler(lambda observed: 'new-broker-opaque-22222222222222222')
        with patch('core.marketplace_client.requests.request',fake_req):
            self.assertEqual(client.request('GET','/api/v1/offers'),{'ok':True})
        self.assertEqual(len(attempts),2)
        self.assertNotEqual(attempts[0][1],attempts[1][1])
        post_client=MarketplaceClient(TOKEN,base_url=ORIGIN)
        with patch('core.marketplace_client.requests.request',fake_req):
            with self.assertRaises(MarketplaceError):
                # POST is never automatically replayed; force response 401.
                with patch('core.marketplace_client.requests.request',
                           lambda *a,**k:SimpleNamespace(status_code=401,json=lambda:{},headers={})):
                    post_client.request('POST','/api/v1/agent-actions',payload={},key='idemp')
        self.assertEqual(len(attempts),2)

    def test_private_api_fail_closed_on_broker_unavailability(self):
        set_broker_access_handler(lambda: (_ for _ in ()).throw(BrokerError('503','temporary')))
        with patch('core.marketplace_client.requests.request',side_effect=AssertionError('must not call')):
            with self.assertRaises(MarketplaceError):
                MarketplaceClient(TOKEN,base_url=ORIGIN).me()

    def test_broker_config_not_legacy_token_fallback(self):
        from pathlib import Path
        app=(Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8')
        self.assertIn('broker_requested',app)
        self.assertIn('broker_connect_ui',app)
        self.assertIn('set_broker_access_handler',app)
        self.assertIn('store.finish(state,binding,uid,ticket,client.exchange)',app)


if __name__=='__main__':unittest.main()
