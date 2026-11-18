"""Cloud history integration guardrails; offline DB + static UX checks."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from core import workflow_store
from core.chat_sessions import init_archive, append_turn, start_conversation
from core.chat_navigation import visible_conversations, transcript_fingerprint
from core.chat_archive_store import (
    chat_auto_save_enabled, set_chat_auto_save, save_conversation,
    list_conversations, load_conversation, delete_conversation,
)

ROOT = Path(__file__).resolve().parents[1]


class CloudChatSettingsV0187(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_override = patch.object(workflow_store,'LOCAL_DB',str(Path(self.tmp.name)/'chat.sqlite'))
        self.db_override.start()
        self.env = patch.dict(os.environ, {'AGENT_STATE_DATABASE_URL':''})
        self.env.start()
        self.alice, self.bob = 'a'*64,'b'*64

    def tearDown(self):
        self.env.stop()
        self.db_override.stop()
        self.tmp.cleanup()

    def test_auto_save_requires_opt_in_and_is_per_user(self):
        self.assertFalse(chat_auto_save_enabled(self.alice))
        self.assertFalse(chat_auto_save_enabled(self.bob))
        set_chat_auto_save(self.alice,True)
        self.assertTrue(chat_auto_save_enabled(self.alice))
        self.assertFalse(chat_auto_save_enabled(self.bob))
        set_chat_auto_save(self.alice,False)
        self.assertFalse(chat_auto_save_enabled(self.alice))

    def test_invalid_principal_or_non_bool_rejected(self):
        with self.assertRaises(ValueError):chat_auto_save_enabled('visitor')
        with self.assertRaises(ValueError):set_chat_auto_save('visitor',True)
        with self.assertRaises(TypeError):set_chat_auto_save(self.alice,'yes')

    def test_deleting_cloud_chat_keeps_another_users_record(self):
        cid = uuid.uuid4().hex
        save_conversation(self.alice,cid,{'turns':[{'role':'user','content':'계정 A'}]})
        save_conversation(self.bob,cid,{'turns':[{'role':'user','content':'계정 B'}]})
        delete_conversation(self.alice,cid)
        self.assertIsNone(load_conversation(self.alice,cid))
        self.assertEqual(load_conversation(self.bob,cid)['turns'][0]['content'],'계정 B')

    def test_saved_chat_never_restores_approval_or_raw_payload(self):
        cid = uuid.uuid4().hex
        save_conversation(self.alice,cid,{'turns':[{'role':'user','content':'예산 30만원'},
            {'role':'assistant','content':'매물 설명','events':[{'name':'search_listings','label':'검색',
                'summary':'조회 성공','data':{'payload':'private'}}]}],
                'pending':{'token':'nonce'},'context':{'attachment_bytes':b'secret'}})
        data = load_conversation(self.alice,cid)
        self.assertEqual(data['context']['recent_listings'],[])
        self.assertIsNone(data['pending'])
        self.assertNotIn('data',data['turns'][1]['events'][0])


class NavigationV0187(unittest.TestCase):
    def archive(self):
        store={}
        initial={'turns':[],'context':{'recent_listings':[]},'pending':None}
        init_archive(store,'scope',initial)
        return store['scope']

    def test_recent_rows_include_remote_without_duplicating_local(self):
        archive=self.archive()
        first=archive['active']
        append_turn(archive['items'][first],'user','매물 찾기')
        cloud=[{'id':first,'title':'옛 제목','updated_at':'2026-11-18 02:00:00'},
               {'id':'b'*32,'title':'다른 대화','updated_at':'2099-11-18 03:00:00'}]
        rows=visible_conversations(archive,cloud)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['title'],'다른 대화')
        self.assertEqual(next(r for r in rows if r['id']==first)['title'],'매물 찾기')
        self.assertFalse(rows[0]['local'])
        self.assertEqual(archive['items'][first]['turns'][0]['content'],'매물 찾기')

    def test_new_chat_remains_separate_and_empty_drafts_not_listed(self):
        archive=self.archive()
        old=archive['active']
        append_turn(archive['items'][old],'user','첫 대화')
        start_conversation(archive)
        start_conversation(archive)
        rows=visible_conversations(archive)
        self.assertEqual(len(rows),2)
        self.assertIn(old,[r['id'] for r in rows])

    def test_fingerprint_ignores_private_workflow_or_payload(self):
        session={'turns':[{'role':'assistant','content':'응답','events':[
            {'name':'search','summary':'완료','success':True,'data':{'secret':'X'}}]}],
            'pending':{'token':'PRIVATE'}}
        fingerprint=transcript_fingerprint(session)
        session['pending']={'token':'DIFFERENT'}
        session['turns'][0]['events'][0]['data']['secret']='Y'
        self.assertEqual(fingerprint,transcript_fingerprint(session))
        session['turns'][0]['content']='새로운 응답'
        self.assertNotEqual(fingerprint,transcript_fingerprint(session))

    def test_ui_hides_diagnostics_and_reduces_duplicate_menus(self):
        app=(ROOT/'app.py').read_text('utf-8')
        css=(ROOT/'assets/style.css').read_text('utf-8')
        self.assertNotIn("with st.expander('대화 보관함",app)
        self.assertNotIn("with st.expander('대화 장기 보관",app)
        self.assertNotIn('DB 연결 진단 실행',app)
        self.assertIn("st.toggle('Supabase에 자동 저장'",app)
        self.assertIn("st.button('⋯', key='chat_more_v0187_'",app)
        self.assertIn('with st.container(key=\'welcome_tile_\'',app)
        self.assertIn('border:1px solid var(--line-strong)',css)

if __name__=='__main__':unittest.main()
