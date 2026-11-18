"""No-server security regression: native Streamlit ID + API token binding."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import time
import unittest
from unittest.mock import patch

from core.oidc_session import resolve_login, revoke_access

ROOT = Path(__file__).resolve().parents[1]
SUB = '38186cc8-934a-43ec-b8aa-e546a43d91df'
ORIGIN = 'https://projectagain.example'
TOKEN = 'secret-opaque-short-access'


class FakeTokens:
    access = TOKEN

    def get(self, name):
        return TOKEN if name == 'access' else None


class FakeUser:
    is_logged_in = True
    tokens = FakeTokens()

    def __init__(self, **override):
        self.claims = {'sub': SUB, 'iss': ORIGIN, 'exp': int(time.time()) + 200}
        self.claims.update(override)

    def to_dict(self):
        return self.claims


def remote_calls():
    seen = []
    def fetch(url, token):
        seen.append((url, token))
        if url.endswith('/api/v1/oauth/userinfo'):
            return 'ok', {'sub': SUB}
        if url.endswith('/api/v1/auth/me'):
            return 'ok', {'id': SUB, 'scopes': ['openid', 'listing:read', 'offer:read']}
        raise AssertionError(url)
    return fetch, seen


class OIDCSecurityTest(unittest.TestCase):
    def test_signed_sub_verified_against_two_platform_endpoints(self):
        fetch, calls = remote_calls()
        state = resolve_login(FakeUser(), ORIGIN, fetch=fetch, expected_issuer=ORIGIN)
        self.assertTrue(state.connected)
        self.assertEqual(state.user_id, SUB)
        self.assertEqual(state.access_token, TOKEN)
        self.assertNotIn(TOKEN, repr(state))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(token == TOKEN for _, token in calls))
        self.assertTrue(state.has_scope('offer:read'))
        self.assertFalse(state.has_scope('offer:draft'))
        self.assertEqual(state.ai_identity, 'platform:' + state.owner_key)

    def test_guest_cannot_be_metered_or_access_private_api(self):
        guest = SimpleNamespace(is_logged_in=False)
        state = resolve_login(guest, ORIGIN, fetch=lambda *_: self.fail('should not call API'))
        self.assertFalse(state.connected)
        self.assertEqual(state.ai_identity,'')
        self.assertEqual(state.access_token,'')

    def test_login_issuer_mismatch_denied_without_request(self):
        state = resolve_login(FakeUser(iss='https://different.example'), ORIGIN,
                              fetch=lambda *_: self.fail('untrusted identity must not call platform'))
        self.assertEqual(state.status,'invalid')

    def test_mismatched_configured_discovery_issuer_fails_closed(self):
        self.assertEqual(resolve_login(FakeUser(), ORIGIN, expected_issuer='https://other.example').status,'invalid')

    def test_wrong_subject_blocked(self):
        fetch, seen = remote_calls()
        state = resolve_login(FakeUser(sub='00000000-0000-0000-0000-000000000001'), ORIGIN, fetch=fetch)
        self.assertEqual(state.status,'invalid')
        self.assertEqual(len(seen),1)

    def test_userinfo_and_me_mismatch_blocked(self):
        for mismatch in ('userinfo','me'):
            with self.subTest(mismatch=mismatch):
                def f(url, token):
                    if url.endswith('userinfo'):
                        return 'ok', {'sub': SUB if mismatch == 'me' else '00000000-0000-0000-0000-000000000001'}
                    return 'ok', {'id': SUB if mismatch == 'userinfo' else '00000000-0000-0000-0000-000000000001'}
                state=resolve_login(FakeUser(),ORIGIN,fetch=f)
                self.assertFalse(state.connected)
                self.assertEqual(state.access_token,'')

    def test_expiry_blocks_before_api_requests(self):
        state=resolve_login(FakeUser(exp=100),ORIGIN,fetch=lambda *_: self.fail('expired'))
        self.assertEqual(state.status,'expired')

    def test_token_401_blocks_ai_and_private_calls(self):
        state=resolve_login(FakeUser(),ORIGIN,fetch=lambda *_: ('expired',None))
        self.assertEqual(state.status,'expired')
        self.assertFalse(state.connected)
        self.assertFalse(state.ai_identity)

    def test_without_exposed_access_fails_closed(self):
        u=FakeUser()
        u.tokens=SimpleNamespace()
        state=resolve_login(u,ORIGIN,fetch=lambda *_: self.fail('missing token'))
        self.assertEqual(state.status,'expired')

    def test_transport_failure_is_not_guest_or_success(self):
        state=resolve_login(FakeUser(),ORIGIN,fetch=lambda *_: ('unavailable',None))
        self.assertEqual(state.status,'unavailable')

    def test_stable_owner_across_short_lived_access_tokens(self):
        fetch, _=remote_calls()
        first=resolve_login(FakeUser(),ORIGIN,fetch=fetch)
        second=resolve_login(FakeUser(),ORIGIN,fetch=fetch)
        self.assertEqual(first.owner_key, second.owner_key)
        self.assertEqual(first.owner_key,hashlib.sha256((ORIGIN+'::'+SUB).encode()).hexdigest())

    def test_revocation_post_not_redirect_or_query(self):
        sent=[]
        ok=revoke_access(TOKEN,ORIGIN,'client','clientsecret',
                         send=lambda *args:(sent.append(args) or True))
        self.assertTrue(ok)
        self.assertEqual(sent[0][0],ORIGIN+'/api/v1/oauth/revoke')
        self.assertEqual(sent[0][1],TOKEN)

    def test_ui_hides_manual_grant_and_binds_identity(self):
        app=(ROOT/'chat_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('st.text_input(\n            "위임 토큰"', app)
        self.assertIn('ProjectAgain 계정으로 로그인',app)
        self.assertIn('resolve_login(st.user',app)
        self.assertIn('set_request_context(token=token',app)
        self.assertIn('set_ai_identity(ai_identity)',app)
        self.assertIn('revoke_access(token',app)
        self.assertIn('owner_scope = login.owner_key[:12] if connected',app)
        self.assertNotIn('ai_identity = \'oidc:\' +',app)

    def test_client_never_auto_approves_transactions(self):
        content=(ROOT/'services'/'marketplace.py').read_text(encoding='utf-8')
        self.assertIn("if method.upper() != 'GET'",content)
        self.assertIn('if not ENABLE_LIVE_DRAFTS:',content)


if __name__ == '__main__':
    unittest.main()
