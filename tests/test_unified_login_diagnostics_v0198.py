"""v0.19.8: stage-specific, non-secret diagnostics when Cloud script logs are empty."""
from pathlib import Path
import asyncio
import unittest
from unittest.mock import patch
from starlette.requests import Request
from core.oauth_broker import BrokerError
from core.unified_web import (
    _start_sync, _StartStageFailure, _start_failure_response,
    login_start, login_route_health, process_callback,
)

ROOT = Path(__file__).resolve().parents[1]
def request(path='/pa-agent/auth/start', query=b''):
    return Request({'type': 'http', 'method':'GET', 'path':path,
        'headers':[(b'sec-fetch-site',b'same-origin')], 'query_string':query})

class StageDiagnosticTests(unittest.TestCase):
    def test_unexpected_config_error_becomes_fixed_code(self):
        with patch('core.unified_web._read_enabled',side_effect=RuntimeError('TOP SECRET')):
            with self.assertRaises(_StartStageFailure) as cm:
                _start_sync()
        self.assertEqual((cm.exception.stage,cm.exception.code),('CONFIG','unexpected'))

    def test_explicit_broker_error_is_redacted_stage_code(self):
        with patch('core.unified_web._read_enabled',return_value=True), \
             patch('core.unified_web._services',side_effect=BrokerError('unified_callback_not_ready', 'SECRET')):
            with self.assertRaises(_StartStageFailure) as cm:
                _start_sync()
        self.assertEqual((cm.exception.stage,cm.exception.code),('SERVICES','unified_callback_not_ready'))

    def test_unknown_error_code_never_echoes_remote_strings(self):
        with patch('core.unified_web._read_enabled',return_value=True), \
             patch('core.unified_web._services',side_effect=BrokerError('leak_private_token','SECRET')):
            with self.assertRaises(_StartStageFailure) as cm:
                _start_sync()
        self.assertEqual(cm.exception.code,'broker_failure')

    def test_stage_response_contains_no_exception_details(self):
        response=_start_failure_response('CONFIG','unexpected')
        self.assertEqual(response.status_code,500)
        self.assertIn(b'PA-START-CONFIG-unexpected',response.body)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')

    def test_health_route_exposed_in_both_entrypoints(self):
        for entry in ('app.py','unified_entry.py'):
            source=(ROOT/entry).read_text('utf-8')
            self.assertIn("Route('/pa-agent/auth/health', login_route_health, methods=['GET']),",source)

class AsyncStageDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_config_returns_safe_500_code(self):
        with patch('core.unified_web._start_sync',side_effect=_StartStageFailure('CONFIG','unexpected')):
            response=await login_start(request())
        self.assertEqual(response.status_code,500)
        self.assertIn(b'PA-START-CONFIG-unexpected',response.body)

    async def test_broker_error_returns_safe_503_code(self):
        with patch('core.unified_web._start_sync',side_effect=_StartStageFailure('CAPABILITIES','unified_callback_not_ready')):
            response=await login_start(request())
        self.assertEqual(response.status_code,503)
        self.assertIn(b'PA-START-CAPABILITIES-unified_callback_not_ready',response.body)

    async def test_unexpected_error_does_not_leak_secret_or_traceback(self):
        with patch('core.unified_web._start_sync',side_effect=RuntimeError('password=PRIVATE')):
            response=await login_start(request())
        self.assertEqual(response.status_code,500)
        self.assertIn(b'PA-START-OTHER-unexpected',response.body)
        self.assertNotIn(b'PRIVATE',response.body)
        self.assertNotIn(b'Traceback',response.body)

    async def test_health_returns_safe_constant(self):
        response=await login_route_health(request('/pa-agent/auth/health'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.body,b'PA-AUTH-ROUTE-OK')

    async def test_callback_unexpected_failure_removes_query_params(self):
        with patch('core.unified_web._callback_sync',side_effect=RuntimeError('private_ticket')):
            response=await process_callback(request('/pa-agent/auth/callback',b'pa_broker_ticket=private_ticket&pa_broker_state=x'))
        self.assertEqual(response.status_code,303)
        self.assertNotIn('private_ticket',response.headers['location'])
        self.assertIn('pa_login_notice=failed',response.headers['location'])

if __name__=='__main__':
    unittest.main()
