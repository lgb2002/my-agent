"""Offline fakes exercise actual LLM routing / structured intake code paths.

No OpenAI request, no Replit request, no user credential required.
"""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch



FIELDS = dict(intent='recommendation', reset_profile=False, reuse_previous=False,
              use_saved_profile=False, objective=None, max_budget_krw=None,
              max_monthly_cost_krw=None, skill_level=None, risk_tolerance=None,
              preferred_tech_stack=None, require_preferred_stack=None,
              preferred_categories=None, qualitative_preferences=None,
              accept_default_for=[], clear_fields=[], evidence=[], followup_question=None)


def turn(**changes):
    values = dict(FIELDS)
    values.update(changes)
    from agent.llm_intake import RecommendationTurn
    return RecommendationTurn.model_validate(values)


def ev(field, quote):
    return {'field': field, 'quote': quote}


class FakeStructured:
    def __init__(self, decision):
        self.decision = decision
    def invoke(self, messages):
        return self.decision


class FakeModel:
    def __init__(self, decisions, *, tool_calls=None):
        self.decisions = iter(decisions)
        self.tool_calls = tool_calls or []
        self.bound_tools = None
        self.invoke_count = 0
        self.structured_count = 0
    def with_structured_output(self, schema, **kwargs):
        from agent.llm_intake import RecommendationTurn
        assert schema is RecommendationTurn
        assert kwargs == {'method':'json_schema', 'strict':True}
        self.structured_count += 1
        return FakeStructured(next(self.decisions))
    def bind_tools(self, tools, **kwargs):
        self.bound_tools = tools
        return self
    def invoke(self, messages):
        self.invoke_count += 1
        if self.tool_calls:
            return self.tool_calls.pop(0)
        return SimpleNamespace(content='단순한 안내입니다.', tool_calls=[])


class FakeMessages(types.ModuleType):
    class Message:
        def __init__(self, content='', tool_call_id=None):
            self.content=content
            self.tool_call_id=tool_call_id
    def __init__(self):
        super().__init__('langchain_core.messages')
        for name in ('AIMessage', 'HumanMessage', 'SystemMessage', 'ToolMessage'):
            setattr(self, name, self.Message)


