"""v0.13 A/B/C regressions: evidence meaning, qualitative ranking, risk gates.

All model decisions are controlled fakes. No paid API or remote calls.
"""
import copy
import sys
import types
import unittest
from unittest.mock import patch

# Delay agent imports until tests actually run: other test modules configure an
# isolated SQLite directory at import time. Early imports would pollute DB state.
def apply_recommendation_decision(*args, **kwargs):
    from agent.llm_intake import apply_recommendation_decision as apply
    return apply(*args, **kwargs)


def recommendation(*args, **kwargs):
    from core.policy import recommendation as rank
    return rank(*args, **kwargs)


def apply_qualitative_review(*args, **kwargs):
    from agent.qualitative_review import apply_qualitative_review as apply
    return apply(*args, **kwargs)


def review_preferences_with_model(*args, **kwargs):
    from agent.qualitative_review import review_preferences_with_model as run
    return run(*args, **kwargs)


class _LazyReview:
    @staticmethod
    def model_validate(value):
        from agent.qualitative_review import PreferenceReview
        return PreferenceReview.model_validate(value)


PreferenceReview = _LazyReview


def turn(**kwargs):
    args = {
        'intent': 'recommendation', 'reset_profile': False, 'reuse_previous': False,
        'use_saved_profile': False, 'objective': None, 'max_budget_krw': None,
        'max_monthly_cost_krw': None, 'skill_level': None,
        'risk_tolerance': None, 'preferred_tech_stack': None,
        'require_preferred_stack': None, 'preferred_categories': None,
        'qualitative_preferences': None, 'accept_default_for': [],
        'clear_fields': [], 'evidence': [], 'followup_question': None,
    }
    args.update(kwargs)
    from agent.llm_intake import RecommendationTurn
    return RecommendationTurn.model_validate(args)


def ev(field, quote):
    return {'field': field, 'quote': quote}


def listing(lid='a', **kwargs):
    result = dict(id=lid, title=lid, status='ACTIVE', is_demo=True,
                  price_krw=250000, tech_stack=['Python'], category='web_app',
                  known_defects=[], verification_status='STATIC_CHECKED',
                  monthly_cost_estimate_krw=0,
                  sale_rights_type='FULL_IP_ASSIGNMENT',
                  lifecycle_status='ACTIVE', has_revenue=False,
                  description='공개된 Python 프로그램')
    result.update(kwargs)
    return result


def prefs(**kwargs):
    p = dict(max_budget_krw=500000, skill_level='BASIC', risk_tolerance='LOW',
             objectives=['학습'], preferred_tech_stack=[], max_results=3)
    p.update(kwargs)
    return p


