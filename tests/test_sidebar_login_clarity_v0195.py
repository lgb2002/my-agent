"""No decorative text before authentication; high-contrast login stays scoped."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class LoginClarityV0195Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'chat_ui.py').read_text(encoding='utf-8')
        cls.css = (ROOT / 'assets/style.css').read_text(encoding='utf-8')

    def test_streamlit_script_still_parses(self):
        ast.parse(self.source)

    def test_redundant_logged_out_captions_removed(self):
        for obsolete in (
            '로그인 전 대화는 이 브라우저에서만 유지돼요.',
            'ProjectAgain 로그인 후 필요한 권한을 안전하게 연결할 수 있어요.',
            '대화는 로그인 후 계정에 저장돼요.',
            '공개 매물 조회는 로그인 없이 사용할 수 있어요.',
            'ProjectAgain 계정 연결이 필요해요.',
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, self.source)

    def test_both_login_strategies_still_available(self):
        # No auto-login, no bypassing broker consent or signed identity validation.
        for marker in (
            "key='broker_native_login'", "key='oidc_login_v018'",
            'st.login()', "st.link_button('ProjectAgain으로 시작하기'",
            'store.lookup_identity(binding)', 'set_broker_access_handler(ensure_fresh)',
            'login.owner_key if connected and login', 'st.session_state',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        self.assertEqual(self.source.count("with st.container(key='sidebar_login_action_v0195')"), 4)

    def test_login_only_css_contrast_no_broad_button_override(self):
        block = self.css.split('/* v0.19.5 — high-contrast login-only action', 1)[1]
        self.assertIn('st-key-sidebar_login_action_v0195', block)
        self.assertIn('stLinkButton', block)
        self.assertIn('stButton', block)
        self.assertIn('background:#295447 !important', block)
        self.assertIn('color:#FFFFFF !important', block)
        self.assertIn('background:#1E4035 !important', block)
        self.assertIn('focus-visible', block)
        self.assertIn('min-height:44px !important', block)
        self.assertNotIn('st-key-chat_nav_row_v0187_', block)
        self.assertNotIn('st-key-primary_workbench', block)

    def test_no_auth_entry_or_durable_data_changes(self):
        for filename in ('app.py','unified_entry.py','core/unified_web.py',
                         'core/unified_login.py','core/oauth_broker.py',
                         'core/chat_archive_store.py'):
            self.assertTrue((ROOT / filename).exists())
        self.assertFalse((ROOT / '.streamlit/secrets.toml').exists())

if __name__ == '__main__':
    unittest.main()
