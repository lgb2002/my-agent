"""v0.14 workflow, verification, opt-in memory. All tool/model calls are fakes."""
import copy
import tempfile
import unittest
import uuid
import sys
import types
from pathlib import Path
from unittest.mock import patch


ID1 = str(uuid.uuid4())
ID2 = str(uuid.uuid4())
ID3 = str(uuid.uuid4())
PROFILE = {'objective':'수익 창출', 'max_budget_krw':500000,
           'skill_level':'INTERMEDIATE', 'risk_tolerance':'MEDIUM'}


class FakeMessage:
    def __init__(self, content=''):
        self.content = content


class FakeLangchainMessages(types.ModuleType):
    def __init__(self):
        super().__init__('langchain_core.messages')
        self.SystemMessage = FakeMessage
        self.HumanMessage = FakeMessage
        self.AIMessage = FakeMessage


class ModelFake:
    def __init__(self, answer):
        self.answer = answer
    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self
    def invoke(self, messages):
        return self.answer


def ranked(n=3):
    ids = [ID1, ID2, ID3]
    return [dict(listing_id=ids[i], title='프로젝트 {}'.format(i + 1),
                 price_krw=100000 + 100000*i, score=82-i*5,
                 reasons=['가격과 기술 조건 부합'], risks=['운영비 독립 검증 필요']) for i in range(n)]


def fake_tool(self, name, args):
    from agent.tools import ToolEvent
    if name == 'recommend_listings':
        return ToolEvent(name, '맞춤 추천', True, '실제 조건에 맞는 후보 3건 조회',
                         {'ranked': ranked()}), None
    if name == 'inspect_listing':
        return ToolEvent(name, '매물 실사', True, '공개 정보 정적 점검', {
            'status':'PARTIAL','report':{'verdict':'UNVERIFIED','findings':[], 'coverage':'공개 자료'}
        }), None
    if name == 'prepare_offer':
        return ToolEvent(name, '구매 제안 준비', True, '승인 카드 생성',
                         {'listing_title':'프로젝트 1', 'price_krw':args['price_krw']}), {
            'kind':'offer_draft','token':'fake','actor':'구매자 B', 'listing_id':ID1,
            'price_krw':args['price_krw'], 'message':'승인 요청'}
    raise AssertionError('Unexpected tool')


