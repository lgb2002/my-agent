"""UI A/B/C invariants, unit-tested without Streamlit/browser/network."""
import ast
import unittest
import uuid
from pathlib import Path

from core.ui_presentation import workflow_view, recommendation_view

ROOT = Path(__file__).resolve().parents[1]


def plan(statuses, state='PARTIAL', verified=None):
    return {'status': state,
            'steps':[{'key':f'part{i}', 'label':f'단계 {i}', 'status':s, 'note':''} for i,s in enumerate(statuses)],
            'verified': verified or {}}


class WorkspacePresentationTests(unittest.TestCase):
    def test_only_completed_counts_as_completed(self):
        x=workflow_view(plan(['COMPLETED','PARTIAL','BLOCKED','WAITING_APPROVAL','SKIPPED']))
        self.assertEqual((x['completed'],x['total'],x['outstanding']), (1,5,4))
        self.assertAlmostEqual(x['fraction'],.2)
        self.assertEqual(x['blocked'],1)
        self.assertEqual(x['partial'],1)
        self.assertEqual(x['waiting_approval'],1)
        self.assertEqual(x['skipped'],1)

    def test_all_approval_pending_is_never_full_progress(self):
        x=workflow_view(plan(['WAITING_APPROVAL']*3,state='WAITING_APPROVAL'))
        self.assertEqual(x['completed'],0)
        self.assertEqual(x['fraction'],0)
        self.assertIn('플랫폼 웹',x['next_action'])

    def test_partial_with_no_more_pending_does_not_claim_done(self):
        x=workflow_view(plan(['COMPLETED','PARTIAL','COMPLETED'],state='PARTIAL'))
        self.assertEqual(x['completed'],2)
        self.assertIn('충족되지',x['next_action'])

    def test_completion_does_not_mean_transaction_settlement(self):
        x=workflow_view(plan(['COMPLETED','COMPLETED'],state='COMPLETED',verified={'fulfilled':True}))
        self.assertEqual(x['fraction'],1)
        self.assertIn('별도 확인',x['next_action'])

    def test_empty_plan_never_divides_by_zero(self):
        x=workflow_view({'steps':[],'status':'ACTIVE'})
        self.assertEqual((x['total'],x['fraction']),(0,0.0))

    def test_offer_price_wait_never_uses_budget_as_actual_offer(self):
        p=plan(['COMPLETED','WAITING_INPUT'],state='WAITING_OFFER_PRICE')
        p['steps'][1]['key']='prepare_offer'
        x=workflow_view(p)
        self.assertIn('구매 예산이 아닌',x['next_action'])

    def test_comparison_uses_existing_rank_and_source_fields_only(self):
        a=str(uuid.uuid4());b=str(uuid.uuid4())
        x=recommendation_view({'eligible_count':2,'ranked':[
            {'listing_id':a,'title':'서비스 A','price_krw':350000, 'reasons':['Python 활용'], 'risks':['운영비 미확인'], 'score':70},
            {'listing_id':b,'title':'서비스 B','price_krw':420000, 'reasons':['운영 부담 낮음'], 'risks':['권리 미확인'], 'score':68},
        ]})
        self.assertEqual(len(x['comparison']),2)
        self.assertEqual([c['listing_id'] for c in x['cards']],[a,b])
        self.assertEqual(x['comparison'][0]['가격'],'350,000원')
        self.assertIn('운영비 미확인',x['comparison'][0]['확인할 점'])

    def test_missing_evidence_not_claimed_safe(self):
        x=recommendation_view({'ranked':[{'title':'데이터 부족','price_krw':None,'reasons':[], 'risks':[], 'risk_label':'검증 부족','uncertainty_count':5}]})
        row=x['cards'][0]
        self.assertEqual(row['price'],'가격 미확인')
        self.assertIn('확인 필요',row['reason'])
        self.assertEqual(row['unverified'],5)
        self.assertEqual(row['risk_label'],'검증 부족')

    def test_compares_at_most_three_without_inventing_rows(self):
        x=recommendation_view({'ranked':[{'title':str(i)} for i in range(6)],'eligible_count':6})
        self.assertEqual(len(x['cards']),3)
        self.assertEqual(x['eligible'],6)

    def test_qualitative_evidence_separated_from_score(self):
        x=recommendation_view({'ranked':[{'title':'A','score':85,'base_score':75,'qualitative_adjustment':10,
            'qualitative_assessments':[{'preference':'운영 간편','verdict':'MATCH','evidence_quote':'월 1시간 운영'}]}]})
        self.assertEqual(x['cards'][0]['assessments'][0]['evidence_quote'],'월 1시간 운영')
        self.assertEqual(x['cards'][0]['base_score'],75)
        self.assertEqual(x['cards'][0]['score'],85)

    def test_no_nested_scroll_and_expander_first_step(self):
        src=(ROOT/'app.py').read_text(encoding='utf-8')
        ast.parse(src)
        self.assertNotIn('st.container(height=540',src)
        self.assertIn("with st.expander('작업 단계 및 상세 확인', expanded=False):",src)
        self.assertIn("show_recommendation_snapshot(event.get('data') or {}, idx, turn_id)",src)
        self.assertIn("st.table(view['comparison'])",src)
        self.assertIn('pending_ui(session, actor)',src)

    def test_tool_and_confirmation_safety_still_present(self):
        src=(ROOT/'app.py').read_text(encoding='utf-8')
        for text in ('submit_confirmed_draft', 'check_action_status',
                     'set_ai_identity(ai_identity)', 'include_demo=show_demo',
                     '검토', 'st.chat_input'):
            self.assertIn(text,src)
        self.assertNotIn('from services import demo_marketplace',src)


if __name__=='__main__': unittest.main()
