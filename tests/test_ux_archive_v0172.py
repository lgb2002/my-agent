"""v0.17.2 non-network regression: conversations, consent storage, UX and security."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from core.chat_sessions import (get_or_migrate_session, init_archive, append_turn,
    start_conversation, open_conversation, remove_conversation, conversation_list)
from core.chat_archive_store import (save_conversation, load_conversation,
    list_conversations, delete_conversation)
from core.ux_actions import (suggested_actions, friendly_state,
                             tool_result_label, request_requires_account)
from core import workflow_store

ROOT = Path(__file__).resolve().parents[1]


class ArchiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.scope = 'live::test::visitor'
        self.legacy = {'turns': [], 'context':{'recent_listings': []}, 'pending':None}
        self.store = {}
        self.current = init_archive(self.store,self.scope,self.legacy)
        self.archive = self.store[self.scope]

    def test_migrates_old_session(self):
        self.assertIs(self.current,self.legacy)
        append_turn(self.current,'user','오래된 질문')
        self.assertEqual(conversation_list(self.archive)[0][1],'오래된 질문')

    def test_new_chat_keeps_old_transcript_and_context(self):
        append_turn(self.current,'user','첫 매물 검색')
        self.current['context']['recent_listings'] = [{'id':str(uuid.uuid4()),'title':'매물 A'}]
        previous_id=self.archive['active']
        created=start_conversation(self.archive)
        self.assertEqual(created['turns'],[])
        self.assertEqual(len(self.archive['items']),2)
        old=open_conversation(self.archive,previous_id)
        self.assertEqual(old['turns'][0]['content'],'첫 매물 검색')
        self.assertEqual(old['context']['recent_listings'][0]['title'],'매물 A')

    def test_switch_to_old_chat_never_restores_approval_nonce(self):
        self.current['pending']={'kind':'live_offer_draft','token':'unsafe'}
        cid=self.archive['active']
        start_conversation(self.archive)
        prior=open_conversation(self.archive,cid)
        self.assertIsNone(prior['pending'])

    def test_delete_active_opens_fresh_chat_and_does_not_affect_others(self):
        append_turn(self.current,'user','첫 채팅')
        original=self.archive['active']
        new=start_conversation(self.archive)
        append_turn(new,'user','두 번째 채팅')
        latest=self.archive['active']
        remove_conversation(self.archive, latest)
        self.assertNotIn(latest,self.archive['items'])
        self.assertEqual(len(self.archive['items']),2)
        self.assertIn(original,self.archive['items'])

    def test_one_scope_cannot_read_another_scope(self):
        other=init_archive(self.store,'live::test::someone_else',{'turns':[], 'context':{}, 'pending':None})
        append_turn(self.current,'user','비공개 질문')
        self.assertEqual(other['turns'],[])

    def test_no_turn_limit_or_fake_reset(self):
        for i in range(155):append_turn(self.current,'user',f'메시지 {i}')
        self.assertEqual(len(self.current['turns']),155)


class StoredArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db_override=patch.object(workflow_store,'LOCAL_DB', str(Path(self.tmp.name)/'archive.sqlite'))
        self.db_override.start()
        self.env_override=patch.dict(os.environ, {'AGENT_STATE_DATABASE_URL':''})
        self.env_override.start()
        self.alice='a'*64
        self.bob='b'*64
        self.cid=uuid.uuid4().hex

    def tearDown(self):
        self.env_override.stop()
        self.db_override.stop()
        self.tmp.cleanup()

    def test_opt_in_save_load_summary_without_pending(self):
        session={'turns':[{'role':'user','content':'예산 30만원', 'events':[]},
            {'role':'assistant','content':'공개 매물 2개 찾았어요','events':[
                {'name':'search_listings','label':'매물 검색','summary':'매물 2건',
                 'success':True,'data':{'secret':'private_api_payload'}}]}],
            'pending':{'token':'private-nonce'}, 'context':{'recent_listings':[{'secret':'private-data'}]}}
        save_conversation(self.alice,self.cid,session)
        restored=load_conversation(self.alice,self.cid)
        self.assertEqual(len(restored['turns']),2)
        self.assertNotIn('private_api_payload',json.dumps(restored))
        self.assertNotIn('private-nonce',json.dumps(restored))
        self.assertEqual(restored['context']['recent_listings'],[])
        self.assertIsNone(restored['pending'])
        self.assertEqual(restored['turns'][1]['events'][0]['summary'],'매물 2건')
        self.assertEqual(len(list_conversations(self.alice)),1)
        self.assertEqual(list_conversations(self.alice)[0]['title'],'예산 30만원')

    def test_owners_cannot_open_each_others_conversation(self):
        save_conversation(self.alice,self.cid,{'turns':[{'role':'user','content':'A 전용'}]})
        self.assertIsNone(load_conversation(self.bob,self.cid))
        self.assertEqual(list_conversations(self.bob),[])
        delete_conversation(self.bob,self.cid)
        self.assertIsNotNone(load_conversation(self.alice,self.cid))
        delete_conversation(self.alice,self.cid)
        self.assertIsNone(load_conversation(self.alice,self.cid))

    def test_rejects_invalid_owner_and_id(self):
        with self.assertRaises(ValueError):save_conversation('visitor-id',self.cid,{'turns':[]})
        with self.assertRaises(ValueError):save_conversation(self.alice,'../secrets',{'turns':[]})

    def test_refuses_sensitive_messages(self):
        with self.assertRaises(ValueError):
            save_conversation(self.alice,self.cid,
                {'turns':[{'role':'user','content':'my key sk-'+'a'*44}]})

    def test_large_conversation_rejected_without_silent_truncation(self):
        with self.assertRaises(ValueError):
            save_conversation(self.alice,self.cid,
                {'turns':[{'role':'assistant','content':'가'*6000} for i in range(120)]})


class UXActionsTests(unittest.TestCase):
    def test_no_private_shortcuts_without_account(self):
        labels=[x[0] for x in suggested_actions({}, authenticated=False,limit=6)]
        self.assertIn('매물 둘러보기',labels)
        self.assertNotIn('내 구매 조건',labels)
        self.assertNotIn('제안 내역',labels)

    def test_authenticated_actions_and_required_input(self):
        actions=suggested_actions({}, authenticated=True,limit=6)
        self.assertIn('내 구매 조건',[x[0] for x in actions])
        self.assertTrue(request_requires_account('내 제안 목록 보여줘'))
        self.assertFalse(request_requires_account('구매 제안이라는 게 뭐야?'))

    def test_relevant_listing_shortcuts_use_real_uuid(self):
        lid=str(uuid.uuid4())
        actions=suggested_actions({'recent_listings':[{'id':lid,'title':'A'}]},authenticated=True)
        self.assertIn(lid,dict(actions).get('1번 매물 검토',''))

    def test_invalid_listing_reference_not_used_in_shortcut(self):
        actions=suggested_actions({'recent_listings':[{'id':'bad','title':'A'}]})
        self.assertNotIn('1번 매물 검토',dict(actions))

    def test_tool_result_never_claims_trade_or_rights_verified(self):
        for name in ('prepare_offer','recommend_listings','inspect_listing','get_handover'):
            label=tool_result_label(name,True)
            self.assertNotIn('거래 완료',label)
            self.assertNotIn('실사 통과',label)
        self.assertIn('미제출',tool_result_label('prepare_offer',True))
        self.assertIn('실패',tool_result_label('search_listings',False))

    def test_states_are_korean_and_unknown_is_uncertain(self):
        self.assertIn('승인 대기',friendly_state('WAITING_APPROVAL'))
        self.assertIn('별도 확인',friendly_state('EXECUTED'))
        self.assertEqual(friendly_state('UNRECOGNIZED'),'상태 확인 필요')

    def test_app_integration_and_revised_welcome(self):
        src=(ROOT/'app.py').read_text(encoding='utf-8')
        ast.parse(src)
        for name in ('init_archive','start_conversation','open_conversation','remove_conversation',
                     'save_conversation','load_conversation','delete_conversation','st.form(',
                     'suggested_actions','friendly_state','request_requires_account',
                     'pending_ui(session, actor)'):
            self.assertIn(name,src)
        self.assertNotIn('st.container(height=540',src)
        self.assertNotIn('st.session_state["chat_sessions_v06"][scope] = {"turns": []',src)
        self.assertIn('실사에서 어떤 위험',src)

    def test_small_screen_css_guards(self):
        css=(ROOT/'assets/style.css').read_text(encoding='utf-8')
        for marker in ('@media (max-width:600px)','@media (max-width:375px)',
                       'overflow-x:auto',':focus-visible','prefers-reduced-motion'):
            self.assertIn(marker,css)


if __name__=='__main__': unittest.main()
