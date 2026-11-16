"""Guardrails for the first-run experience (no Streamlit server required)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EntryDesignTests(unittest.TestCase):
    def test_four_action_prompts_match_existing_tool_intents(self):
        from agent.chat import offline_intent
        root = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        examples = None
        for node in ast.walk(root):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'examples' for target in node.targets
            ):
                examples = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(examples)
        self.assertEqual([r[0] for r in examples], ['01', '02', '03', '04'])
        self.assertEqual(len({r[1] for r in examples}), 4)
        targets = ['search_listings', 'recommend_listings', 'search_listings', 'get_recent_jobs']
        for option, target in zip(examples, targets):
            with self.subTest(label=option[1]):
                self.assertEqual(offline_intent(option[3], {})[0], target)

    def test_ui_chrome_keeps_native_streamlit_controls(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('with st.container(key="welcome_actions"):', source)
        self.assertIn('for start in (0, 2):', source)  # row-major mobile reading order
        self.assertIn('st.chat_input(', source)
        self.assertIn('st.button(title, width="stretch"', source)
        self.assertIn('pending_prompt = prompt', source)
        self.assertIn('perform_confirmed_action(', source)
        self.assertIn('st.rerun()', source)

    def test_important_keyboard_and_mobile_styles_are_present(self):
        css = (ROOT / 'assets' / 'style.css').read_text(encoding='utf-8')
        for rule in ('st-key-welcome_actions', ':focus-visible', '@media (max-width:760px)',
                     'prefers-reduced-motion', 'stChatInput'):
            with self.subTest(rule=rule):
                self.assertIn(rule, css)

    def test_design_system_is_labeled_provisional(self):
        doc = (ROOT / 'DESIGN.md').read_text(encoding='utf-8')
        self.assertIn('실제 Streamlit', doc)
        self.assertIn('미검증', doc)
        self.assertIn('첫 진입', doc)


if __name__ == '__main__':
    unittest.main()
