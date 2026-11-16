"""No external network, no secrets logged. Validate live integration contracts."""
import unittest
from unittest.mock import patch
from core.runtime_secrets import configure_from_secrets, ai_activation_reason
from core.live_diagnostics import check_public_listings, check_delegation, run_diagnostics
from core.marketplace_client import MarketplaceClient
from core.request_context import set_request_context


class Reply:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def json(self):
        return self.payload


class LiveDiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        set_request_context()

    def test_secrets_load_top_level_settings_and_not_shared_grant(self):
        env = {}
        keys = configure_from_secrets({'OPENAI_API_KEY': 'secret-openai',
                                       'ENABLE_OPENAI_CHAT': 'true',
                                       'MARKETPLACE_API_URL': 'https://service.example',
                                       'MARKETPLACE_API_KEY': 'shared-should-not-be-used'}, env)
        self.assertTrue(keys['OPENAI_API_KEY'])
        self.assertEqual(env['ENABLE_OPENAI_CHAT'], 'true')
        self.assertNotIn('MARKETPLACE_API_KEY', env)

    def test_existing_env_precedence(self):
        env = {'ENABLE_OPENAI_CHAT': 'false'}
        configure_from_secrets({'ENABLE_OPENAI_CHAT':'true'}, env)
        self.assertEqual(env['ENABLE_OPENAI_CHAT'], 'false')

    def test_openai_flag_reason(self):
        self.assertIn('false', ai_activation_reason(True, False))
        self.assertIn('설정되지', ai_activation_reason(False, False))

    @patch('core.marketplace_client.requests.request')
    def test_diagnostic_two_filters_and_anonymous_auth(self, remote):
        remote.side_effect = [Reply({'items': [], 'next_cursor': None, 'total_estimate': 0}),
                              Reply({'items': [{'id': 'abc'}], 'next_cursor': None, 'total_estimate': 1})]
        output = run_diagnostics('https://service.example', token='', include_demo=True)
        self.assertEqual(output['public']['count'], 0)
        self.assertEqual(output['with_demo']['count'], 1)
        self.assertEqual(output['delegation']['code'], 'NO_USER_TOKEN')
        self.assertIn('시연 매물', output['interpretation'])
        reqs = remote.call_args_list
        self.assertEqual([r.kwargs['params']['include_demo'] for r in reqs], ['false', 'true'])
        self.assertTrue(all('Authorization' not in r.kwargs['headers'] for r in reqs))

    @patch('core.marketplace_client.requests.request')
    def test_explicit_filter_beats_active_context(self, remote):
        set_request_context(include_demo=True)
        remote.return_value = Reply({'items': [], 'next_cursor': None})
        check_public_listings('https://service.example', False)
        self.assertEqual(remote.call_args.kwargs['params']['include_demo'], 'false')

    @patch('core.marketplace_client.requests.request')
    def test_authenticated_me_and_no_token_in_report(self, remote):
        raw_token = 'secret-opaque-token-value'
        remote.return_value = Reply({'id': 'user-private-id', 'scopes': ['listing:read']})
        result = check_delegation('https://service.example', raw_token)
        self.assertEqual(result['http_status'], 200)
        self.assertEqual(result['scope_count'], 1)
        self.assertNotIn(raw_token, repr(result))
        self.assertNotIn('user-private-id', repr(result))
        self.assertEqual(remote.call_args.args[1], 'https://service.example/api/v1/auth/me')
        self.assertEqual(remote.call_args.kwargs['headers']['Authorization'], 'Bearer ' + raw_token)

    @patch('core.marketplace_client.requests.request')
    def test_expired_grant_is_not_mistaken_for_public_failure(self, remote):
        remote.return_value = Reply({'error': {'code': 'TOKEN_EXPIRED', 'message': 'expired'}}, 401)
        result = check_delegation('https://service.example', 'expired-opaque')
        self.assertFalse(result['ok'])
        self.assertEqual(result['http_status'], 401)
        self.assertIn('인증', result['detail'])

    @patch('core.marketplace_client.requests.request')
    def test_non_json_contract_and_http_errors_not_silenced(self, remote):
        remote.return_value = Reply({'listings': []})
        result = check_public_listings('https://service.example', True)
        self.assertEqual(result['code'], 'CONTRACT_MISMATCH')
        self.assertIsNone(result['count'])
        self.assertFalse(result['ok'])

    @patch('core.marketplace_client.requests.request')
    def test_remote_500_does_not_turn_into_zero(self, remote):
        remote.return_value = Reply({'error': {'code': 'SERVER', 'message': 'internal'}}, 500)
        result = check_public_listings('https://service.example', True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['http_status'], 500)
        self.assertIsNone(result['count'])

    @patch('core.marketplace_client.requests.request')
    def test_standard_listing_parser(self, remote):
        remote.return_value = Reply({'items': [{'id': 'one'}, {'id':'two'}],
                                     'next_cursor': '15', 'total_estimate': 3})
        result = check_public_listings('https://service.example', True)
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['has_next_page'])
        self.assertEqual(result['total_estimate'], 3)


if __name__ == '__main__':
    unittest.main()
