"""Production API-only regression. All transport calls are offline fakes."""
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class ApiOnlyTests(unittest.TestCase):
    def test_no_runtime_sandbox_service_or_catalogue(self):
        self.assertFalse((ROOT/'services'/'demo_marketplace.py').exists())
        self.assertFalse((ROOT/'fixtures'/'demo_contract.json').exists())
        self.assertFalse((ROOT/'data'/'mock_marketplace.sqlite3').exists())
        from services.marketplace import client_for_actor, LiveReadOnlyClient
        with patch.object(LiveReadOnlyClient, '__init__', return_value=None):
            self.assertIsInstance(client_for_actor('anything'), LiveReadOnlyClient)

    def test_legacy_agent_mode_value_is_ignored(self):
        from core import config
        from services.marketplace import client_for_actor, LiveReadOnlyClient
        with patch.dict(os.environ, {'AGENT_MODE':'mock'}):
            with patch.object(LiveReadOnlyClient,'__init__',return_value=None):
                self.assertIsInstance(client_for_actor('구매자 B'), LiveReadOnlyClient)
            self.assertFalse(config.writes_enabled())
            self.assertFalse(hasattr(config,'AGENT_MODE'))

    def test_runtime_writes_never_allowed_even_if_legacy_config_set(self):
        from agent.core import AgentRuntime, AgentError
        import core.config as config
        with patch('core.marketplace_client.MARKETPLACE_BASE_URL','https://api.example.test'), patch.object(config,'MARKETPLACE_BASE_URL','https://api.example.test'):
            runtime=AgentRuntime('ProjectAgain 사용자')
            with self.assertRaises(AgentError) as caught:
                runtime.request('POST','/api/agent/v1/negotiations/draft',{'listing_id':'x'},write=True,key='foo')
            self.assertEqual(caught.exception.status,404)

    def test_api_client_cannot_post_via_generic_request(self):
        from services.marketplace import LiveReadOnlyClient
        from core.marketplace_client import MarketplaceError
        with patch('core.marketplace_client.MarketplaceClient.__init__',return_value=None):
            client=LiveReadOnlyClient()
        with self.assertRaises(MarketplaceError):
            client.request('POST','/api/v1/listings',payload={})

    def test_demo_check_is_platform_filter_not_local_mode(self):
        from core.request_context import set_request_context
        from core.marketplace_client import MarketplaceClient
        try:
            set_request_context(include_demo=True)
            with patch.object(MarketplaceClient,'request',return_value={'items':[], 'next_cursor':None}) as req:
                MarketplaceClient(base_url='https://api.example.test').listings()
                self.assertEqual(req.call_args.kwargs['params']['include_demo'],'true')
        finally:
            set_request_context()

    def test_four_mock_only_tools_not_advertised(self):
        from agent.tools import TOOL_LABELS, TOOL_DEFINITIONS
        old={'prepare_counter_offer','prepare_accept_offer','prepare_publish_report','prepare_handover_check'}
        self.assertFalse(old & set(TOOL_LABELS))
        self.assertEqual(len(TOOL_LABELS),9)
        self.assertEqual(set(TOOL_LABELS),{x['function']['name'] for x in TOOL_DEFINITIONS})

    def test_local_zip_scan_never_needs_demo_seller_or_remote_upload(self):
        from agent.core import AgentRuntime, AgentError
        import core.config as config
        import io, zipfile, uuid
        lid=str(uuid.uuid4())
        class Client:
            def listing(self, value): return {'id':lid,'seller_id':'seller-1','status':'ACTIVE','title':'Own project'}
        with patch('core.marketplace_client.MARKETPLACE_BASE_URL','https://api.example.test'), patch.object(config,'MARKETPLACE_BASE_URL','https://api.example.test'):
            runtime=AgentRuntime('ProjectAgain 사용자')
            with patch('agent.core.delegated_token',return_value='test-opaque-token'), patch.object(runtime,'authenticated',return_value=(Client(),{'id':'seller-1','role':'SELLER'})):
                raw=io.BytesIO()
                with zipfile.ZipFile(raw,'w') as z: z.writestr('README.md','hello')
                outcome=runtime.request('POST','/api/agent/v1/inspections/zip?listing_id='+lid,
                        body=raw.getvalue(),write=True,key='scan-'+uuid.uuid4().hex)
                self.assertTrue(outcome['job_id'])
                job=runtime.request('GET','/api/agent/v1/jobs/'+outcome['job_id'])
                self.assertEqual(job['status'],'PARTIAL')
                self.assertEqual(job['result']['dynamic_execution'],'NOT_TESTED')

    def test_anonymous_cannot_submit_seller_zip_scan(self):
        from agent.core import AgentRuntime, AgentError
        import core.config as config
        class Client:
            def listing(self, _):
                raise AssertionError('anonymous visitor must be rejected before listing access')
        with patch.object(config,'MARKETPLACE_BASE_URL','https://api.example.test'), patch('agent.core.delegated_token',return_value=None):
            runtime=AgentRuntime('public')
            with self.assertRaises(AgentError) as caught:
                runtime.inspect_upload(Client(),{'id':'visitor:fake','role':'PUBLIC'},'listing-id',b'not-a-zip','test-key')
            self.assertEqual(caught.exception.status,401)

    def test_real_platform_demo_flag_is_kept_in_inspection(self):
        from core.policy import metadata_findings
        listing={'id':'abc','title':'Test listing','is_demo':True,'status':'ACTIVE',
                 'price_krw':100000, 'tech_stack':['Python']}
        self.assertTrue(metadata_findings(listing)['is_demo'])

    def test_ui_keeps_remote_demo_filter_and_no_role_selection(self):
        source=(ROOT/'chat_ui.py').read_text(encoding='utf-8')
        self.assertIn('시연 매물 포함',source)
        self.assertNotIn('체험할 역할',source)
        self.assertNotIn('perform_confirmed_action',source)
        self.assertIn('submit_confirmed_draft',source)
        ast.parse(source)

if __name__=='__main__':unittest.main()
