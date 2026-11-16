"""Offline end-to-end tests: no Streamlit runtime, HTTP server, or paid model."""
import io
import os
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

# Isolate user data; tests are never allowed to mutate production/demo data.
TEST_DATA = tempfile.TemporaryDirectory(prefix='micro_agent_single_test_')
os.environ['AGENT_DATA_DIR'] = TEST_DATA.name
os.environ['AGENT_MODE'] = 'mock'
os.environ['ENABLE_OPENAI_CHAT'] = 'false'
from agent.core import AgentRuntime, AgentError
from core import db
from services import demo_marketplace as demo
from core.policy import recommendation
from core.config import FIXTURE_PATH

LISTING = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def key():
    return uuid.uuid4().hex


def defaults():
    return {'max_budget_krw': 1000000, 'min_budget_krw': 0,
            'max_monthly_cost_krw': 30000, 'skill_level': 'BASIC',
            'risk_tolerance': 'MEDIUM', 'objectives': ['학습'],
            'preferred_tech_stack': ['Python']}


def zip_bytes(entries):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return mem.getvalue()


class SingleProcessAgentTest(unittest.TestCase):
    def setUp(self):
        # Reset local DBs to avoid test-order coupling.
        for name in ('agent_jobs.sqlite3', 'mock_marketplace.sqlite3'):
            p = Path(TEST_DATA.name) / name
            if p.exists():
                p.unlink()
        demo.init_db()
        self.buyer = AgentRuntime('구매자 B')
        self.seller = AgentRuntime('판매자 A')

    def get(self, app, path):
        return app.request('GET', path)

    def post(self, app, path, payload=None, *, k=None, body=None):
        return app.request('POST', path, payload, body, True, k or key())

    def test_no_localhost_http_server_needed(self):
        h = self.get(self.buyer, '/health')
        self.assertIn('서버 불필요', h['marketplace'])
        self.assertEqual(h['agent_mode'], 'mock')

    def test_demo_listings(self):
        items = self.get(self.buyer, '/api/agent/v1/listings')['items']
        self.assertEqual(len(items), 3)
        self.assertTrue(all(i['is_demo'] for i in items))

    def test_recommendation_filters_budget(self):
        prefs = defaults()
        prefs['max_budget_krw'] = 100000
        job = self.post(self.buyer, '/api/agent/v1/jobs', {'task_type':'RECOMMEND','preferences':prefs})
        result = self.get(self.buyer, '/api/agent/v1/jobs/'+job['job_id'])
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertTrue(all(x['price_krw'] <= 100000 for x in result['result']['ranked']))
        self.assertGreater(len(result['result']['excluded']), 0)

    def test_live_policy_can_rank_real_listings(self):
        import json
        fixtures = json.loads(FIXTURE_PATH.read_text('utf8'))
        item = dict(fixtures['listings'][1], is_demo=False)
        result = recommendation([item], defaults(), demo_only=False)
        self.assertEqual(result['count'], 1)
        self.assertFalse(result['is_demo'])

    def test_job_idempotency(self):
        payload={'task_type':'RECOMMEND','preferences':defaults()}
        k = key()
        x=self.post(self.buyer,'/api/agent/v1/jobs',payload,k=k)
        y=self.post(self.buyer,'/api/agent/v1/jobs',payload,k=k)
        self.assertEqual(x['job_id'],y['job_id'])
        self.assertFalse(y['created'])

    def test_job_key_conflict(self):
        k=key()
        self.post(self.buyer,'/api/agent/v1/jobs',{'task_type':'RECOMMEND','preferences':defaults()},k=k)
        with self.assertRaises(AgentError) as c:
            self.post(self.buyer,'/api/agent/v1/jobs',{'task_type':'INSPECT_METADATA','listing_id':LISTING},k=k)
        self.assertEqual(c.exception.status,409)

    def test_job_owner_isolation(self):
        j=self.post(self.buyer,'/api/agent/v1/jobs',{'task_type':'RECOMMEND','preferences':defaults()})
        with self.assertRaises(AgentError) as c:
            self.get(self.seller,'/api/agent/v1/jobs/'+j['job_id'])
        self.assertEqual(c.exception.status,404)

    def test_metadata_not_pass(self):
        j=self.post(self.buyer,'/api/agent/v1/jobs',{'task_type':'INSPECT_METADATA','listing_id':LISTING})
        result=self.get(self.buyer,'/api/agent/v1/jobs/'+j['job_id'])
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['result']['verdict'],'UNVERIFIED')

    def test_buyer_cannot_upload_seller_code(self):
        raw=zip_bytes({'readme.md':'example'})
        with self.assertRaises(AgentError) as c:
            self.post(self.buyer,'/api/agent/v1/inspections/zip?listing_id='+LISTING,body=raw)
        self.assertEqual(c.exception.status,403)

    def test_seller_zip_and_report_review(self):
        raw=(Path(__file__).resolve().parent.parent/'fixtures'/'demo_incomplete_app.zip').read_bytes()
        j=self.post(self.seller,'/api/agent/v1/inspections/zip?listing_id='+LISTING,body=raw)
        result=self.get(self.seller,'/api/agent/v1/jobs/'+j['job_id'])
        self.assertEqual(result['status'],'PARTIAL')
        self.assertNotEqual(result['result']['dynamic_execution'],'PASS')
        report=self.post(self.seller, '/api/agent/v1/jobs/'+j['job_id']+'/publish')
        self.assertEqual(report['review_status'],'PENDING_REVIEW')
        self.assertTrue(report['is_demo'])

    def test_zip_slip_block(self):
        raw=zip_bytes({'../bad.py': 'print("no")'})
        j=self.post(self.seller,'/api/agent/v1/inspections/zip?listing_id='+LISTING,body=raw)
        result=self.get(self.seller,'/api/agent/v1/jobs/'+j['job_id'])
        self.assertEqual(result['status'],'FAILED')

    def _draft(self):
        return self.post(self.buyer,'/api/agent/v1/negotiations/draft',
            {'listing_id':LISTING,'offered_price_krw':750000,'message':'DEMO 제안','repair_requests':[]})

    def test_offer_blocked_before_approval(self):
        action=self._draft()
        with self.assertRaises(AgentError) as c:
            self.post(self.buyer, '/api/agent/v1/negotiations/actions/'+action['id']+'/execute')
        self.assertEqual(c.exception.status,409)
        offers=self.get(self.buyer,'/api/agent/v1/offers?listing_id='+LISTING)
        self.assertEqual(len(offers['items']),0)

    def test_offer_approval_execution_and_counterparty(self):
        action=self._draft()
        self.post(self.buyer,'/api/agent/v1/negotiations/actions/'+action['id']+'/approve')
        out=self.post(self.buyer,'/api/agent/v1/negotiations/actions/'+action['id']+'/execute')
        self.assertEqual(out['status'],'EXECUTED')
        oid=out['created_offer_id']
        seller_offers=self.get(self.seller,'/api/agent/v1/offers?listing_id='+LISTING)
        self.assertEqual(seller_offers['items'][0]['id'],oid)
        with self.assertRaises(AgentError):
            self.post(self.buyer, '/api/agent/v1/offers/'+oid+'/accept',{'expected_version':1})
        counter=self.post(self.seller,'/api/agent/v1/negotiations/counter-draft',
            {'offer_id':oid,'offered_price_krw':780000,'message':'역제안'})
        self.post(self.seller,'/api/agent/v1/negotiations/actions/'+counter['id']+'/approve')
        sent=self.post(self.seller,'/api/agent/v1/negotiations/actions/'+counter['id']+'/execute')
        new_id=sent['created_offer_id']
        tx=self.post(self.buyer,'/api/agent/v1/offers/'+new_id+'/accept',{'expected_version':1})
        self.assertEqual(tx['status'],'AWAITING_HANDOVER')
        checks=self.get(self.seller, '/api/agent/v1/transactions/'+tx['id']+'/handover-checks')
        self.assertEqual(checks['items'],[])
        check=self.post(self.seller, '/api/agent/v1/transactions/'+tx['id']+'/handover-checks',
                       {'check_key':'source_manifest','result':'SELLER_SUBMITTED','evidence_refs':[]})
        self.assertTrue(check['seller_submitted'])
        self.assertFalse(check['buyer_confirmed'])
        self.assertFalse(check['agent_checked'])

    def test_action_inaccessible_to_another_actor(self):
        action=self._draft()
        with self.assertRaises(AgentError) as c:
            self.get(self.seller, '/api/agent/v1/negotiations/actions/'+action['id'])
        self.assertEqual(c.exception.status,404)

    def test_missing_write_key_blocked(self):
        with self.assertRaises(AgentError) as c:
            self.buyer.request('POST','/api/agent/v1/jobs',{'task_type':'RECOMMEND','preferences':defaults()},write=True,key=None)
        self.assertEqual(c.exception.status,422)

    def test_disabled_llm(self):
        with self.assertRaises(AgentError) as c:
            self.post(self.buyer,'/api/agent/v1/assistant/chat',{'message':'hello','history':[]})
        self.assertEqual(c.exception.status,409)

    def test_live_writes_blocked(self):
        import agent.core as core
        with patch.object(core,'writes_enabled',lambda:False):
            with self.assertRaises(AgentError) as c:
                self.post(self.buyer,'/api/agent/v1/negotiations/draft',
                    {'listing_id':LISTING,'offered_price_krw':500000,'message':'demo'})
        self.assertEqual(c.exception.status,403)