class AMeaningValidationTests(unittest.TestCase):
    def test_reject_inverse_skill_meaning(self):
        ctx = {}
        d = turn(skill_level='ADVANCED', evidence=[ev('skill_level','완전 초보야')])
        kind, _ = apply_recommendation_decision(d,'개발은 완전 초보야',ctx)
        self.assertEqual(kind,'ask')
        self.assertNotIn('skill_level',ctx['recommendation_intake']['profile'])

    def test_reject_inverse_risk_meaning(self):
        ctx = {}
        d = turn(risk_tolerance='HIGH', evidence=[ev('risk_tolerance','위험은 낮게')])
        kind, _ = apply_recommendation_decision(d,'위험은 낮게 하고 싶어',ctx)
        self.assertEqual(kind,'ask')
        self.assertNotIn('risk_tolerance',ctx['recommendation_intake']['profile'])

    def test_low_risk_from_rejection_of_high_risk(self):
        ctx = {}
        d = turn(risk_tolerance='LOW', evidence=[ev('risk_tolerance','고위험은 싫어')])
        apply_recommendation_decision(d,'고위험은 싫어',ctx)
        self.assertEqual(ctx['recommendation_intake']['profile']['risk_tolerance'],'LOW')

    def test_negated_skill_should_not_count_as_skill(self):
        ctx = {}
        d = turn(skill_level='NONE', evidence=[ev('skill_level','초보는 아니야')])
        apply_recommendation_decision(d,'초보는 아니야',ctx)
        self.assertNotIn('skill_level',ctx['recommendation_intake']['profile'])

    def test_reject_opposite_objective(self):
        ctx = {}
        d = turn(objective='수익 창출', evidence=[ev('objective','개발 학습용')])
        apply_recommendation_decision(d,'개발 학습용',ctx)
        self.assertNotIn('objective',ctx['recommendation_intake']['profile'])

    def test_monthly_cost_not_budget_if_quote_contains_both(self):
        ctx = {}
        message = '구매 예산 50만원, 월 운영비 5만원'
        d = turn(max_budget_krw=500000, max_monthly_cost_krw=50000,
                 evidence=[ev('max_budget_krw',message),ev('max_monthly_cost_krw',message)])
        apply_recommendation_decision(d,message,ctx)
        self.assertNotIn('max_budget_krw',ctx['recommendation_intake']['profile'])
        self.assertNotIn('max_monthly_cost_krw',ctx['recommendation_intake']['profile'])

    def test_narrow_money_quotes_are_both_valid(self):
        ctx = {}
        message = '구매 예산 50만원, 월 운영비 5만원'
        d = turn(max_budget_krw=500000, max_monthly_cost_krw=50000,
                 evidence=[ev('max_budget_krw','예산 50만원'),ev('max_monthly_cost_krw','운영비 5만원')])
        apply_recommendation_decision(d,message,ctx)
        p = ctx['recommendation_intake']['profile']
        self.assertEqual(p['max_budget_krw'],500000)
        self.assertEqual(p['max_monthly_cost_krw'],50000)

    def test_skill_not_implicitly_required_tech(self):
        ctx={}
        d=turn(skill_level='INTERMEDIATE',preferred_tech_stack=['Python'],
               require_preferred_stack=True,
               evidence=[ev('skill_level','파이썬 중급'),
                         ev('preferred_tech_stack','파이썬 중급'),
                         ev('require_preferred_stack','파이썬 중급')])
        apply_recommendation_decision(d,'파이썬 중급',ctx)
        p=ctx['recommendation_intake']['profile']
        self.assertEqual(p['skill_level'],'INTERMEDIATE')
        self.assertNotIn('preferred_tech_stack',p)
        self.assertNotIn('require_preferred_stack',p)

    def test_unambiguous_combined_sentence(self):
        ctx={}
        message='수익용이고 예산 50만원, 개발 중급, 위험 낮게'
        d=turn(objective='수익 창출',max_budget_krw=500000,skill_level='INTERMEDIATE',
               risk_tolerance='LOW',evidence=[ev('objective','수익용'),
               ev('max_budget_krw','예산 50만원'),ev('skill_level','개발 중급'),
               ev('risk_tolerance','위험 낮게')])
        kind, payload=apply_recommendation_decision(d,message,ctx)
        self.assertEqual(kind,'ready')
        self.assertEqual(payload['args']['risk_tolerance'],'LOW')


class CRiskAssessmentTests(unittest.TestCase):
    def test_legacy_unverified_project_is_not_low_risk_recommendation(self):
        out=recommendation([listing(verification_status='UNVERIFIED')],prefs(),demo_only=False)
        self.assertEqual(out['eligible_count'],0)
        self.assertTrue(any('검사 자료' in r for r in out['excluded'][0]['reasons']))

    def test_low_risk_unknown_monthly_cost_under_cap_is_excluded(self):
        out=recommendation([listing(monthly_cost_estimate_krw=None)],
                           prefs(max_monthly_cost_krw=10000), demo_only=False)
        self.assertEqual(out['eligible_count'],0)
        self.assertIn('운영비 미확인',' '.join(out['excluded'][0]['reasons']))

    def test_low_risk_complex_stack_beyond_skill_is_excluded(self):
        out=recommendation([listing(tech_stack=['React','Kubernetes'],category='saas')],
                           prefs(skill_level='NONE'),demo_only=False)
        self.assertEqual(out['eligible_count'],0)
        self.assertTrue(any('복잡도' in r for r in out['excluded'][0]['reasons']))

    def test_low_risk_missing_rights_is_excluded(self):
        out=recommendation([listing(sale_rights_type=None)],prefs(),demo_only=False)
        self.assertEqual(out['eligible_count'],0)
        self.assertTrue(any('권리' in r for r in out['excluded'][0]['reasons']))

    def test_serious_known_defect_blocks_low_risk(self):
        out=recommendation([listing(known_defects=['관리자 키가 노출되어 있음'])],prefs(),demo_only=False)
        self.assertEqual(out['eligible_count'],0)

    def test_medium_risk_unknown_remains_visible_as_uncertain(self):
        out=recommendation([listing(verification_status='UNVERIFIED',
                                     monthly_cost_estimate_krw=None,sale_rights_type='')],
                           prefs(risk_tolerance='MEDIUM'),demo_only=False)
        self.assertEqual(out['eligible_count'],1)
        row=out['ranked'][0]
        self.assertEqual(row['risk_checks']['operations'],'UNKNOWN')
        self.assertGreater(row['uncertainty_count'],0)
        self.assertTrue(any('권리' in x for x in row['risks']))
        self.assertNotIn('검증 완료',str(row))

    def test_eligible_pool_never_contains_excluded_price(self):
        out=recommendation([listing('a'),listing('b',price_krw=900000)],
                           prefs(risk_tolerance='MEDIUM',qualitative_preferences=['관리 쉬움']),demo_only=False)
        self.assertEqual(len(out['candidate_pool']),1)
        self.assertEqual(out['candidate_pool'][0]['listing_id'],'a')
        self.assertEqual(out['qualitative_preferences'],['관리 쉬움'])