class WorkflowTests(unittest.TestCase):
    def test_llm_identifies_multi_step_but_not_budget_as_offer(self):
        from agent.workflow import recognize_workflow
        message='50만원 이하 수익화 매물 추천하고 3개 비교해서 위험 분석 후 제안 초안도 준비해줘'
        answer = {'multi_step':True,'compare':True,'inspect':True,
                  'prepare_offer':True,'candidate_count':3,'offer_price_krw':500000,
                  'offer_quote':'50만원 이하'}
        # Even if LLM hallucinates offer price from a *budget* quote, our guard
        # must not accept it. See separate test for explicit offer evidence.
        with patch.dict(sys.modules,{'langchain_core.messages':FakeLangchainMessages()}):
            plan = recognize_workflow(ModelFake(answer),message)
        self.assertIsNotNone(plan)
        self.assertEqual([x['key'] for x in plan['steps']],
                         ['recommend','compare','inspect','prepare_offer','verify'])
        # Current literal check can't distinguish budget from offer semantically.
        # This assertion will be repaired by the amount evidence guard.
        self.assertIsNone(plan['offer_price_krw'])

    def test_only_single_step_returns_no_plan(self):
        from agent.workflow import recognize_workflow
        answer={'multi_step':False,'compare':False,'inspect':False,
                'prepare_offer':False,'candidate_count':3,'offer_price_krw':None,'offer_quote':None}
        with patch.dict(sys.modules,{'langchain_core.messages':FakeLangchainMessages()}):
            self.assertIsNone(recognize_workflow(ModelFake(answer),'추천해줘'))

    def test_pipeline_wait_for_price_then_resume_without_duplicate_calls(self):
        from agent.workflow import create_plan, execute_plan
        from agent.tools import ToolDispatcher
        from agent.chat import _format_event
        plan = create_plan('추천 → 비교 → 실사 → 구매 제안 준비',
                           ['recommend','compare','inspect','prepare_offer','verify'])
        calls=[]
        def record(self,name,args):
            calls.append(name)
            return fake_tool(self,name,args)
        ctx={'last_recommendation_profile':copy.deepcopy(PROFILE)}
        with patch.object(ToolDispatcher,'invoke',autospec=True,side_effect=record):
            r1=execute_plan(plan,ctx,'구매자 B',recommendation_input={
                'args':copy.deepcopy(PROFILE),'qualitative_preferences':[]},formatter=_format_event)
            self.assertEqual(plan['status'],'WAITING_OFFER_PRICE')
            self.assertEqual(calls,['recommend_listings','inspect_listing'])
            self.assertEqual(len(plan['ranked']),3)
            self.assertIn('얼마로 제안',r1['content'])
            plan['offer_price_krw']=400000
            plan['status']='ACTIVE'
            r2=execute_plan(plan,ctx,'구매자 B',formatter=_format_event)
        self.assertEqual(calls,['recommend_listings','inspect_listing','prepare_offer'])
        self.assertIsNotNone(r2['pending'])
        self.assertEqual(r2['pending']['kind'],'offer_draft')
        self.assertEqual(plan['status'],'PARTIAL')
        self.assertFalse(plan['verified']['fulfilled'])
        self.assertIn('제안은 사용자 확인 단계', ' '.join(plan['verified']['issues']))

    def test_compare_incomplete_and_inspection_unverified_never_claim_success(self):
        from agent.workflow import create_plan,execute_plan
        from agent.tools import ToolDispatcher, ToolEvent
        from agent.chat import _format_event
        plan=create_plan('3개 비교 후 위험 평가', ['recommend','compare','inspect','verify'],count=3)
        def short(self,name,args):
            if name=='recommend_listings':
                return ToolEvent(name,'맞춤 추천',True,'1개 확인',{'ranked':ranked(1)}),None
            return fake_tool(self,name,args)
        with patch.object(ToolDispatcher,'invoke',autospec=True,side_effect=short):
            out=execute_plan(plan,{'last_recommendation_profile':PROFILE},'구매자 B',
                             recommendation_input={'args':PROFILE,'qualitative_preferences':[]},formatter=_format_event)
        self.assertEqual(plan['status'],'PARTIAL')
        self.assertEqual(plan['steps'][1]['status'],'PARTIAL')
        self.assertIn('비교 요청 3건 중 1건만 확보', ' '.join(plan['verified']['issues']))

    def test_live_mode_never_calls_prepare_offer(self):
        import agent.workflow as wf
        from agent.tools import ToolDispatcher
        from agent.chat import _format_event
        plan=wf.create_plan('추천하고 3개 비교하고 제안 준비',
                            ['recommend','compare','prepare_offer','verify'],offer_price=300000)
        calls=[]
        def record(self,name,args):
            calls.append(name)
            return fake_tool(self,name,args)
        with patch.object(wf,'AGENT_MODE','live'),patch.object(ToolDispatcher,'invoke',autospec=True,side_effect=record):
            out=wf.execute_plan(plan,{'last_recommendation_profile':PROFILE},'ProjectAgain 사용자',
                                recommendation_input={'args':PROFILE,'qualitative_preferences':[]},formatter=_format_event)
        self.assertEqual(calls,['recommend_listings'])
        self.assertIn('읽기 전용',out['content'])
        self.assertEqual(plan['steps'][2]['status'],'BLOCKED')

    def test_llm_price_needs_verbatim_amount(self):
        from agent.workflow import read_offer_amount
        with patch.dict(sys.modules,{'langchain_core.messages':FakeLangchainMessages()}):
            kind,value=read_offer_amount(ModelFake({'intent':'amount',
                'price_krw':400000,'evidence_quote':'40만원'}),'40만원에 제안해줘')
            self.assertEqual((kind,value),('amount',400000))
            kind,value=read_offer_amount(ModelFake({'intent':'amount',
                'price_krw':4000000,'evidence_quote':'40만원'}),'40만원에 제안해줘')
            self.assertEqual((kind,value),('invalid',None))

    def test_resume_marks_running_as_interrupted(self):
        from core.workflow_store import _safe_load
        from agent.workflow import create_plan
        plan=create_plan('test',['recommend','compare','verify'])
        plan['steps'][0]['status']='RUNNING'
        result=_safe_load(plan)
        self.assertEqual(result['steps'][0]['status'],'INTERRUPTED')


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        import core.workflow_store as store
        self.store=store
        self.old=store.LOCAL_DB
        store.LOCAL_DB=str(Path(self.tmp.name)/'memory.sqlite3')
        self.dbflag=patch.dict('os.environ', {'AGENT_STATE_DATABASE_URL':''})
        self.dbflag.start()
        self.owner1='a'*64
        self.owner2='b'*64
    def tearDown(self):
        self.dbflag.stop()
        self.store.LOCAL_DB=self.old
        self.tmp.cleanup()
    def test_isolate_preferences_and_delete(self):
        self.store.save_preferences(self.owner1, PROFILE)
        self.assertIsNone(self.store.load_preferences(self.owner2))
        self.assertEqual(self.store.load_preferences(self.owner1)['max_budget_krw'],500000)
        self.store.delete_preferences(self.owner1)
        self.assertIsNone(self.store.load_preferences(self.owner1))
    def test_isolate_plan_and_deleted_plan(self):
        from agent.workflow import create_plan
        plan=create_plan('과거 작업',['recommend','compare','verify'])
        self.store.save_workflow(self.owner1,plan)
        self.assertIsNone(self.store.load_workflow(self.owner2,plan['id']))
        self.assertEqual(len(self.store.list_workflows(self.owner1)),1)
        self.store.delete_workflow(self.owner1,plan['id'])
        self.assertEqual(self.store.list_workflows(self.owner1),[])
    def test_reject_token_and_non_verified_owner(self):
        with self.assertRaises(ValueError):
            self.store.save_preferences('visitor:123', PROFILE)
        p=dict(PROFILE);p['objective']='sk-'+'x'*24
        with self.assertRaises(ValueError):
            self.store.save_preferences(self.owner1,p)