class StructuredRoutingTest(unittest.TestCase):
    def setUp(self):
        import agent.chat as chat
        from agent.llm_intake import apply_recommendation_decision
        from agent.tools import ToolEvent as _ToolEvent
        global ToolEvent
        ToolEvent=_ToolEvent
        self.chat=chat
        self.apply_decision=apply_recommendation_decision
        self.fake_messages = FakeMessages()
        self.modules=patch.dict(sys.modules, {'langchain_core.messages': self.fake_messages})
        self.modules.start()
        self.flags=patch.multiple(chat, ENABLE_OPENAI_CHAT=True, OPENAI_API_KEY='test-key', OPENAI_MODEL='gpt-4.1-mini')
        self.flags.start()
    def tearDown(self):
        self.flags.stop()
        self.modules.stop()
    def agent(self, model):
        return self.chat.ChatAgent('구매자 B', model_factory=lambda: model)

    def test_single_turn_combined_conditions_and_one_tool_execution(self):
        user='수익 목적으로 예산 80만원이고 월 운영비는 5만원, 파이썬 중급이고 위험은 낮은 게 좋아. 추천해줘'
        d=turn(objective='수익 창출', max_budget_krw=800000, max_monthly_cost_krw=50000,
               skill_level='INTERMEDIATE', risk_tolerance='LOW', preferred_tech_stack=['Python'],
               evidence=[ev('objective','수익 목적으로'),ev('max_budget_krw','예산 80만원'),
                         ev('max_monthly_cost_krw','월 운영비는 5만원'),
                         ev('skill_level','파이썬 중급'),ev('risk_tolerance','위험은 낮은 게 좋아'),
                         ev('preferred_tech_stack','파이썬 중급')])
        model=FakeModel([d])
        recorded=[]
        def dispatch(_self, name, args):
            recorded.append((name,args))
            return ToolEvent('recommend_listings','맞춤 추천',True,'정확한 후보 2건을 찾았어요.',
                             {'ranked': []}), None
        context={}
        with patch.object(self.chat.ToolDispatcher, 'invoke', autospec=True, side_effect=dispatch):
            result=self.agent(model).reply(user,[],context)
        self.assertEqual(result['mode'],'openai_recommendation')
        self.assertEqual(len(recorded),1)
        self.assertEqual(recorded[0][0],'recommend_listings')
        self.assertEqual(recorded[0][1]['max_budget_krw'],800000)
        self.assertEqual(recorded[0][1]['max_monthly_cost_krw'],50000)
        self.assertEqual(recorded[0][1]['risk_tolerance'],'LOW')
        self.assertFalse(recorded[0][1]['require_preferred_stack'])
        self.assertNotIn('recommendation_intake',context)
        self.assertEqual(model.structured_count,1)

    def test_multi_turn_asks_only_unknown_and_handles_interruption(self):
        model=FakeModel([
            turn(followup_question='어떤 목적으로 프로젝트를 인수하시나요?'),
            turn(objective='개발 학습', max_budget_krw=500000,
                 evidence=[ev('objective','공부용'),ev('max_budget_krw','50만원')],
                 followup_question='개발 경험은 어느 정도인가요?'),
            turn(intent='other'),
            turn(skill_level='INTERMEDIATE',risk_tolerance='LOW',
                 evidence=[ev('skill_level','중급'),ev('risk_tolerance','리스크 낮게')])
        ], tool_calls=[SimpleNamespace(content='매물 조회 완료',tool_calls=[])])
        ctx={}; agent=self.agent(model)
        r1=agent.reply('나에게 맞는 거 추천',[],ctx)
        self.assertIn('목적',r1['content'])
        r2=agent.reply('공부용이고 50만원 이하여야 해',[],ctx)
        self.assertIn('개발 경험',r2['content'])
        r3=agent.reply('매물 목록 먼저 보여줘',[],ctx)
        self.assertEqual(r3['mode'],'openai')
        self.assertIn('recommendation_intake',ctx)
        collected=[]
        with patch.object(self.chat.ToolDispatcher,'invoke',autospec=True,
                          side_effect=lambda _s,n,a: (collected.append((n,a)) or ToolEvent(n,'추천',True,'완료',{}),None)):
            r4=agent.reply('중급이고 리스크 낮게 해줘',[],ctx)
        self.assertEqual(r4['mode'],'openai_recommendation')
        self.assertEqual(collected[0][1]['objective'],'개발 학습')
        self.assertEqual(collected[0][1]['max_budget_krw'],500000)
        self.assertEqual(collected[0][1]['skill_level'],'INTERMEDIATE')

    def test_model_cannot_fabricate_budget_without_user_quote(self):
        ctx={}
        d=turn(objective='수익 창출', max_budget_krw=100000000,
               evidence=[ev('objective','돈 벌고 싶어'),ev('max_budget_krw','예산 1억원')])
        phase,text=self.apply_decision(d,'돈 벌고 싶어. 예산은 아직 모르겠어',ctx)
        self.assertEqual(phase,'ask')
        self.assertIn('예산',text)
        self.assertNotIn('max_budget_krw',ctx['recommendation_intake']['profile'])

    def test_correction_overrides_and_clear(self):
        ctx={'recommendation_intake':{'profile':{'objective':'수익 창출', 'max_budget_krw':800000,
                 'skill_level':'BASIC','risk_tolerance':'HIGH'},'waiting':'risk_tolerance'}}
        d=turn(max_budget_krw=500000,risk_tolerance='LOW',
               evidence=[ev('max_budget_krw','예산을 50만원으로'),ev('risk_tolerance','위험은 낮게')])
        phase,payload=self.apply_decision(d,'예산을 50만원으로 수정하고 위험은 낮게',ctx)
        self.assertEqual(phase,'ready')
        self.assertEqual(payload['args']['max_budget_krw'],500000)
        self.assertEqual(payload['args']['risk_tolerance'],'LOW')

    def test_unknown_does_not_become_unconsented_default(self):
        ctx={'recommendation_intake':{'profile':{'objective':'포트폴리오','max_budget_krw':200000},
                                      'waiting':'skill_level'}}
        d=turn(accept_default_for=['skill_level','risk_tolerance'],
               evidence=[ev('skill_level','모름'),ev('risk_tolerance','모름')])
        phase,text=self.apply_decision(d,'모름',ctx)
        self.assertEqual(phase,'ask')
        self.assertIn('위험',text)
        self.assertEqual(ctx['recommendation_intake']['profile']['skill_level'],'BASIC')
        self.assertNotIn('risk_tolerance',ctx['recommendation_intake']['profile'])

    def test_tool_request_is_still_llm_tool_calling(self):
        model=FakeModel([turn(intent='other')],tool_calls=[
            SimpleNamespace(content='',tool_calls=[{'id':'tool1','name':'search_listings','args':{'query':''}}]),
            SimpleNamespace(content='찾은 매물을 안내했습니다.',tool_calls=[])])
        called=[]
        def dispatch(_self, name, args):
            called.append(name)
            return ToolEvent(name,'매물 검색',True,'매물 1건',{'listings': []}),None
        with patch.object(self.chat.ToolDispatcher,'invoke',autospec=True,side_effect=dispatch):
            result=self.agent(model).reply('현재 등록된 매물 목록 보여줘',[],{})
        self.assertEqual(result['mode'],'openai')
        self.assertEqual(called,['search_listings'])
        self.assertEqual(len(model.bound_tools),9)

    def test_model_error_never_falls_back_to_regex(self):
        class FailedModel:
            def with_structured_output(self,*a,**k):
                raise ConnectionError('Secret must not leak')
        result=self.agent(FailedModel()).reply('50만원 이하 추천',[],{})
        self.assertEqual(result['mode'],'openai_error')
        self.assertEqual(result['events'],[])
        self.assertNotIn('Secret must not leak',result['content'])

    def test_saved_profile_explicitly_uses_user_specific_read_tool(self):
        profile={'max_budget_krw':700000, 'skill_level':'INTERMEDIATE',
                 'risk_tolerance':'LOW', 'objectives':['수익 창출'],
                 'preferred_tech_stack':['Python']}
        model=FakeModel([turn(use_saved_profile=True)])
        called=[]
        def dispatch(_self, name, args):
            called.append(name)
            if name=='get_buyer_preferences':
                return ToolEvent(name,'내 구매 조건',True,'조회 성공',{'buyer_preferences':profile}),None
            return ToolEvent(name,'맞춤 추천',True,'추천 완료',{'ranked':[]}),None
        with patch.object(self.chat.ToolDispatcher,'invoke',autospec=True,side_effect=dispatch):
            result=self.agent(model).reply('내 프로필을 불러와서 추천해줘',[],{})
        self.assertEqual(called,['get_buyer_preferences','recommend_listings'])
        self.assertEqual(result['mode'],'openai_recommendation')

    def test_money_is_verified_against_quoted_user_amount(self):
        d=turn(objective='수익', max_budget_krw=5_000_000,
               evidence=[ev('objective','수익용'), ev('max_budget_krw','예산 50만원')])
        ctx={}
        phase,text=self.apply_decision(d,'수익용, 예산 50만원, 개발 경험은 잘 모르겠어',ctx)
        self.assertEqual(phase,'ask')
        self.assertNotIn('max_budget_krw',ctx['recommendation_intake']['profile'])

    def test_previous_profile_can_be_reused_and_modified(self):
        ctx={'last_recommendation_profile':{'objective':'수익 창출',
             'max_budget_krw':900000,'skill_level':'INTERMEDIATE','risk_tolerance':'LOW'}}
        d=turn(reuse_previous=True,max_budget_krw=500000,evidence=[ev('max_budget_krw','50만원')])
        phase,payload=self.apply_decision(d,'다시 50만원으로 변경해서 추천',ctx)
        self.assertEqual(phase,'ready')
        self.assertEqual(payload['args']['max_budget_krw'],500000)
        self.assertEqual(payload['args']['objective'],'수익 창출')

    def test_cancel_resets_only_recommendation_intake(self):
        ctx={'recommendation_intake':{'profile':{'objective':'수익'},'waiting':'max_budget_krw'},'recent_listings':[{'id':'123'}]}
        phase,text=self.apply_decision(turn(intent='cancel_recommendation'),'취소',ctx)
        self.assertEqual(phase,'cancel')
        self.assertNotIn('recommendation_intake',ctx)
        self.assertIn('recent_listings',ctx)

    def test_unsupported_category_is_rejected(self):
        d=turn(objective='게임 공부',max_budget_krw=400000,skill_level='BASIC',risk_tolerance='LOW',
               preferred_categories=['saas','unknown_category'],
               evidence=[ev('objective','게임 공부'),ev('max_budget_krw','40만원'),
                         ev('skill_level','기초'),ev('risk_tolerance','저위험'),
                         ev('preferred_categories','게임')])
        ctx={}
        phase,value=self.apply_decision(d,'게임 공부, 예산 40만원, 기초 수준에 저위험 게임 찾기',ctx)
        self.assertEqual(phase,'ready')
        self.assertEqual(value['args']['preferred_categories'],['saas'])

if __name__=='__main__':
    unittest.main()