class ChatFirstToolTest(unittest.TestCase):
    """Chat tools must not bypass platform's human-approval boundary."""
    setUp = SingleProcessAgentTest.setUp
    get = SingleProcessAgentTest.get
    post = SingleProcessAgentTest.post
    _draft = SingleProcessAgentTest._draft

    def test_ordinal_is_not_misread_as_offer_price(self):
        from agent.chat import _offline_price
        self.assertEqual(_offline_price('1번 매물에 50만원 제안 준비해줘'), 500000)
        self.assertEqual(_offline_price('100만원 이하 프로젝트 추천해줘'), 1000000)

    def test_chat_search_and_followup_inspection(self):
        from agent.chat import ChatAgent
        ctx = {}
        listing = ChatAgent('구매자 B').reply('매물 목록 보여줘', [], ctx)
        self.assertEqual(listing['events'][0]['name'], 'search_listings')
        self.assertTrue(listing['events'][0]['success'])
        self.assertEqual(len(ctx['recent_listings']), 3)
        inspected = ChatAgent('구매자 B').reply('첫 번째 매물 실사해줘', [], ctx)
        self.assertEqual(inspected['events'][0]['name'], 'inspect_listing')
        self.assertEqual(inspected['events'][0]['data']['status'], 'PARTIAL')
        self.assertEqual(inspected['events'][0]['data']['report']['verdict'], 'UNVERIFIED')

    def test_recommendation_from_conversation(self):
        from agent.chat import ChatAgent
        result = ChatAgent('구매자 B').reply('100만원 이하 Python 프로젝트 추천해줘', [], {})
        self.assertEqual(result['events'][0]['name'], 'recommend_listings')
        self.assertTrue(result['events'][0]['success'])
        self.assertTrue(all(x['price_krw'] <= 1000000 for x in result['events'][0]['data']['ranked']))
        self.assertEqual(result['mode'], 'offline')

    def test_chat_prepares_offer_but_never_sends_without_buttons(self):
        from agent.chat import ChatAgent
        from agent.tools import perform_confirmed_action
        ctx = {}
        ChatAgent('구매자 B').reply('매물 목록 보여줘', [], ctx)
        result = ChatAgent('구매자 B').reply('1번 매물에 50만원 제안 전송해줘', [], ctx)
        self.assertEqual(result['pending']['kind'], 'offer_draft')
        self.assertEqual(result['pending']['price_krw'], 500000)
        self.assertEqual(len(self.get(self.buyer,'/api/agent/v1/offers?listing_id='+LISTING)['items']), 0)
        msg, review = perform_confirmed_action('구매자 B', result['pending'], 'create')
        self.assertEqual(review['kind'], 'review_action')
        action = self.get(self.buyer, '/api/agent/v1/negotiations/actions/'+review['action_id'])
        self.assertEqual(action['status'], 'PENDING_APPROVAL')
        self.assertEqual(len(self.get(self.buyer,'/api/agent/v1/offers?listing_id='+LISTING)['items']), 0)
        with self.assertRaises(ValueError):
            perform_confirmed_action('구매자 B', review, 'execute')
        msg, review = perform_confirmed_action('구매자 B', review, 'approve')
        self.assertIn('아직', msg)
        self.assertEqual(len(self.get(self.buyer,'/api/agent/v1/offers?listing_id='+LISTING)['items']), 0)
        msg, done = perform_confirmed_action('구매자 B', review, 'execute')
        self.assertIsNone(done)
        self.assertEqual(len(self.get(self.buyer,'/api/agent/v1/offers?listing_id='+LISTING)['items']), 1)

    def test_confirmation_rejects_foreign_actor(self):
        from agent.tools import perform_confirmed_action
        with self.assertRaises(ValueError):
            perform_confirmed_action('판매자 A', {'actor':'구매자 B','kind':'offer_draft', 'token':'test'}, 'create')

    def test_unsafe_tool_name_rejected(self):
        from agent.tools import ToolDispatcher
        event, pending = ToolDispatcher('구매자 B', {}).invoke('exec_python', {'code':'import os'})
        self.assertFalse(event.success)
        self.assertIsNone(pending)

    def test_zip_inspect_via_conversation_tool(self):
        from agent.tools import ToolDispatcher
        raw=(Path(__file__).resolve().parent.parent/'fixtures'/'demo_incomplete_app.zip').read_bytes()
        ctx = {'attachment_bytes':raw}
        event, pending = ToolDispatcher('판매자 A',ctx).invoke('inspect_attached_zip', {'listing':LISTING})
        self.assertTrue(event.success, event.summary)
        self.assertIsNone(pending)
        self.assertEqual(event.data['status'], 'PARTIAL')
        self.assertNotEqual(event.data['report']['dynamic_execution'],'PASS')

    def test_publish_report_requires_click(self):
        from agent.tools import ToolDispatcher, perform_confirmed_action
        raw=(Path(__file__).resolve().parent.parent/'fixtures'/'demo_incomplete_app.zip').read_bytes()
        tool = ToolDispatcher('판매자 A',{'attachment_bytes':raw})
        inspected,_ = tool.invoke('inspect_attached_zip',{'listing':LISTING})
        job_id = inspected.data['job_id']
        event, pending = tool.invoke('prepare_publish_report',{'job_id':job_id})
        self.assertTrue(event.success, event.summary)
        self.assertEqual(pending['kind'], 'publish_report')
        self.assertEqual(self.get(self.seller,'/api/agent/v1/listings/'+LISTING+'/reports')['items'], [])
        _, done = perform_confirmed_action('판매자 A',pending,'publish')
        self.assertIsNone(done)
        reports = self.get(self.seller,'/api/agent/v1/listings/'+LISTING+'/reports')['items']
        self.assertEqual(len(reports),1)
        self.assertEqual(reports[0]['review_status'],'PENDING_REVIEW')

    def test_handover_record_requires_click(self):
        from agent.tools import ToolDispatcher, perform_confirmed_action
        offer=self._draft()
        self.post(self.buyer, '/api/agent/v1/negotiations/actions/'+offer['id']+'/approve')
        sent=self.post(self.buyer, '/api/agent/v1/negotiations/actions/'+offer['id']+'/execute')
        counter=self.post(self.seller,'/api/agent/v1/negotiations/counter-draft',
            {'offer_id':sent['created_offer_id'],'offered_price_krw':780000,'message':'역제안'})
        self.post(self.seller,'/api/agent/v1/negotiations/actions/'+counter['id']+'/approve')
        counter_sent=self.post(self.seller,'/api/agent/v1/negotiations/actions/'+counter['id']+'/execute')
        tx=self.post(self.buyer, '/api/agent/v1/offers/'+counter_sent['created_offer_id']+'/accept', {'expected_version':1})
        tool=ToolDispatcher('판매자 A',{})
        args={'transaction_id':tx['id'],'check_key':'source_manifest','result':'SELLER_SUBMITTED','remarks':'정적 자료 제출'}
        event, pending=tool.invoke('prepare_handover_check',args)
        self.assertTrue(event.success, event.summary)
        self.assertEqual(self.get(self.seller,'/api/agent/v1/transactions/'+tx['id']+'/handover-checks')['items'],[])
        _,done=perform_confirmed_action('판매자 A', pending,'record')
        self.assertIsNone(done)
        record=self.get(self.seller,'/api/agent/v1/transactions/'+tx['id']+'/handover-checks')['items'][0]
        self.assertFalse(record['buyer_confirmed'])

    def test_live_mode_does_not_stage_writes(self):
        import agent.tools as tools
        with patch.object(tools, 'AGENT_MODE', 'live'):
            event,pending=tools.ToolDispatcher('구매자 B',{}).invoke('prepare_offer',
                              {'listing':LISTING,'price_krw':500000,'message':'test'})
        self.assertFalse(event.success)
        self.assertIsNone(pending)

    def test_no_api_key_disclosure(self):
        from agent.chat import ChatAgent
        result=ChatAgent('구매자 B').reply('sk-proj-abcdefghijklmnopqrstuvwxyz123456',[],{})
        self.assertEqual(result['mode'],'blocked')
        self.assertEqual(result['events'],[])

    def test_ordinals_in_model_arguments(self):
        from agent.tools import ToolDispatcher
        ctx = {}
        tool = ToolDispatcher('구매자 B', ctx)
        tool.invoke('search_listings', {'query': ''})
        event,_ = tool.invoke('inspect_listing', {'listing': '1번 매물'})
        self.assertTrue(event.success, event.summary)
        self.assertEqual(event.data['listing_title'], ctx['recent_listings'][0]['title'])

    def test_recent_zip_report_can_be_prepared_from_chat(self):
        from agent.chat import ChatAgent
        ctx = {'attachment_bytes': (Path(__file__).resolve().parent.parent/'fixtures'/'demo_incomplete_app.zip').read_bytes()}
        session = ChatAgent('판매자 A')
        session.reply('매물 목록 보여줘',[],ctx)
        inspected = session.reply('1번 매물 ZIP 검사해줘',[],ctx)
        self.assertEqual(inspected['events'][0]['name'],'inspect_attached_zip')
        self.assertTrue(inspected['events'][0]['success'])
        ctx.pop('attachment_bytes',None)
        staged = session.reply('방금 검사 보고서 제출 준비해줘',[],ctx)
        self.assertEqual(staged['pending']['kind'],'publish_report')
        self.assertEqual(staged['events'][0]['name'],'prepare_publish_report')

    def test_langchain_model_calls_real_dispatcher(self):
        import sys
        import types
        import agent.chat as chat
        from types import SimpleNamespace
        model_module = types.ModuleType('langchain_openai')
        msg_module = types.ModuleType('langchain_core.messages')
        class Message:
            def __init__(self, content=None, tool_call_id=None):
                self.content=content
                self.tool_call_id=tool_call_id
        for name in ('AIMessage','HumanMessage','SystemMessage','ToolMessage'):
            setattr(msg_module,name,Message)
        model_module.ChatOpenAI=lambda **kw: None
        class FakeModel:
            def __init__(self): self.calls=0; self.bound_tools=[]
            def bind_tools(self, tools, **kwargs): self.bound_tools=tools; return self
            def invoke(self, messages):
                self.calls+=1
                if self.calls==1:
                    return SimpleNamespace(content='',tool_calls=[{'id':'test-call-1','name':'search_listings','args':{'query':''}}])
                return SimpleNamespace(content='매물 3건을 찾아봤어요.',tool_calls=[])
        model = FakeModel()
        with patch.dict(sys.modules, {'langchain_openai':model_module, 'langchain_core.messages':msg_module}), \
                patch.object(chat, 'ENABLE_OPENAI_CHAT', True), \
                patch.object(chat, 'OPENAI_API_KEY','test-only-key'):
            result=chat.ChatAgent('구매자 B',model_factory=lambda:model).reply('매물 찾아줘',[],{})
        self.assertEqual(result['mode'],'openai')
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['name'],'search_listings')
        self.assertGreater(len(model.bound_tools),5)
        self.assertEqual(model.calls,2)


if __name__ == '__main__':
    unittest.main()
