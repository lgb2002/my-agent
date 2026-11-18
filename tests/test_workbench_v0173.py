"""Workbench state, evidence and safety: no network, no paid model calls."""
import ast
import unittest
import uuid
from pathlib import Path
from core.workspace_state import workspace_view, profile_summary, focused_actions

ROOT=Path(__file__).resolve().parents[1]

def session(events=None, context=None, pending=None, *, text='요청'):
    turns=[{'role':'user','content':text}]
    if events is not None:
        turns.append({'role':'assistant','content':'도구 결과를 정리했어요','events':events})
    return {'turns':turns,'context':context or {},'pending':pending}

def event(name,data=None,success=True):
    e={'name':name,'label':'도구','success':success,'summary':'모의 응답'}
    if data is not None:e['data']=data
    return e

class WorkbenchProjection(unittest.TestCase):
    def test_initial_state_keeps_real_welcome(self):
        self.assertEqual(workspace_view({'turns':[],'context':{},'pending':None})['focus'],'welcome')

    def test_search_uses_current_response_only(self):
        ident=str(uuid.uuid4())
        s=session([event('search_listings',{'listings':[{'id':ident,'title':'자료 확인된 매물'}]})])
        result=workspace_view(s)
        self.assertEqual(result['focus'],'search')
        self.assertEqual(result['data']['listings'][0]['id'],ident)
        self.assertEqual(result['turn_index'],1)

    def test_recommendation_data_is_same_ranked_rows_not_invented(self):
        ident=str(uuid.uuid4())
        s=session([event('recommend_listings',{'ranked':[{'listing_id':ident,'title':'한 건만'}]})])
        r=workspace_view(s)
        self.assertEqual(r['focus'],'recommend')
        self.assertEqual(len(r['data']['ranked']),1)

    def test_compare_step_is_also_recommendation(self):
        s=session([event('compare',{'ranked':[],'requested':3})])
        self.assertEqual(workspace_view(s)['focus'],'recommend')

    def test_inspection_gets_distinct_surface(self):
        self.assertEqual(workspace_view(session([event('inspect_listing',{'report':{'findings':[]}})]))['focus'],'inspection')

    def test_in_progress_intake_takes_precedence_over_old_result(self):
        s=session([event('search_listings',{'listings':[]})],
                  {'recommendation_intake':{'profile':{'objective':'학습'}}})
        r=workspace_view(s)
        self.assertEqual(r['focus'],'intake')
        self.assertEqual(r['chips'],['목적 · 학습'])

    def test_confirmation_takes_precedence_over_everything(self):
        s=session([event('recommend_listings',{'ranked':[]})],
                  pending={'kind':'live_offer_draft','token':'private-nonce'})
        r=workspace_view(s)
        self.assertEqual(r['focus'],'offer')
        self.assertNotIn('private-nonce',str(r['data']))

    def test_waiting_offer_price_overrides_last_recommendation(self):
        s=session([event('recommend_listings',{'ranked':[]})],
                  {'workflow':{'status':'WAITING_OFFER_PRICE','steps':[]}})
        self.assertEqual(workspace_view(s)['focus'],'workflow')

    def test_sanitized_archive_never_masquerades_as_live_listing(self):
        s=session([event('recommend_listings')])
        r=workspace_view(s)
        self.assertEqual(r['focus'],'restored')
        self.assertEqual(r['data'],{})

    def test_filter_switch_marks_old_listing_snapshot_stale(self):
        r=workspace_view(session([event('search_listings',{'listings':[{'title':'old'}]})],
                                 {'_listing_snapshot_stale':True}))
        self.assertEqual(r['focus'],'stale')
        self.assertTrue(any('다시 조회' in label for label,_ in focused_actions(r,{},False)))

    def test_new_answer_after_filter_switch_is_visible(self):
        s=session([event('search_listings',{'listings':[{'title':'old'}]})],
                   {'_listing_snapshot_stale':True})
        s['turns'].extend([{'role':'user','content':'이제 뭐 하지? '},
                            {'role':'assistant','content':'새로운 조건으로 조회하는 것이 좋아요'}])
        r=workspace_view(s)
        self.assertEqual(r['focus'],'conversation')
        self.assertIsNone(r['previous_result'])

    def test_failed_latest_tool_does_not_show_previous_success(self):
        s=session([event('search_listings',{'listings':[{'title':'old'}]})])
        s['turns'].extend([{'role':'user','content':'다른 거'},
                            {'role':'assistant','content':'실패','events':[event('inspect_listing',{},False)]}])
        r=workspace_view(s)
        self.assertEqual(r['focus'],'error')
        self.assertEqual(r['data'],{})

    def test_newer_answer_overrides_outdated_visual_and_keeps_reference(self):
        s=session([event('recommend_listings',{'ranked':[{'title':'A'}]})])
        s['turns'].extend([{'role':'user','content':'이 중 뭐가 좋니'},
                            {'role':'assistant','content':'A는 인수하기 쉬운지 확인해야 해요'}])
        r=workspace_view(s)
        self.assertEqual(r['focus'],'conversation')
        self.assertEqual(r['previous_result'],'recommend')
        self.assertIn('A는',r['last_assistant'])

    def test_private_profile_not_filled_with_defaults(self):
        r=profile_summary({'preferred_tech_stack':['FastAPI'],'risk_tolerance':'LOW'})
        self.assertEqual(len(r),2)
        self.assertFalse(any('예산' in x for x in r))

    def test_profile_from_previous_confirmed_turn(self):
        s=session([], {'last_recommendation_profile':{'max_budget_krw':500000,'objective':'운영'}})
        r=workspace_view(s)
        self.assertIn('예산 · 500,000원 이하',r['chips'])

    def test_recommendation_action_uses_real_uuid(self):
        lid=str(uuid.uuid4())
        r=workspace_view(session([event('recommend_listings',{'ranked':[{'listing_id':lid}]})]))
        actions=focused_actions(r,{},False)
        self.assertIn(lid,actions[0][1])
        self.assertFalse(any('제안' in label for label,_ in actions))

    def test_malformed_id_never_becomes_review_action(self):
        r=workspace_view(session([event('recommend_listings',{'ranked':[{'listing_id':'1번'}]})]))
        actions=focused_actions(r,{},True)
        self.assertFalse(any('1번 매물의' in cmd or '1번 매물에' in cmd for _,cmd in actions))
        self.assertFalse(any('1순위 제안' in label for label,_ in actions))

    def test_search_pagination_not_claimed_without_cursor(self):
        lid=str(uuid.uuid4())
        r=workspace_view(session([event('search_listings',{'listings':[{'id':lid}]})]))
        self.assertFalse(any('다음 매물' in label for label,_ in focused_actions(r,{},False)))
        r['data']['next_cursor']=15
        self.assertTrue(any('다음 매물' in label for label,_ in focused_actions(r,{},False)))

    def test_code_renders_single_primary_surface_and_no_duplicate_history_table(self):
        src=(ROOT/'app.py').read_text(encoding='utf-8')
        ast.parse(src)
        for token in ('render_primary_workspace(workbench, session, actor)',
                      "with st.expander('대화 기록 · {}개 메시지",'show_search_workspace',
                      'show_inspection_workspace', 'show_recommendation_snapshot',
                      'pending_ui(session, actor)', 'st.chat_input', 'include_demo=show_demo'):
            self.assertIn(token,src)
        self.assertNotIn('st.container(height=540',src)
        self.assertIn('show_event(event, no, idx, render_detail=False)',src)

    def test_controls_use_existing_confirmation_and_authorization(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn('submit_confirmed_draft(pending)',app)
        self.assertIn("if pending.get('attempted')",app)
        self.assertIn("request_requires_account(submitted)",app)
        self.assertIn('set_ai_identity(ai_identity)',app)
        self.assertIn("st.session_state['queued_tool_prompt_v015']",app)

if __name__=='__main__': unittest.main()
