"""v0.19.6 Cloud navigation regression: top-level ASGI route, unchanged auth."""
import ast
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from starlette.requests import Request
from core.unified_login import (
    PUBLIC_APP_URL, CLOUD_ASGI_BASE_URL, UNIFIED_START_URL, UNIFIED_LOGOUT_URL,
)
from core.unified_web import login_start, login_logout, _redirect_to_home

ROOT = Path(__file__).resolve().parents[1]


class CloudNavigationTests(unittest.TestCase):
    def test_cloud_links_bypass_outer_wrapper_but_reach_original_asgi_paths(self):
        self.assertEqual(PUBLIC_APP_URL, 'https://projectagain.streamlit.app/')
        self.assertEqual(CLOUD_ASGI_BASE_URL, PUBLIC_APP_URL + '~/+/')
        self.assertEqual(UNIFIED_START_URL, PUBLIC_APP_URL + '~/+/pa-agent/auth/start')
        self.assertEqual(UNIFIED_LOGOUT_URL, PUBLIC_APP_URL + '~/+/pa-agent/auth/logout')
        for url, backend_path in ((UNIFIED_START_URL, '/pa-agent/auth/start'),
                                  (UNIFIED_LOGOUT_URL, '/pa-agent/auth/logout')):
            parsed = urlparse(url)
            self.assertEqual(parsed.scheme, 'https')
            self.assertEqual(parsed.hostname, 'projectagain.streamlit.app')
            self.assertEqual(parsed.path.removeprefix('/~/+'), backend_path)
            self.assertNotIn('?', url)
            self.assertNotIn('#', url)

    def test_all_unified_auth_ui_links_use_shared_direct_routes(self):
        text = (ROOT / 'chat_ui.py').read_text('utf-8')
        self.assertIn('start_link = UNIFIED_START_URL', text)
        self.assertGreaterEqual(text.count('UNIFIED_LOGOUT_URL'), 5)
        self.assertNotIn('https://projectagain.streamlit.app/pa-agent/auth/start', text)
        self.assertNotIn('https://projectagain.streamlit.app/pa-agent/auth/logout', text)
        self.assertIn('st.login()', text)  # safe fallback unchanged
        self.assertIn('st.link_button(\'ProjectAgain으로 시작하기\'', text)

    def test_existing_asgi_routes_and_callback_unchanged(self):
        entry = (ROOT / 'app.py').read_text('utf-8')
        web = (ROOT / 'core/unified_web.py').read_text('utf-8')
        ast.parse(entry)
        ast.parse(web)
        self.assertIn("Route('/pa-agent/auth/start', login_start", entry)
        self.assertIn("Route('/pa-agent/auth/logout', login_logout", entry)
        self.assertEqual(_redirect_to_home().headers['location'], PUBLIC_APP_URL)
        self.assertIn('redirect = UNIFIED_START_URL', web)
        self.assertIn("redirect = 'https://projectagain.kr/auth/logout'", web)
        self.assertNotIn('st.login()', web)  # Unified flow never uses OIDC st.login

    def test_no_auth_secrets_or_identity_tokens_in_navigation_link(self):
        all_links = (UNIFIED_START_URL, UNIFIED_LOGOUT_URL, UNIFIED_LOGOUT_URL + '?next=switch')
        for url in all_links:
            for forbidden in ('client_state=', 'pa_broker_ticket=', 'id_token=',
                              'session_proof=', 'broker_session=', 'access_token='):
                self.assertNotIn(forbidden, url)


class CloudLoginRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_route_retains_303_and_secure_cookie(self):
        raw_cookie = secrets.token_urlsafe(48)
        scope = {'type':'http','method':'GET','path':'/pa-agent/auth/start',
                 'headers':[(b'sec-fetch-site',b'none')], 'query_string':b''}
        target = 'https://projectagain.kr/api/v1/oauth/authorize?response_type=code&state=unit-test'
        with patch('core.unified_web._start_sync', return_value=(target, raw_cookie)):
            reply = await login_start(Request(scope))
        self.assertEqual(reply.status_code, 303)
        self.assertEqual(reply.headers['location'], target)
        cookie = reply.headers['set-cookie']
        self.assertIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=lax', cookie)
        self.assertNotIn('session_proof', cookie)

    async def test_switch_account_route_still_revokes_before_navigation(self):
        scope = {'type':'http','method':'GET','path':'/pa-agent/auth/logout',
                 'headers':[(b'sec-fetch-site',b'none')],
                 'query_string':b'next=switch'}
        with patch('core.unified_web._logout_sync', return_value=True):
            reply = await login_logout(Request(scope))
        self.assertEqual(reply.status_code, 303)
        self.assertEqual(reply.headers['location'], 'https://projectagain.kr/auth/logout')
        self.assertIn('pa_agent_session=', reply.headers['set-cookie'])

    async def test_log_out_then_restart_goes_to_direct_start_route(self):
        scope = {'type':'http','method':'GET','path':'/pa-agent/auth/logout',
                 'headers':[(b'sec-fetch-site',b'none')], 'query_string':b'next=start'}
        with patch('core.unified_web._logout_sync', return_value=True):
            reply = await login_logout(Request(scope))
        self.assertEqual(reply.status_code,303)
        self.assertEqual(reply.headers['location'],UNIFIED_START_URL)


if __name__ == '__main__':
    unittest.main()
