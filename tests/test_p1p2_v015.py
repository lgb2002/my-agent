"""V0.15: six-area regressions, no network or paid API calls."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


class RiskEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(id=str(uuid.uuid4()), title='정적 매물', status='ACTIVE', is_demo=True,
                         price_krw=300000, tech_stack=['Python'], category='web_app',
                         verification_status='STATIC_CHECKED', sale_rights_type='FULL_IP_ASSIGNMENT',
                         monthly_cost_estimate_krw=None, has_revenue=False, known_defects=[])
        self.prefs = dict(max_budget_krw=500000, skill_level='BASIC', risk_tolerance='MEDIUM',
                          objectives=['학습'], preferred_tech_stack=[], max_results=3)

    def test_risk_dimensions_are_per_evidence_field(self):
        from core.policy import recommendation
        row = recommendation([self.item],self.prefs)['ranked'][0]
        dims = {x['key']:x for x in row['risk_dimensions']}
        self.assertEqual(len(dims),7)
        self.assertEqual(dims['operations']['status'],'UNKNOWN')
        self.assertIn('안전으로 판단하지 않음',dims['operations']['explanation'])
        self.assertEqual(row['risk_label'],'검증 부족')

    def test_low_risk_excludes_unknown_cost_if_user_sets_cap(self):
        from core.policy import recommendation
        p = dict(self.prefs, risk_tolerance='LOW', max_monthly_cost_krw=10000)
        result = recommendation([self.item],p)
        self.assertEqual(result['ranked'],[])
        self.assertIn('운영비',str(result['excluded']))

    def test_risk_unknown_never_looks_like_verified_safety(self):
        from core.policy import recommendation
        listing = dict(self.item, verification_status='UNVERIFIED', sale_rights_type='')
        result = recommendation([listing],dict(self.prefs,risk_tolerance='LOW'))
        self.assertFalse(result['ranked'])
        self.assertIn('검사',str(result['excluded']))

class MemoryTests(unittest.TestCase):
    def test_condenses_confirmed_profile_and_task_without_tokens(self):
        from core.conversation_memory import build_context_digest
        from agent.workflow import create_plan
        context = {'last_recommendation_profile':{'objective':'수익', 'max_budget_krw':500000,
                                                  'risk_tolerance':'LOW'},
                   'recent_listings':[{'id':str(uuid.uuid4()), 'title':'파이썬 서비스'}],
                   'workflow':create_plan('검증 후 비교', ['recommend','compare','verify'])}
        history = [{'role':'user', 'content':f'과거 요청{i}'} for i in range(16)]
        output = build_context_digest(context,history)
        self.assertIn('500000',output)
        self.assertIn('검증 후 비교',output)
        self.assertIn('과거 요청',output)
        self.assertLessEqual(len(output),1800)

    def test_does_not_recap_apikey_as_user_fact(self):
        from core.conversation_memory import build_context_digest
        ctx={'last_recommendation_profile':{'objective':'학습','max_budget_krw':100000}}
        out=build_context_digest(ctx,[{'role':'user','content':'내 키 sk-'+'x'*50}]*20)
        self.assertNotIn('sk-',out)

class LiveDraftTests(unittest.TestCase):
    def setUp(self):
        self.lid=str(uuid.uuid4())
        self.uid='user-one'
        self.pending={'kind':'live_offer_draft','listing_id':self.lid,'price_krw':500000,
                      'message':'조건 확인 뒤 제안합니다', 'principal_id':self.uid,
                      'token':'ab'*18}

    def test_default_is_disabled(self):
        from core import live_actions as la
        with patch.object(la,'ENABLE_LIVE_DRAFTS',False), patch.object(la,'AGENT_MODE','live'):
            with self.assertRaises(ValueError):
                la.submit_confirmed_draft(self.pending)

    def test_token_required_and_user_bound(self):
        from core import live_actions as la
        with patch.object(la,'ENABLE_LIVE_DRAFTS',True),patch.object(la,'AGENT_MODE','live'):
            with patch.object(la,'delegated_token',return_value=''):
                with self.assertRaises(ValueError):
                    la.submit_confirmed_draft(self.pending)
            class Client:
                def me(self): return {'id':'other-account','scopes':['offer:draft']}
            with patch.object(la,'delegated_token',return_value='private-token'),patch.object(la,'LiveReadOnlyClient',return_value=Client()):
                with self.assertRaises(ValueError):
                    la.submit_confirmed_draft(self.pending)

    def test_submit_calls_draft_only_not_approve_execute(self):
        from core import live_actions as la
        called=[]
        actionid=str(uuid.uuid4())
        class Client:
            def me(self): return {'id':'user-one','scopes':['offer:draft']}
            def listing(self,lid): return {'id':lid,'seller_id':'seller','status':'ACTIVE'}
            def draft_action(self,proposal,key):
                called.append((proposal,key))
                return {'id':actionid,'status':'PENDING_APPROVAL'}
        with patch.object(la,'ENABLE_LIVE_DRAFTS',True),patch.object(la,'AGENT_MODE','live'),patch.object(la,'delegated_token',return_value='private-token'):
            with patch.object(la,'LiveReadOnlyClient',return_value=Client()):
                result=la.submit_confirmed_draft(self.pending)
        self.assertEqual(result,actionid)
        self.assertEqual(len(called),1)
        self.assertEqual(called[0][0]['action_type'],'SUBMIT_OFFER')
        self.assertEqual(len(called[0][1]),64)
        self.assertNotIn('private-token',str(called))

    def test_general_live_post_stays_blocked_even_if_draft_flag_true(self):
        from services import marketplace as m
        with patch.object(m,'ENABLE_LIVE_DRAFTS',True):
            with patch.object(m,'delegated_token',return_value='some-token'):
                # Tests write guard without needing a real host or network.
                with patch('core.marketplace_client.MarketplaceClient.__init__',return_value=None):
                    client=m.LiveReadOnlyClient()
                    with self.assertRaises(m.MarketplaceError):
                        client.request('POST','/api/v1/agent-actions',payload={})

class PersistenceTests(unittest.TestCase):
    def test_local_db_health_transient(self):
        import core.workflow_store as store
        with tempfile.TemporaryDirectory() as td:
            with patch.object(store,'LOCAL_DB',str(Path(td)/'state.db')):
                with patch.dict('os.environ',{'AGENT_STATE_DATABASE_URL':''}):
                    state=store.storage_health()
        self.assertEqual(state,{'ready':True,'kind':'sqlite','durable_across_cloud_redeploy':False})

class WorkflowTests(unittest.TestCase):
    def test_comparison_event_contains_grounded_rows(self):
        from agent.workflow import create_plan,execute_plan
        from agent.tools import ToolEvent,ToolDispatcher
        from agent.chat import _format_event
        rid=str(uuid.uuid4())
        row={'listing_id':rid,'title':'확인된 매물','price_krw':200000,'score':80,
             'risks':['권리 미확인'],'reasons':['예산 충족']}
        plan=create_plan('추천하고 비교',['recommend','compare','verify'],count=2)
        def tool(self,name,args):
            if name=='recommend_listings':return ToolEvent(name,'추천',True,'조회',{'ranked':[row]}),None
            raise AssertionError(name)
        with patch.object(ToolDispatcher,'invoke',autospec=True,side_effect=tool):
            out=execute_plan(plan,{'last_recommendation_profile':{'objective':'학습'}},'구매자 B',
                            recommendation_input={'args':{},'qualitative_preferences':[]},formatter=_format_event)
        comparison = [e for e in out['events'] if e['name']=='compare'][0]
        self.assertEqual(comparison['data']['ranked'][0]['listing_id'],rid)
        self.assertEqual(comparison['data']['requested'],2)


class RemoteActionStateTests(unittest.TestCase):
    def test_executed_offer_is_not_financial_transfer_verified(self):
        from agent.workflow import create_plan, verify_plan
        plan=create_plan('구매 제안', ['recommend','prepare_offer','verify'])
        plan['ranked']=[{'listing_id':str(uuid.uuid4()),'title':'테스트 매물','risk_checks':{}}]
        plan['steps'][0]['status']='COMPLETED'
        plan['steps'][1]['status']='COMPLETED'
        verified=verify_plan(plan)
        self.assertFalse(verified['fulfilled'])
        self.assertTrue(any('권리 이전' in str(x) for x in verified['issues']))

    def test_remote_action_id_is_saved_without_credentials(self):
        import core.workflow_store as store
        from agent.workflow import create_plan
        with tempfile.TemporaryDirectory() as td:
            with patch.object(store,'LOCAL_DB',str(Path(td)/'saved.db')):
                with patch.dict('os.environ',{'AGENT_STATE_DATABASE_URL':''}):
                    plan=create_plan('구매 제안 준비',['recommend','prepare_offer','verify'])
                    plan['remote_action_id']=str(uuid.uuid4())
                    plan['steps'][1]['status']='WAITING_APPROVAL'
                    store.save_workflow('a'*64,plan)
                    restored=store.load_workflow('a'*64,plan['id'])
        self.assertEqual(restored['remote_action_id'],plan['remote_action_id'])
        self.assertEqual(restored['steps'][1]['status'],'BLOCKED')
        self.assertNotIn('token',str(restored).lower())

if __name__=='__main__': unittest.main()