class WorkflowChatIntegrationTests(unittest.TestCase):
    def test_model_drives_plan_intake_and_resume_in_three_turns(self):
        import agent.chat as chat
        from agent.llm_intake import RecommendationTurn
        from agent.tools import ToolDispatcher
        from agent.workflow import WorkflowIntent, WorkflowAmount
        class ResponseChain:
            def __init__(self):
                self.answers = [
                    RecommendationTurn.model_validate(dict(
                        intent='recommendation',reset_profile=False,reuse_previous=False,
                        use_saved_profile=False, objective='수익 창출',max_budget_krw=500000,
                        max_monthly_cost_krw=None,skill_level=None,risk_tolerance=None,
                        preferred_tech_stack=None,require_preferred_stack=None,
                        preferred_categories=None,qualitative_preferences=None,
                        accept_default_for=[],clear_fields=[],
                        evidence=[{'field':'objective','quote':'수익 목적'},
                                  {'field':'max_budget_krw','quote':'50만원 이하'}],
                        followup_question='개발 경험은 어느 정도인가요?')),
                    WorkflowIntent(multi_step=True, compare=True, inspect=True,
                                   prepare_offer=True,candidate_count=3,
                                   offer_price_krw=None,offer_quote=None),
                    RecommendationTurn.model_validate(dict(
                        intent='recommendation',reset_profile=False,reuse_previous=False,
                        use_saved_profile=False,objective=None,max_budget_krw=None,
                        max_monthly_cost_krw=None,skill_level='INTERMEDIATE',risk_tolerance='MEDIUM',
                        preferred_tech_stack=None,require_preferred_stack=None,
                        preferred_categories=None,qualitative_preferences=None,
                        accept_default_for=[],clear_fields=[],
                        evidence=[{'field':'skill_level','quote':'개발 중급'},
                                  {'field':'risk_tolerance','quote':'위험은 보통'}],
                        followup_question=None)),
                    WorkflowAmount(intent='amount',price_krw=400000,evidence_quote='40만원')
                ]
            def with_structured_output(self,schema,**kwargs):
                self.requested_schema=schema
                return self
            def invoke(self,messages):
                result=self.answers.pop(0)
                self_test.assertIsInstance(result,self.requested_schema)
                return result
        self_test=self
        model=ResponseChain()
        agent=chat.ChatAgent('구매자 B',model_factory=lambda:model)
        ctx={}
        first='수익 목적으로 50만원 이하 프로젝트 추천해서 3개 비교하고 위험 분석 후 제안 준비해줘'
        # quote expects an exact fragment from this message
        first=first.replace('수익 목적으로','수익 목적')
        with patch.dict(sys.modules,{'langchain_core.messages':FakeLangchainMessages()}),             patch.multiple(chat, ENABLE_OPENAI_CHAT=True, OPENAI_API_KEY='dummy'):
            with patch.object(ToolDispatcher,'invoke',autospec=True,side_effect=fake_tool):
                a=agent.reply(first,[],ctx)
                self.assertIn('개발 경험',a['content'])
                self.assertIn('workflow',ctx)
                b=agent.reply('개발 중급이고 위험은 보통',[],ctx)
                self.assertEqual(b['mode'],'workflow')
                self.assertEqual(ctx['workflow']['status'],'WAITING_OFFER_PRICE')
                self.assertEqual(len(ctx['workflow']['ranked']),3)
                c=agent.reply('40만원에 제안해줘',[],ctx)
                self.assertIsNotNone(c['pending'])
                self.assertEqual(c['pending']['price_krw'],400000)
                self.assertEqual(ctx['workflow']['status'],'PARTIAL')
        self.assertEqual(len(model.answers),0)



