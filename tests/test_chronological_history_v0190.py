"""v0.19.0: historical evidence is safe, chronological, account scoped, non-actionable."""
import ast
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from core import workflow_store
from core.chat_archive_store import save_conversation, load_conversation, list_conversations, _sanitize
from core.chat_history_snapshot import capture_event, refresh_prompt
from core.chat_sessions import append_turn, conversation_title
from core.chat_navigation import transcript_fingerprint

ROOT = Path(__file__).resolve().parents[1]


class StoredResultSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.overrides=(patch.object(workflow_store,'LOCAL_DB',str(Path(self.tmp.name)/'db.sqlite')),
                        patch.dict(os.environ,{'AGENT_STATE_DATABASE_URL':''}))
        for item in self.overrides: item.start()
        self.owner='a'*64
        self.other='b'*64
        self.cid=uuid.uuid4().hex

    def tearDown(self):
        for item in reversed(self.overrides): item.stop()
        self.tmp.cleanup()

    def test_search_event_roundtrip_keeps_public_listing_and_timestamp(self):
        session={'turns':[], 'context':{'pending':{'token':'DO-NOT-SAVE'}},'pending':{'token':'DO-NOT-SAVE'}}
        append_turn(session,'user','파이썬 매물 보여줘')
        append_turn(session,'assistant','현재 매물 두 건입니다.',events=[{
            'name':'search_listings','label':'매물 검색','summary':'조회 2건','success':True,
            'data':{'query':'파이썬','listings':[{'id':str(uuid.uuid4()),'title':'실제 매물',
                    'price_krw':230000,'description':'설명','seller_email':'no@no.net',
                    'access_token':'secret-value'}], 'next_cursor':15,
                    'session_proof':'secret-value'}}])
        save_conversation(self.owner,self.cid,session)
        loaded=load_conversation(self.owner,self.cid)
        event=loaded['turns'][1]['events'][0]
        self.assertEqual(event['data']['listings'][0]['price_krw'],230000)
        self.assertEqual(event['data']['query'],'파이썬')
        self.assertEqual(event['data']['next_cursor'],15)
        self.assertIn('captured_at',event)
        self.assertTrue(event['historical'])
        self.assertNotIn('seller_email',event['data']['listings'][0])
        self.assertNotIn('session_proof',event['data'])
        self.assertNotIn('DO-NOT-SAVE',str(loaded))
        self.assertIsNone(loaded['pending'])
        self.assertEqual(loaded['context']['recent_listings'][0]['title'],'실제 매물')
        self.assertTrue(loaded['context']['_listing_snapshot_stale'])
        self.assertNotIn('listing_next_cursor',loaded['context'])
        self.assertEqual(refresh_prompt(event),'현재 플랫폼에서 파이썬 매물을 새로 검색해줘')

    def test_recommendation_evidence_is_bounded_and_credentials_removed(self):
        ident=str(uuid.uuid4())
        event=capture_event({'name':'recommend_listings','success':True,'summary':'추천',
            'data':{'ranked':[{'listing_id':ident,'title':'후보','price_krw':300000,
                'reasons':['구조 양호'],'risks':['운영비 미확인'],'risk_label':'확인 필요',
                'risk_dimensions':[{'label':'검증','status':'UNVERIFIED','explanation':'자료 부족',
                                    'secret':'never'}], 'bearer':'credential'}],
                    'criteria':{'max_budget_krw':500000,'risk_tolerance':'LOW','secret':'bad'},
                    'private_payload':'never'}},captured_at='2026-11-18T04:00:00+00:00')
        self.assertEqual(event['data']['ranked'][0]['reasons'],['구조 양호'])
        self.assertNotIn('private_payload',event['data'])
        self.assertNotIn('bearer',event['data']['ranked'][0])
        self.assertNotIn('secret',str(event))
        self.assertIn('추천',refresh_prompt(event))
        self.assertNotIn('제안',refresh_prompt(event))

    def test_unauthorized_or_mutating_events_have_no_replay_data(self):
        for name in ('prepare_offer','unknown_tool'):
            event=capture_event({'name':name,'success':True,
                                 'data':{'token':'secret','principal_id':'private'}})
            self.assertNotIn('data',event)
            self.assertIsNone(refresh_prompt(event))
        for owner in ('bad_owner',self.other):
            if owner=='bad_owner':
                with self.assertRaises(ValueError): load_conversation(owner,self.cid)
            else:
                self.assertIsNone(load_conversation(owner,self.cid))

    def test_existing_legacy_v1_history_still_opens(self):
        session={'turns':[{'role':'user','content':'기존 대화'},
                          {'role':'assistant','content':'기존 답변','events':[{
                           'name':'search_listings','label':'매물 검색','summary':'조회','success':True}]}]}
        save_conversation(self.owner,self.cid,session)
        loaded=load_conversation(self.owner,self.cid)
        self.assertEqual([x['content'] for x in loaded['turns']],['기존 대화','기존 답변'])
        self.assertNotIn('data',loaded['turns'][1]['events'][0])

    def test_title_avoids_greetings_and_fingerprint_tracks_results(self):
        base={'turns':[{'role':'user','content':'안녕'},
                       {'role':'assistant','content':'안녕!'},
                       {'role':'user','content':'50만원 이하 프로젝트를 추천해줘'}]}
        self.assertIn('50만원',conversation_title(base))
        base['turns'].append({'role':'assistant','content':'조회','events':[{'name':'search_listings',
             'success':True,'data':{'listings':[{'title':'A'}]}}]})
        before=transcript_fingerprint(base)
        base['turns'][-1]['events'][0]['data']['listings'][0]['title']='B'
        self.assertNotEqual(transcript_fingerprint(base),before)

    def test_ui_is_main_chronological_chat_and_keeps_safe_approval(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        css=(ROOT/'assets/style.css').read_text(encoding='utf-8')
        ast.parse(app)
        self.assertIn('for i, turn in enumerate(visible_turns, start=offset):',app)
        self.assertNotIn("with st.expander('대화 기록 ·",app)
        self.assertNotIn('대화 문장만 불러왔어요.',app)
        self.assertNotIn('render_primary_workspace(workbench, session, actor)',app)
        self.assertIn('if session.get(\'pending\'):',app)
        self.assertIn('pending_ui(session, actor)',app)
        self.assertIn('현재 가격·거래 상태가 아닙니다.',app)
        self.assertIn('계정 · 설정 ▾',app)
        self.assertNotIn("with st.container(key='sidebar_shortcuts_v0189')",app)
        self.assertIn('inline_zip_v0190',app)
        self.assertIn('다른 계정으로 로그인',app)
        self.assertIn('ProjectAgain 회원가입',app)
        self.assertIn('min-height:0;flex:1 1 auto',css)
        self.assertIn('st-key-conversation_history_v0174',css)


if __name__=='__main__': unittest.main()
