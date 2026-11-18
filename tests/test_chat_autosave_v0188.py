"""v0.18.8 contract: verified account auto-save, scoped deletion, chat-first UI."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from core import workflow_store
from core.chat_sessions import init_archive, append_turn
from core.chat_archive_store import (
    save_conversation, list_conversations, load_conversation, delete_all_conversations,
    chat_auto_save_enabled, set_chat_auto_save,
)
from core.chat_navigation import conversation_group, search_conversations, visible_conversations

ROOT = Path(__file__).resolve().parents[1]


class AutoSaveDefaultV0188(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.overrides = (
            patch.object(workflow_store, 'LOCAL_DB', str(Path(self.tmp.name)/'accounts.sqlite')),
            patch.dict(os.environ, {'AGENT_STATE_DATABASE_URL':''}),
        )
        for override in self.overrides: override.start()
        self.alice, self.bob = 'a'*64, 'b'*64

    def tearDown(self):
        for override in reversed(self.overrides): override.stop()
        self.tmp.cleanup()

    def test_old_disabled_setting_does_not_erase_saved_records(self):
        cid = '1'*32
        set_chat_auto_save(self.alice, False)  # legacy preference still exists
        save_conversation(self.alice, cid, {'turns':[{'role':'user','content':'기존 보관 대화'}]})
        self.assertFalse(chat_auto_save_enabled(self.alice))
        self.assertEqual(load_conversation(self.alice,cid)['turns'][0]['content'], '기존 보관 대화')
        # New default UI no longer reads old opt-in flag; no migration deletes data.
        self.assertNotIn('chat_auto_save_enabled(', (ROOT/'chat_ui.py').read_text(encoding='utf-8'))

    def test_bulk_delete_is_owner_scoped_and_keeps_other_tables(self):
        for owner in (self.alice,self.bob):
            for cid in ('1'*32,'2'*32):
                save_conversation(owner,cid,{'turns':[{'role':'user','content':owner[0]}]})
        workflow_store.save_preferences(self.alice, {'objective':'탐색','max_budget_krw':500000,'skill_level':'초급','risk_tolerance':'low'})
        delete_all_conversations(self.alice)
        self.assertEqual(list_conversations(self.alice), [])
        self.assertEqual(len(list_conversations(self.bob)), 2)
        self.assertEqual(workflow_store.load_preferences(self.alice)['max_budget_krw'],500000)

    def test_anonymous_owner_rejected_for_bulk_delete(self):
        with self.assertRaises(ValueError):
            delete_all_conversations('anonymous')

    def test_search_uses_titles_only_and_groups_korean_time(self):
        data=[{'title':'30만원 Python 매물', 'id':'1'},
              {'title':'React 사업 비교', 'id':'2'}]
        self.assertEqual([r['id'] for r in search_conversations(data, 'PYTHON')], ['1'])
        self.assertEqual(search_conversations(data,''),data)
        self.assertEqual(search_conversations(data,'auth_secret'),[])
        now=datetime(2026,11,18,0,30,tzinfo=timezone.utc) # 09:30 KST
        self.assertEqual(conversation_group('2026-11-17T23:50:00+00:00',now=now),'오늘')
        self.assertEqual(conversation_group('2026-11-16T06:00:00+00:00',now=now),'지난 7일')
        self.assertEqual(conversation_group('2026-01-01T06:00:00+00:00',now=now),'이전 대화')

    def test_chat_first_uses_real_input_and_hides_storage_switch_and_dev_tools(self):
        code=(ROOT/'chat_ui.py').read_text(encoding='utf-8')
        css=(ROOT/'assets/style.css').read_text(encoding='utf-8')
        self.assertIn("welcome_input = st.chat_input(",code)
        self.assertIn("with st.container(key='welcome_input_v0188')",code)
        self.assertIn("with account_panel:",code)
        self.assertIn("with chat_panel:",code)
        self.assertIn("st.text_input('대화 검색'",code)
        self.assertIn('save_conversation(cloud_owner',code)
        self.assertNotIn("st.toggle('Supabase에 자동 저장'",code)
        self.assertNotIn("st.popover('사용 가능한 도구",code)
        self.assertIn('delete_all_conversations(cloud_owner)',code)
        self.assertIn('st-key-welcome_input_v0188',css)


if __name__=='__main__':unittest.main()
