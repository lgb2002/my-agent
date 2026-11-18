"""Regression tests for v0.18.9 compact shell and ephemeral attachment privacy."""
import ast
import unittest
from pathlib import Path

from core.chat_attachments import MAX_ZIP_BYTES, stored_zip_bytes, zip_record

ROOT=Path(__file__).resolve().parents[1]


class CompactShellV0189(unittest.TestCase):
    def test_zip_requires_explicit_scan_button_and_correct_conversation(self):
        record=zip_record('owner::1','conversation-A',b'ZIP-BYTES')
        self.assertIsNone(stored_zip_bytes(record,'owner::1','conversation-A'))
        self.assertEqual(stored_zip_bytes(record,'owner::1','conversation-A',require_armed=False),b'ZIP-BYTES')
        self.assertIsNone(stored_zip_bytes(record,'owner::1','conversation-B',require_armed=False))
        self.assertIsNone(stored_zip_bytes(record,'other-owner','conversation-A',require_armed=False))
        armed=zip_record('owner::1','conversation-A',b'ZIP-BYTES',armed=True)
        self.assertEqual(stored_zip_bytes(armed,'owner::1','conversation-A'),b'ZIP-BYTES')
        self.assertIsNone(stored_zip_bytes(armed,'owner::1','conversation-B'))

    def test_zip_invalid_or_oversize_rejected(self):
        for data in ('not-bytes',b'',b'X'*(MAX_ZIP_BYTES+1)):
            with self.subTest(data_type=type(data).__name__,length=len(data)):
                with self.assertRaises(ValueError):
                    zip_record('owner','conversation-A',data)
        self.assertIsNone(stored_zip_bytes({'scope':'o','conversation_id':'c','data':b'bad','armed':'True'},'o','c'))

    def test_native_modal_secondary_controls_and_account_approval_preserved(self):
        app=(ROOT/'chat_ui.py').read_text(encoding='utf8')
        ast.parse(app)
        self.assertIn("@st.dialog('ProjectAgain 설정'",app)
        for text in ('전체 대화 삭제', '시연 매물 포함', '확인한 조건과 작업 계획 저장',
                     '검사할 ZIP 선택', '로그아웃', '사용 가능한 도구'):
            self.assertIn(text,app)
        for old in ("with st.expander('매물 표시 설정'", "with st.expander('저장한 조건 · 작업'",
                    'with st.popover(\'대화 관리\')', 'with st.expander("ZIP 검사 · 도구"'):
            self.assertNotIn(old,app)
        self.assertIn('delete_all_conversations(cloud_owner)',app)
        self.assertIn('revoke_access(token, platform_issuer',app)
        self.assertIn('client.logout(record)',app)
        self.assertIn('store.clear(binding)',app)
        self.assertIn("st.session_state['pending_zip_v0189'] = zip_record(",app)
        self.assertIn('saved = st.session_state.get(\'pending_zip_v0189\')',app)
        self.assertIn('stored_zip_bytes(saved, scope, conversation_id)',app)
        self.assertIn('submit_confirmed_draft(pending)',app)
        self.assertIn('request_requires_account(submitted)',app)

    def test_compact_welcome_and_sidebar_are_conversational(self):
        app=(ROOT/'chat_ui.py').read_text(encoding='utf8')
        css=(ROOT/'assets/style.css').read_text(encoding='utf8')
        self.assertIn("quick_cols = st.columns(4",app)
        self.assertIn("st.chat_input('예: 50만원 이하 Python 프로젝트를 추천해줘'",app)
        self.assertIn("key='sidebar_recent_v0189'",app)
        self.assertNotIn("with st.container(key='sidebar_shortcuts_v0189')",app)
        self.assertIn("with st.popover('내 계정'",app)
        self.assertIn('open_settings_v0189',app)
        self.assertIn('.st-key-sidebar_recent_v0189',css)
        self.assertIn('.st-key-welcome_actions',css)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',css)
        self.assertIn('prefers-reduced-motion',css)

    def test_persist_consent_not_lost_when_dialog_closes(self):
        app=(ROOT/'chat_ui.py').read_text(encoding='utf8')
        self.assertIn('remember_workflow_setting_v0189_',app)
        self.assertIn("current['context']['_persist_owner'] = pref_owner",app)
        self.assertIn("permanent_consent_key not in st.session_state",app)
        self.assertIn('on_change=lambda: st.session_state.__setitem__(consent_key',app)

if __name__=='__main__': unittest.main()
