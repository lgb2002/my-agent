"""ProjectAgain API contract regression tests (offline, mocked network).

These are NOT proof of a real Replit deployment or of platform integration.
"""
import unittest
import os
import sys
import tempfile
from unittest.mock import patch

# Isolate local job records; network calls are patched.
_SANDBOX = tempfile.TemporaryDirectory(prefix='agent_v06_contract_')
if 'core.config' not in sys.modules:
    os.environ['AGENT_DATA_DIR'] = _SANDBOX.name
    os.environ['ENABLE_OPENAI_CHAT'] = 'false'

from core.marketplace_client import MarketplaceClient, MarketplaceError, origin_only
from core.request_context import set_request_context
from core.policy import recommendation, metadata_findings
from agent.tools import ToolDispatcher
from agent.chat import ChatAgent


class FakeResponse:
    def __init__(self, obj, status=200):
        self.obj, self.status_code = obj, status
    def json(self):
        return self.obj


class ProjectAgainContractTest(unittest.TestCase):
    def tearDown(self):
        set_request_context()

    def test_host_url_normalization_no_double_prefix(self):
        self.assertEqual(origin_only('https://projectagain.example/api/v1/'), 'https://projectagain.example')
        self.assertEqual(origin_only('https://projectagain.example'), 'https://projectagain.example')
        for bad in ('http://projectagain.example', 'https://projectagain.example/api/v1/api/v1',
                    'https://user:password@projectagain.example', 'https://projectagain.example?x=1'):
            with self.assertRaises(ValueError):
                origin_only(bad)

    @patch('core.marketplace_client.requests.request')
    def test_anonymous_public_search_does_not_send_global_token(self, remote):
        remote.return_value = FakeResponse({'items': [], 'next_cursor': None, 'total_estimate': 0})
        client = MarketplaceClient('', base_url='https://projectagain.example')
        result = client.listings(limit=15, cursor=0)
        self.assertEqual(result['items'], [])
        args, kwargs = remote.call_args
        self.assertEqual(args[1], 'https://projectagain.example/api/v1/listings')
        self.assertNotIn('Authorization', kwargs['headers'])
        self.assertEqual(kwargs['params']['include_demo'], 'false')
        self.assertEqual(kwargs['params']['cursor'], 0)

    @patch('core.marketplace_client.requests.request')
    def test_demo_filter_is_explicit_opt_in(self, remote):
        remote.return_value = FakeResponse({'items': [], 'next_cursor': '15'})
        set_request_context(include_demo=True)
        MarketplaceClient('', base_url='https://projectagain.example').listings(limit=15)
        self.assertEqual(remote.call_args.kwargs['params']['include_demo'], 'true')

    def test_personal_request_without_delegation_blocked_before_network(self):
        client = MarketplaceClient('', base_url='https://projectagain.example')
        with self.assertRaises(MarketplaceError) as c:
            client.buyer_preferences()
        self.assertEqual(c.exception.status, 401)
        with self.assertRaises(MarketplaceError):
            client.offers('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')

    @patch('core.marketplace_client.requests.request')
    def test_opaque_bearer_token_is_not_jwt_and_not_logged(self, remote):
        remote.return_value = FakeResponse({'id': 'user-1', 'scopes': ['buyer_profile:read']})
        token = 'opaque-secret-grant-1234567890'
        client = MarketplaceClient(token, base_url='https://projectagain.example/api/v1')
        out = client.me()
        self.assertEqual(out['id'], 'user-1')
        self.assertEqual(remote.call_args.kwargs['headers']['Authorization'], 'Bearer ' + token)
        self.assertNotIn(token, repr(out))

    @patch('core.marketplace_client.requests.request')
    def test_detail_uuid_remains_stable_and_demo_flag_forwarded(self, remote):
        uid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        remote.return_value = FakeResponse({'id':uid,'title':'old'})
        set_request_context(include_demo=True)
        out = MarketplaceClient('', base_url='https://projectagain.example').listing(uid)
        self.assertEqual(out['id'], uid)
        self.assertEqual(remote.call_args.args[1], 'https://projectagain.example/api/v1/listings/' + uid)
        self.assertEqual(remote.call_args.kwargs['params']['include_demo'], 'true')

    def test_live_write_is_disabled_before_transport(self):
        import core.marketplace_client as mc
        import services.marketplace as svc
        with patch.object(mc, 'MARKETPLACE_BASE_URL', 'https://projectagain.example'):
            readonly = svc.LiveReadOnlyClient()
            with self.assertRaises(MarketplaceError) as c:
                readonly.request('POST', '/api/v1/agent-actions', {'action_type':'SUBMIT_OFFER'}, key='once')
            self.assertEqual(c.exception.code, 'WRITE_DISABLED')

    def test_listing_choice_uses_pinned_uuid_not_fresh_list(self):
        uid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        other = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        ctx = {'recent_listings': [{'id':uid,'title':'선택한 프로젝트'}]}
        dispatcher = ToolDispatcher('구매자 B', ctx)
        calls = []
        def fake(method, path, *args, **kwargs):
            calls.append(path)
            if path.endswith(uid):
                return {'id':uid,'title':'선택한 프로젝트'}
            return {'items':[{'id':other, 'title':'신규 등록 매물'}]}
        dispatcher.request = fake
        chosen = dispatcher._listing('1번 매물')
        self.assertEqual(chosen['id'], uid)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith(uid))
        with self.assertRaises(ValueError):
            ToolDispatcher('구매자 B', {})._listing('1번')

    def test_page_cursor_keeps_identity_and_next_page(self):
        uid = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        ctx = {}
        dispatcher = ToolDispatcher('구매자 B', ctx)
        calls = []
        def fake(method, path, *args, **kwargs):
            calls.append(path)
            return {'items':[{'id':uid,'title':'첫 프로젝트','price_krw':100000,
                              'tech_stack':None, 'known_defects':None}], 'next_cursor':'15','total_estimate':25}
        dispatcher.request = fake
        event, _ = dispatcher.invoke('search_listings', {'query':'Python'})
        self.assertTrue(event.success, event.summary)
        self.assertEqual(ctx['recent_listings'][0]['id'], uid)
        self.assertEqual(ctx['listing_next_cursor'], '15')
        name, args = __import__('agent.chat', fromlist=['offline_intent']).offline_intent('다음 매물 보여줘',ctx)
        self.assertEqual(name, 'search_listings')
        self.assertEqual(args['cursor'], 15)

    def test_optional_listing_fields_are_safe(self):
        item = {'id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','status':'ACTIVE','is_demo':False,
                'price_krw':500000,'title':'매물','category':None,
                'tech_stack':None,'known_defects':None,'sale_rights_type':None,
                'lifecycle_status':None}
        prefs = {'max_budget_krw':1000000, 'min_budget_krw':0,
                 'max_monthly_cost_krw':30000,'skill_level':'BASIC',
                 'risk_tolerance':'MEDIUM','objectives':[], 'preferred_tech_stack':['Python']}
        result = recommendation([item], prefs)
        self.assertEqual(result['count'], 1)
        self.assertEqual(metadata_findings(item)['verdict'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
