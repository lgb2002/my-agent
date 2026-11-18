"""v0.19.2 presentation-only changes; auth and ownership stay protected."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SidebarV0192Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=(ROOT/'app.py').read_text(encoding='utf8')
        cls.css=(ROOT/'assets/style.css').read_text(encoding='utf8')

    def test_simple_actions_replace_large_cta(self):
        tree=ast.parse(self.app)
        self.assertIn("with st.container(key='sidebar_primary_actions_v0192')",self.app)
        self.assertIn("st.button('새 대화', icon=':material/edit_square:', type='tertiary'",self.app)
        self.assertIn("on_click=_request_new_conversation",self.app)
        self.assertIn("st.button('대화 검색', icon=':material/search:', type='tertiary'",self.app)
        self.assertIn("st.session_state.get('chat_search_open_v0192', False)",self.app)
        self.assertIn("if st.session_state.get('chat_search_open_v0192', False):",self.app)
        self.assertNotIn("st.button('＋ 새 대화', type='primary'",self.app)
        self.assertNotIn("with st.popover('계정 · 설정 ▾'",self.app)

    def test_account_actions_are_visible_via_one_footer_popover(self):
        self.assertIn("with st.popover('내 계정', icon=':material/account_circle:'",self.app)
        for key in ('account_switch_v0190', 'account_logout_v0190', 'open_settings_v0189'):
            self.assertIn(key,self.app)
        self.assertIn("st.link_button('회원가입', MARKETPLACE_BASE_URL",self.app)
        self.assertIn("st.link_button('ProjectAgain 웹사이트', MARKETPLACE_BASE_URL",self.app)
        self.assertIn('show_settings_dialog(scope, current, active_archive, cloud_owner,',self.app)

    def test_only_sidebar_is_compact_and_mobile_remains_tappable(self):
        scoped=self.css.split('/* v0.19.2 / editorial sidebar navigation',1)[1]
        self.assertIn('st-key-sidebar_primary_actions_v0192',scoped)
        self.assertIn('height:36px !important',scoped)
        self.assertIn('height:44px !important',scoped)
        self.assertIn('focus-visible',scoped)
        self.assertNotIn('[data-testid="stMain"] [data-testid="stButton"]',scoped)
        self.assertNotIn('.st-key-workspace_action_row_v0173',scoped)

    def test_broker_and_user_data_are_still_behind_verified_identity(self):
        self.assertIn('login.owner_key if connected and login',self.app)
        self.assertIn('set_broker_access_handler(ensure_fresh)',self.app)
        self.assertIn('save_conversation(cloud_owner',self.app)
        self.assertIn('delete_conversation(cloud_owner, cid)',self.app)
        self.assertIn('if session.get(\'pending\'):',self.app)
        self.assertIn('submit_confirmed_draft(pending)',self.app)
        self.assertIn('ENABLE_LIVE_DRAFTS',self.app)

    def test_handoff_explicitly_requires_platform_contract_before_auth_change(self):
        doc=(ROOT/'docs/PLATFORM_UNIFIED_LOGIN_HANDOFF_V0192.md').read_text('utf8')
        for text in ('v0.23','v0.25','명시적 동의','session_proof','Refresh Token',
                     '플랫폼 개발 채팅','Agent 개발 채팅','실 PostgreSQL'):
            self.assertIn(text,doc)
        self.assertIn('인증은 변경하지 않음',doc)

if __name__=='__main__': unittest.main()
