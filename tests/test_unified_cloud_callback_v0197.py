"""v0.19.7 Cloud unified callback: direct ASGI path, strict broker handshake."""
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from starlette.requests import Request
from core.unified_login import UNIFIED_CALLBACK_URL, CLOUD_ASGI_BASE_URL, UnifiedClient
from core.unified_web import process_callback
from core.oauth_broker import BrokerError

ROOT = Path(__file__).resolve().parents[1]

class CallbackRouteContractTests(unittest.TestCase):
    def test_exact_direct_callback_route_declared_in_both_entrypoints(self):
        self.assertEqual(UNIFIED_CALLBACK_URL, CLOUD_ASGI_BASE_URL + 'pa-agent/auth/callback')
        parsed = urlparse(UNIFIED_CALLBACK_URL)
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.hostname, 'projectagain.streamlit.app')
        self.assertNotIn('?', UNIFIED_CALLBACK_URL)
        for entry in ('app.py','unified_entry.py'):
            s = (ROOT / entry).read_text('utf-8')
            self.assertIn("Route('/pa-agent/auth/callback', process_callback, methods=['GET']),", s)
        self.assertNotEqual(UNIFIED_CALLBACK_URL, 'https://projectagain.streamlit.app/')

    def test_capabilities_fail_closed_without_explicit_exact_return_uri(self):
        client = UnifiedClient('https://projectagain.kr', 'broker', 'dummy-secret-that-is-at-least-thirty-two-characters')
        base = {'unified_login_enabled':True,'flow':'BROKER_CONSENT_AND_SIGNED_IDENTITY'}
        for mismatch in (None, 'https://projectagain.streamlit.app/',
                         'https://evil.test/~/+/pa-agent/auth/callback',
                         UNIFIED_CALLBACK_URL + '?a=b'):
            payload = dict(base)
            if mismatch is not None: payload['unified_return_uri'] = mismatch
            mock_response = type('Response',(),{'status_code':200,'json':lambda self: payload})()
            with patch('core.unified_login.requests.get',return_value=mock_response):
                with self.assertRaises(BrokerError) as cm:
                    client.capabilities()
            self.assertEqual(cm.exception.code,'unified_callback_not_ready')
        response = type('Response',(),{'status_code':200,
                    'json':lambda self:dict(base,unified_return_uri=UNIFIED_CALLBACK_URL)})()
        with patch('core.unified_login.requests.get',return_value=response):
            self.assertTrue(client.capabilities())

class CallbackRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_with_browser_cookie_clears_ticket_after_exchange(self):
        scope={'type':'http','method':'GET','path':'/pa-agent/auth/callback',
               'headers':[(b'cookie',b'pa_agent_session=example-test-cookie')],
               'query_string':b'pa_broker_ticket=private_ticket&pa_broker_state=random_state'}
        with patch('core.unified_web._callback_sync',return_value='') as fn:
            response = await process_callback(Request(scope))
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'https://projectagain.streamlit.app/')
        self.assertEqual(response.headers.get('referrer-policy'),'no-referrer')
        self.assertEqual(response.headers.get('cache-control'),'no-store')
        self.assertNotIn('private_ticket',str(response.headers))
        self.assertEqual(fn.call_args.args,('example-test-cookie','private_ticket','random_state',None))

    async def test_no_cookie_cannot_create_login(self):
        scope={'type':'http','method':'GET','path':'/pa-agent/auth/callback',
               'headers':[], 'query_string':b'pa_broker_ticket=ticket&pa_broker_state=state'}
        with patch('core.unified_web._callback_sync',return_value='failed') as fn:
            response=await process_callback(Request(scope))
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'https://projectagain.streamlit.app/?pa_login_notice=failed')
        self.assertEqual(fn.call_args.args[0],'')

    async def test_duplicate_query_parameters_never_call_exchange(self):
        scope={'type':'http','method':'GET','path':'/pa-agent/auth/callback',
               'headers':[], 'query_string':b'pa_broker_ticket=a&pa_broker_ticket=b&pa_broker_state=c'}
        with patch('core.unified_web._callback_sync') as fn:
            response=await process_callback(Request(scope))
        self.assertEqual(response.status_code,303)
        self.assertIn('pa_login_notice=failed',response.headers['location'])
        fn.assert_not_called()