class BQualitativeRankingTests(unittest.TestCase):
    def setUp(self):
        self.listings = [listing('a',description='서버 운영과 배포를 직접 해야 합니다.'),
                         listing('b',description='관리 편의 기능과 자동화 기능이 제공됩니다.')]
        self.base = recommendation(self.listings,prefs(risk_tolerance='MEDIUM',
                    qualitative_preferences=['관리 편의']), demo_only=False)

    def test_documented_match_can_rerank_candidate(self):
        review = PreferenceReview.model_validate({'assessments':[{
            'listing_id':'b','preference':'관리 편의','verdict':'MATCH',
            'evidence_quote':'관리 편의 기능','explanation':'판매자가 관리 편의 기능을 표기했습니다.'}]})
        data = apply_qualitative_review(copy.deepcopy(self.base),review,['관리 편의'])
        self.assertEqual(data['ranked'][0]['listing_id'],'b')
        self.assertEqual(data['ranked'][0]['qualitative_adjustment'],10)
        self.assertEqual(data['qualitative_review_status'],'EVIDENCE_BASED')

    def test_unquoted_fabrication_cannot_increase_score(self):
        review = PreferenceReview.model_validate({'assessments':[{
            'listing_id':'b','preference':'관리 편의','verdict':'MATCH',
            'evidence_quote':'검증된 월 매출 500만원',
            'explanation':'수익 보장'}]})
        data=apply_qualitative_review(copy.deepcopy(self.base),review,['관리 편의'])
        self.assertEqual(data['qualitative_review_status'],'INSUFFICIENT_EVIDENCE')
        self.assertTrue(all(x['score']==x['base_score'] for x in data['ranked']))

    def test_unsupported_id_cannot_reappear(self):
        review=PreferenceReview.model_validate({'assessments':[{
            'listing_id':'excluded-id','preference':'관리 편의','verdict':'MATCH',
            'evidence_quote':'관리 편의 기능','explanation':'임의 항목'}]})
        data=apply_qualitative_review(copy.deepcopy(self.base),review,['관리 편의'])
        self.assertEqual(len(data['ranked']),2)
        self.assertNotIn('excluded-id',[x['listing_id'] for x in data['ranked']])

    def test_unknown_does_not_imply_positive_fit(self):
        review=PreferenceReview.model_validate({'assessments':[{
            'listing_id':'a','preference':'관리 편의','verdict':'UNKNOWN',
            'evidence_quote':'','explanation':'자료 없음'}]})
        data=apply_qualitative_review(copy.deepcopy(self.base),review,['관리 편의'])
        self.assertEqual(data['qualitative_review_status'],'INSUFFICIENT_EVIDENCE')
        self.assertTrue(all(x['qualitative_adjustment']==0 for x in data['ranked']))

    def test_hard_budget_risk_gate_cannot_be_overridden(self):
        base=recommendation([listing('a'),listing('b',price_krw=600000,
            description='관리 편의 기능')],prefs(risk_tolerance='MEDIUM'),demo_only=False)
        review=PreferenceReview.model_validate({'assessments':[{
            'listing_id':'b','preference':'관리 편의','verdict':'MATCH',
            'evidence_quote':'관리 편의 기능','explanation':'좋은 항목'}]})
        data=apply_qualitative_review(base,review,['관리 편의'])
        self.assertEqual([x['listing_id'] for x in data['ranked']], ['a'])

    def test_model_failure_keeps_rule_results_and_states_reason(self):
        class FailedModel:
            def with_structured_output(self,*args,**kwargs):
                raise RuntimeError('model unavailable')
        data=review_preferences_with_model(FailedModel(),copy.deepcopy(self.base),['관리 편의'])
        self.assertEqual(data['qualitative_review_status'],'MODEL_UNAVAILABLE')
        self.assertEqual(data['ranked'][0]['base_score'],data['ranked'][0]['score'])

    def test_no_qualitative_input_does_not_consume_llm_call(self):
        class FailIfCalled:
            def with_structured_output(self,*a,**kw):
                raise AssertionError('no need for LLM')
        data=review_preferences_with_model(FailIfCalled(),copy.deepcopy(self.base),[])
        self.assertEqual(data['qualitative_review_status'],'NOT_REQUESTED')


