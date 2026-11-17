"""Regression for conversational intake and tool discoverability after first turn."""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.recommendation_intake import advance
from agent.chat import ChatAgent
from agent.tools import ToolEvent

ROOT = Path(__file__).resolve().parents[1]


class MultiAnswerTest(unittest.TestCase):
    def setUp(self):
        self.context = {}
        advance('나에게 맞는 프로젝트 추천해줘', self.context)

    def test_one_message_holds_all_four_constraints_and_cannot_flip_risk(self):
        result = advance('수익 목적이고 예산은 50만원, 파이썬 중급이고 위험은 적은 게 좋아', self.context)
        self.assertIn('args', result)
        self.assertEqual(result['args']['max_budget_krw'], 500000)
        self.assertEqual(result['args']['skill_level'], 'INTERMEDIATE')
        self.assertEqual(result['args']['risk_tolerance'], 'LOW')
        self.assertFalse(result['args']['require_preferred_stack'])
        self.assertIn('Python', result['args']['preferred_tech_stack'])

    def test_risk_synonyms_and_followup_minimal_answer(self):
        phrases = ['리스크는 낮게', '위험이 낮은', '위험은 적은 게 좋아', '위험 낮음',
                   '리스크 적은 편', '위험 감수 적음', '보수적으로', '안정적인 게 좋아']
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                context = {}
                advance('추천해줘', context)
                result = advance('수익 목적 예산 50만원 초보 ' + phrase, context)
                self.assertEqual(result['args']['risk_tolerance'], 'LOW')
        ctx={}
        advance('맞춤 추천해줘', ctx)
        advance('개발 공부',ctx)
        advance('70만원',ctx)
        advance('초보',ctx)
        result=advance('낮게',ctx)
        self.assertEqual(result['args']['risk_tolerance'],'LOW')

    def test_separate_monthly_cost_and_budget_in_any_order(self):
        for msg in ('수익 목적으로 월 운영비 5만원, 구매 예산 80만원, 초보, 위험 낮음',
                    '초보, 저위험, 수익 목적, 예산 80만원이고 월 비용은 5만원'):
            with self.subTest(message=msg):
                ctx={}
                advance('추천해줘',ctx)
                result=advance(msg,ctx)
                self.assertEqual(result['args']['max_budget_krw'],800000)
                self.assertEqual(result['args']['max_monthly_cost_krw'],50000)

    def test_monthly_cost_alone_is_not_acquisition_budget(self):
        result=advance('수익 목적, 월 운영비 5만원, 개발 수준 초급, 저위험',self.context)
        self.assertIn('구매 예산',result['message'])
        self.assertNotIn('max_budget_krw',self.context['recommendation_intake']['profile'])
        self.assertEqual(self.context['recommendation_intake']['profile']['max_monthly_cost_krw'],50000)

    def test_clarification_shows_already_captured_conditions(self):
        result=advance('수익 목적, 50만원, Python 중급이고',self.context)
        self.assertIn('확인한 조건',result['message'])
        self.assertIn('500,000원',result['message'])
        self.assertIn('위험',result['message'])
        final=advance('리스크 낮게 해줘',self.context)
        self.assertIn('args', final)

    def test_explicit_tech_mandatory_even_with_skill_statement(self):
        result=advance('수익 목적 80만원 파이썬 중급, Python 프로젝트 추천, 저위험',self.context)
        self.assertTrue(result['args']['require_preferred_stack'])

    def test_other_request_does_not_get_swallowed_in_questionnaire(self):
        result=advance('현재 매물 목록 보여줘',self.context)
        self.assertIsNone(result)
        self.assertIn('recommendation_intake',self.context)

    def test_no_guess_when_user_does_not_supply_risk(self):
        result=advance('수익 목적, 50만원, Python 중급',self.context)
        self.assertNotIn('args',result)
        self.assertIn('위험',result['message'])

    def test_chat_agent_invokes_once_with_all_combined_answers(self):
        context={}
        agent=ChatAgent('구매자 B')
        intro=agent.reply('맞춤 추천해줘',[],context)
        self.assertEqual(intro['events'],[])
        observed=[]
        def fake_invoke(_self, name, args):
            observed.append((name,args))
            return ToolEvent('recommend_listings','맞춤 추천',True,'상위 3건을 찾았어요.',{}), None
        with patch('agent.chat.ToolDispatcher.invoke', autospec=True, side_effect=fake_invoke):
            result=agent.reply('수익용이고 구매 예산 60만원, 개발 중급, 리스크 낮게',[],context)
        self.assertEqual(result['mode'],'recommendation')
        self.assertEqual(len(observed),1)
        self.assertEqual(observed[0][0],'recommend_listings')
        self.assertEqual(observed[0][1]['risk_tolerance'],'LOW')
        self.assertEqual(observed[0][1]['max_budget_krw'],600000)
        self.assertIn('추천에 적용한 조건',result['content'])
        self.assertIn('600,000원',result['content'])


class ToolAccessUiTest(unittest.TestCase):
    def test_available_tool_directory_not_behind_developer_flag(self):
        source=(ROOT/'app.py').read_text(encoding='utf8')
        tree=ast.parse(source)
        visible=[n for n in ast.walk(tree) if isinstance(n,ast.With) and
                 '사용 가능한 도구' in (ast.get_source_segment(source,n) or '')]
        self.assertTrue(visible)
        self.assertIn('continue_tool_v11_',source)
        self.assertIn('if session["turns"]:',source)
        self.assertIn('실행 결과와 근거 보기',source)
        self.assertIn('tool-activity',source)

    def test_tool_badge_escapes_untrusted_text(self):
        from html import escape
        source=(ROOT/'app.py').read_text(encoding='utf8')
        self.assertIn('escape(label)',source)
        self.assertEqual(escape('<b>'), '&lt;b&gt;')

    def test_no_server_and_auth_policies_preserved(self):
        app=(ROOT/'app.py').read_text(encoding='utf8')
        tools=(ROOT/'agent/tools.py').read_text(encoding='utf8')
        self.assertIn('perform_confirmed_action',app)
        self.assertIn('set_request_context(token=token',app)
        self.assertIn('ToolDispatcher',tools)

if __name__=='__main__':
    unittest.main()
