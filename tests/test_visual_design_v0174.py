"""Visual-system behavior tests; no Streamlit runtime, external network or model calls."""
import ast
import re
import unittest
from pathlib import Path

from core.ui_design import layout_mode, risk_display, evidence_rows, activity_tone

ROOT = Path(__file__).resolve().parents[1]


class VisualSystemV0174Tests(unittest.TestCase):
    def test_wide_states_are_evidence_heavy(self):
        for state in ('recommend', 'search', 'inspection', 'workflow'):
            with self.subTest(state=state):
                self.assertEqual(layout_mode(state), 'wide')

    def test_reading_states_remain_narrow(self):
        for state in ('welcome', 'intake', 'conversation', 'restored', 'stale', 'error'):
            with self.subTest(state=state):
                self.assertEqual(layout_mode(state), 'reading')

    def test_confirmation_is_standard_width(self):
        self.assertEqual(layout_mode('offer'), 'standard')
        self.assertEqual(layout_mode('offer_summary'), 'standard')

    def test_unknown_state_fails_to_reading_not_extra_wide(self):
        self.assertEqual(layout_mode('new_something'), 'reading')

    def test_missing_data_is_not_green_safe_state(self):
        self.assertEqual(risk_display('UNKNOWN'), ('미확인', 'unknown'))
        self.assertEqual(risk_display(''), ('자료 확인 필요', 'unknown'))

    def test_static_pass_is_not_a_safety_certification(self):
        label, tone = risk_display('PASS')
        self.assertIn('표기', label)
        self.assertNotIn('안전', label)
        self.assertEqual(tone, 'reported')

    def test_risk_severity_has_real_text_labels(self):
        self.assertEqual(risk_display('PROBLEM'), ('문제 발견', 'problem'))
        self.assertEqual(risk_display('CAUTION'), ('주의', 'caution'))
        self.assertEqual(risk_display('SELLER_REPORTED'), ('판매자 고지', 'reported'))

    def test_html_evidence_escapes_model_and_seller_text(self):
        html = evidence_rows([{'label':'<script>evil</script>', 'status':'CAUTION',
                               'explanation':'<img src=x onerror=alert(1)>'}])
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('주의', html)
        self.assertIn('role="list"', html)
        self.assertIn('role="listitem"', html)

    def test_unknown_or_invalid_evidence_is_handled(self):
        self.assertEqual(evidence_rows([]), '')
        self.assertIn('자료 확인 필요', evidence_rows([{'label':'권리', 'status':'NEW_ENUM'}]))

    def test_api_response_tone_is_observed_not_verified(self):
        self.assertEqual(activity_tone(True), 'observed')
        self.assertEqual(activity_tone(False), 'problem')

    def test_single_css_design_token_source_and_three_widths(self):
        css = (ROOT/'assets/style.css').read_text(encoding='utf-8')
        self.assertEqual(css.count(':root {'),1)
        for token in ('--reading-width:820px', '--standard-width:1040px',
                      '--compare-width:1220px', '--type-body:1rem', '--leading-body:1.74'):
            self.assertIn(token, css)
        self.assertIn(':has(.pa-layout-mode--wide)', css)
        self.assertIn(':has(.pa-layout-mode--reading)', css)
        self.assertIn(':has(.pa-layout-mode--standard)', css)

    def test_responsive_focus_and_non_color_states(self):
        css = (ROOT/'assets/style.css').read_text(encoding='utf-8')
        for rule in ('@media (max-width:980px)', '@media (max-width:760px)',
                     '@media (max-width:600px)', '@media (max-width:375px)',
                     ':focus-visible', 'prefers-reduced-motion',
                     '.evidence-tag--problem', '.evidence-tag--unknown',
                     '.evidence-tag--caution'):
            self.assertIn(rule, css)
        self.assertIn('overflow-x:auto', css)
        self.assertIn('.mobile-table-cue {display:block', css)
        self.assertNotIn('overflow-y:auto', css)

    def test_real_app_uses_layout_state_and_evidence_rows(self):
        src = (ROOT/'app.py').read_text(encoding='utf-8')
        ast.parse(src)
        for code in ("mode = layout_mode(workbench['focus'])", 'pa-layout-mode--{}',
                     "evidence_rows(card['dimensions'])", "activity_tone(success)",
                     "with st.status('요청 분석 및 도구 실행 중'", "with st.container(key='conversation_history_v0174')"):
            self.assertIn(code,src)

    def test_business_permissions_are_not_modified(self):
        src = (ROOT/'app.py').read_text(encoding='utf-8')
        for code in ('submit_confirmed_draft(pending)', 'request_requires_account(submitted)',
                     'include_demo=show_demo', 'set_ai_identity(ai_identity)',
                     "st.session_state['queued_tool_prompt_v015']", 'st.chat_input('):
            self.assertIn(code, src)

    def test_design_doc_has_system_and_validation_contract(self):
        text = (ROOT/'DESIGN.md').read_text(encoding='utf-8')
        for term in ('시각적', '정보 구조', '컴포넌트', '인터랙션 상태',
                     '반응형', '접근성', '실제 Streamlit', '미검증', '사용자 통제'):
            self.assertIn(term,text)


if __name__ == '__main__':
    unittest.main()
