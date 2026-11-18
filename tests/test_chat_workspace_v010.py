"""Regression tests for the production sidebar and complete conversation history."""
import ast
import unittest
from pathlib import Path

from core.chat_sessions import append_turn, conversation_scope, get_or_migrate_session

ROOT = Path(__file__).resolve().parents[1]


class ChatWorkspaceV010Tests(unittest.TestCase):
    def test_full_history_survives_far_beyond_previous_eighty_turn_limit(self):
        session = {'turns': [], 'context': {}, 'pending': None}
        for n in range(150):
            append_turn(session, 'user', '메시지 {}'.format(n))
        self.assertEqual(len(session['turns']), 150)
        self.assertEqual(session['turns'][0]['content'], '메시지 0')
        self.assertEqual(session['turns'][-1]['content'], '메시지 149')

    def test_listing_filter_does_not_change_conversation_identity(self):
        scope = conversation_scope('live', 'ProjectAgain 사용자', 'browser-owner')
        store = {}
        session = get_or_migrate_session(store, scope)
        append_turn(session, 'user', '첫 메시지')
        self.assertIs(get_or_migrate_session(store, scope), session)
        self.assertEqual(session['turns'][0]['content'], '첫 메시지')

    def test_migrates_old_filtered_session_without_erasing_history(self):
        scope = conversation_scope('live', 'ProjectAgain 사용자', 'browser-owner')
        old = scope + '::True'
        historical = {'turns':[{'role':'user','content':'예전 채팅'}], 'context':{},'pending':None}
        store={old:historical}
        migrated=get_or_migrate_session(store,scope,[old,scope+'::False'])
        self.assertIs(migrated,historical)
        self.assertNotIn(old,store)

    def test_ui_default_demo_and_scrollable_native_chat(self):
        source=(ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn("st.checkbox('시연 매물 포함'", source)
        self.assertIn('include_demo_setting_v0189', source)
        self.assertIn('set_request_context(token=token, visitor_id=visitor, include_demo=show_demo)',source)
        self.assertNotIn('st.container(height=540',source)
        self.assertIn("for i, turn in enumerate(session['turns']):",source)
        self.assertIn('pending_ui(session, actor)',source)
        self.assertIn("for i, turn in enumerate(session['turns']):",source)
        self.assertNotIn('if SHOW_DEVELOPER_TOOLS:',source)
        self.assertIn('previous_filter != show_demo',source)
        self.assertNotIn('session["turns"][-80:]',source)

    def test_developer_diagnostics_removed_from_main_sidebar(self):
        config=(ROOT/'core/config.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('SHOW_DEVELOPER_TOOLS', 'false')",config)
        source=(ROOT/'app.py').read_text(encoding='utf-8')
        for label in ('API 연결 진단', '로그인 저장소 오류 진단', 'DB 연결 진단 실행'):
            self.assertNotIn(label,source)
        self.assertIn('사용 가능한 도구 · {}개',source)

    def test_document_captures_core_information_design_principles(self):
        doc=(ROOT/'DESIGN.md').read_text(encoding='utf-8')
        for principle in ('대화','우선순위','점진적 공개','사용자 통제','미검증'):
            self.assertIn(principle,doc)


if __name__=='__main__':
    unittest.main()
