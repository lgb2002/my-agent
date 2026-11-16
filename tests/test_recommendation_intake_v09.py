"""Focused v0.9 regression: no guessed preferences, hard constraints, top 3."""
import unittest
from unittest.mock import patch

from agent.recommendation_intake import advance
from core.policy import recommendation


class IntakeTest(unittest.TestCase):
    def test_missing_criteria_ask_before_any_tool_call(self):
        ctx = {}
        first = advance('맞춤 추천해줘', ctx)
        self.assertIn('목적', first['message'])
        next_ = advance('학습 용도로', ctx)
        self.assertIn('예산', next_['message'])
        next_ = advance('60만원', ctx)
        self.assertIn('개발 경험', next_['message'])
        next_ = advance('초보', ctx)
        self.assertIn('위험', next_['message'])
        final = advance('보수적으로', ctx)
        self.assertEqual(final['args']['max_budget_krw'], 600000)
        self.assertEqual(final['args']['objective'], '개발 학습')
        self.assertEqual(final['args']['risk_tolerance'], 'LOW')
        self.assertNotIn('recommendation_intake', ctx)

    def test_tech_hard_filter_requested_explicitly(self):
        ctx = {}
        first = advance('70만원 이하 Python 프로젝트 추천해줘. 포트폴리오용, 초급, 저위험', ctx)
        self.assertIn('args', first)
        self.assertTrue(first['args']['require_preferred_stack'])
        self.assertIn('Python', first['args']['preferred_tech_stack'])

    def test_default_only_when_user_explicitly_skips(self):
        ctx={}
        advance('추천해줘',ctx)
        advance('재판매할 거야',ctx)
        advance('80만원',ctx)
        next_=advance('모름',ctx)
        self.assertIn('위험', next_['message'])
        final=advance('모름',ctx)
        self.assertIn('args', final)
        self.assertEqual(len(final['assumptions']), 2)

    def test_consent_and_cancel(self):
        ctx={}
        advance('추천해줘',ctx)
        self.assertIn('취소', advance('취소',ctx)['message'])
        self.assertNotIn('recommendation_intake', ctx)

    def test_model_cannot_skip_intake_even_if_enabled(self):
        from agent.chat import ChatAgent
        ctx={}
        with patch('agent.chat.ENABLE_OPENAI_CHAT', True), patch('agent.chat.OPENAI_API_KEY','stub-key'):
            result=ChatAgent('구매자 B').reply('맞춤 추천해줘',[],ctx)
        self.assertEqual(result['mode'], 'recommendation_intake')
        self.assertFalse(result['events'])

    def test_direct_tool_does_not_guess_preferences(self):
        from agent.tools import ToolDispatcher
        event, _ = ToolDispatcher('구매자 B', {}).invoke('recommend_listings', {'max_budget_krw':1000000})
        self.assertFalse(event.success)
        self.assertIn('구매 목적', event.summary)

    def test_read_existing_platform_profile_when_explicitly_requested(self):
        from agent.recommendation_intake import from_saved_profile
        p = from_saved_profile({'max_budget_krw':750000,'objectives':['서비스 운영'],
              'skill_level':'INTERMEDIATE','risk_tolerance':'LOW',
              'preferred_tech_stack':['Python'], 'max_monthly_cost_krw':0,
              'owner_token':'should-never-be-copied'})
        self.assertEqual(p['max_budget_krw'], 750000)
        self.assertEqual(p['max_monthly_cost_krw'], 0)
        self.assertNotIn('owner_token', p)
        ctx={'recommendation_intake':{'profile':p,'waiting':''}}
        step=advance('추천해줘',ctx)
        self.assertIn('args', step)
        self.assertFalse(step['args']['require_preferred_stack'])

    def test_saved_profile_without_personal_auth_fails_safe(self):
        from agent.chat import ChatAgent
        result = ChatAgent('구매자 B').reply('내 프로필로 추천해줘', [], {})
        self.assertFalse(result['events'][0]['success'])
        self.assertIn('직접', result['content'])

    def test_without_unit_price_does_not_guess(self):
        ctx={}
        x=advance('100 Python 추천',ctx)
        self.assertIn('목적', x['message'])
        x=advance('학습',ctx)
        self.assertIn('예산', x['message'])
        self.assertNotIn('max_budget_krw',ctx['recommendation_intake']['profile'])


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.items=[
            {'id':'a','status':'ACTIVE','price_krw':500000,'category':'web_app','tech_stack':['Python'],'known_defects':[], 'verification_status':'STATIC_CHECKED','lifecycle_status':'ACTIVE'},
            {'id':'b','status':'ACTIVE','price_krw':500000,'category':'game','tech_stack':['JavaScript'],'known_defects':[], 'verification_status':'STATIC_CHECKED'},
            {'id':'c','status':'ACTIVE','price_krw':700000,'category':'web_app','tech_stack':['Python'],'known_defects':[], 'verification_status':'STATIC_CHECKED'},
            {'id':'d','status':'ACTIVE','price_krw':400000,'category':'web_app','tech_stack':['Python'],'known_defects':[], 'verification_status':'STATIC_CHECKED'},
            {'id':'e','status':'ACTIVE','price_krw':300000,'category':'web_app','tech_stack':['Python'],'known_defects':[], 'verification_status':'STATIC_CHECKED'},
        ]
        self.prefs={'max_budget_krw':600000,'skill_level':'BASIC','risk_tolerance':'LOW', 'objectives':['학습'],
                    'preferred_tech_stack':['Python'],'require_preferred_stack':True,'preferred_categories':['web_app'], 'max_results':2}

    def test_rejects_wrong_tech_category_price_and_caps(self):
        out=recommendation(self.items,self.prefs,demo_only=False)
        self.assertEqual(out['eligible_count'],3)
        self.assertEqual(len(out['ranked']),2)
        self.assertEqual(len(out['excluded']),2)
        self.assertTrue(all(x['listing_id'] not in ('b','c') for x in out['ranked']))

    def test_profit_risk_not_misrepresented_as_verified(self):
        prefs={**self.prefs,'objectives':['수익 창출'],'preferred_categories':[]}
        out=recommendation(self.items,prefs,demo_only=False)
        self.assertTrue(all(any('수익' in risk for risk in x['risks']) for x in out['ranked']))


if __name__ == '__main__':
    unittest.main()
