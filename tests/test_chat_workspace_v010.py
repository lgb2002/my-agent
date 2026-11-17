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
        self.assertIn('st.checkbox("시연 매물 포함", value=True, key="include_demo_v10")', source)
        self.assertIn('set_request_context(token=token, visitor_id=visitor, include_demo=show_demo)',source)
        self.assertNotIn('st.container(height=540',source)
        self.assertIn("for i, turn in enumerate(session['turns']):",source)
        self.assertIn('pending_ui(session, actor)',source)
        self.assertIn("for i, turn in enumerate(session['turns']):",source)
        self.assertIn('if SHOW_DEVELOPER_TOOLS:',source)
        self.assertIn('previous_filter != show_demo',source)
        self.assertNotIn('session["turns"][-80:]',source)

    def test_developer_ui_off_by_default_and_hidden_from_public_ui(self):
        config=(ROOT/'core/config.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('SHOW_DEVELOPER_TOOLS', 'false')",config)
        source=(ROOT/'app.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        developer_block=next(node for node in ast.walk(tree)
            if isinstance(node,ast.If) and isinstance(node.test,ast.Name) and node.test.id=='SHOW_DEVELOPER_TOOLS')
        block_text=ast.get_source_segment(source,developer_block)
        for label in ('최근 작업','대화 기록 저장','API 연결 진단','OpenAI 상태'):
            self.assertIn(label,block_text)
        # The general tool list is now user-facing; it must not be gated.
        self.assertIn('사용 가능한 도구 · {}개', source)
        self.assertNotIn('사용 가능한 도구', block_text)

    def test_document_captures_core_information_design_principles(self):
        doc=(ROOT/'DESIGN.md').read_text(encoding='utf-8')
        for principle in ('대화','우선순위','점진적 공개','사용자 통제','미검증'):
            self.assertIn(principle,doc)


if __name__=='__main__':
    unittest.main()