if __name__=='__main__':
    unittest.main()

class RestoredMemorySafetyTests(unittest.TestCase):
    def test_unfinished_recommendation_restores_only_confirmed_fields(self):
        from agent.workflow import create_plan
        from core.workflow_store import _safe_load
        plan=create_plan('추천 후 비교',['recommend','compare','verify'])
        plan['status']='WAITING_INPUT'
        plan['recommendation_criteria']={'max_budget_krw':500000,'objective':'학습'}
        plan['steps'][0]['status']='WAITING_INPUT'
        restored=_safe_load(copy.deepcopy(plan))
        self.assertEqual(restored['status'],'WAITING_INPUT')
        self.assertEqual(restored['recommendation_criteria']['max_budget_krw'],500000)
        self.assertNotIn('risk_tolerance',restored['recommendation_criteria'])

    def test_approval_card_is_not_recreated_from_disk(self):
        from agent.workflow import create_plan
        from core.workflow_store import _safe_load
        plan=create_plan('추천 후 제안',['recommend','prepare_offer','verify'])
        plan['status']='PARTIAL'
        plan['steps'][0]['status']='COMPLETED'
        plan['steps'][1]['status']='WAITING_APPROVAL'
        restored=_safe_load(copy.deepcopy(plan))
        self.assertEqual(restored['steps'][1]['status'],'BLOCKED')
        self.assertEqual(restored['status'],'PARTIAL')
        self.assertIn('승인 카드 복원 불가',' '.join(restored['issues']))