if __name__=='__main__':
    unittest.main()

class DIntegratedQualitativeToolFlow(unittest.TestCase):
    """The entire LLM intake -> dispatch -> optional preference LLM -> response path."""
    def test_chat_agent_applies_qualitative_review(self):
        from types import SimpleNamespace
        from agent.llm_intake import RecommendationTurn
        import agent.chat as chat
        from agent.tools import ToolEvent
        from tests.test_llm_routing_v012 import FakeMessages

        message='수익 목적, 예산 50만원, 개발 중급, 위험 보통이고 관리 편의가 중요해. 추천해줘'
        router = turn(objective='수익 창출',max_budget_krw=500000,
                      skill_level='INTERMEDIATE',risk_tolerance='MEDIUM',
                      qualitative_preferences=['관리 편의'],evidence=[
                          ev('objective','수익 목적'),ev('max_budget_krw','예산 50만원'),
                          ev('skill_level','개발 중급'),ev('risk_tolerance','위험 보통'),
                          ev('qualitative_preferences','관리 편의가 중요해')])
        review=PreferenceReview.model_validate({'assessments':[{
            'listing_id':'b','preference':'관리 편의','verdict':'MATCH',
            'evidence_quote':'관리 편의 기능','explanation':'판매자 설명에 관련 기능이 명시되어 있습니다.'}]})
        class Model:
            count=0
            def with_structured_output(self, schema, **opts):
                self.count+=1
                decision=router if schema is RecommendationTurn else review
                class Invoke:
                    def invoke(self, _messages):
                        return decision
                return Invoke()
            def invoke(self, _messages):
                return SimpleNamespace(content='판매자 공개 정보의 해석이며 검증은 아닙니다.')
        model=Model()
        base=recommendation([listing('a',description='서버를 직접 관리해야 합니다.'),
                             listing('b',description='관리 편의 기능이 제공됩니다.')],
                            prefs(risk_tolerance='MEDIUM'),demo_only=False)
        def dispatch(_dispatcher, name, args):
            self.assertEqual(name,'recommend_listings')
            self.assertEqual(args['qualitative_preferences'],['관리 편의'])
            data={**base, 'criteria':args, 'status':'SUCCEEDED'}
            return ToolEvent(name,'맞춤 추천',True,'기본 추천 완료',data),None
        with patch.dict(sys.modules,{'langchain_core.messages':FakeMessages()}), \
             patch.multiple(chat,ENABLE_OPENAI_CHAT=True,OPENAI_API_KEY='testing-only'), \
             patch.object(chat.ToolDispatcher,'invoke',autospec=True,side_effect=dispatch):
            ctx={}
            result=chat.ChatAgent('구매자 B',model_factory=lambda:model).reply(message,[],ctx)
        self.assertEqual(result['mode'],'openai_recommendation')
        self.assertEqual(result['events'][0]['data']['qualitative_review_status'],'EVIDENCE_BASED')
        self.assertEqual(result['events'][0]['data']['ranked'][0]['listing_id'],'b')
        self.assertEqual(ctx['recent_listings'][0]['id'],'b')
        self.assertGreaterEqual(model.count,2)
