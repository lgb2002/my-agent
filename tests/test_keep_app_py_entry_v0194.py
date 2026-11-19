"""Regression checks for v0.19.4 stable app.py deployment entry."""
import ast
import hashlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class StableEntrypointTests(unittest.TestCase):
    def test_chat_ui_matches_audited_v0195_presentation_update(self):
        # SHA-256 after v0.19.5 sidebar-only clarity update. The ASGI entry stays unchanged.
        self.assertEqual(hashlib.sha256((ROOT / 'chat_ui.py').read_bytes()).hexdigest(),
                         '69c9e1867c5902cc1d315206ed88197fd23ddaae92cec656e802664490f51988')

    def test_both_launchers_target_same_chat_ui_with_secure_callback_routes(self):
        for name in ('app.py', 'unified_entry.py'):
            with self.subTest(name=name):
                source = (ROOT / name).read_text(encoding='utf-8')
                tree = ast.parse(source)
                calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
                launches = [c for c in calls if isinstance(c.func, ast.Attribute)
                            and isinstance(c.func.value, ast.Name)
                            and c.func.value.id == 'st' and c.func.attr == 'App']
                self.assertEqual(len(launches), 1)
                self.assertEqual(launches[0].args[0].value, 'chat_ui.py')
                self.assertIn("'/pa-agent/auth/start'", source)
                self.assertIn("'/pa-agent/auth/logout'", source)
                self.assertIn('BrokerReturnMiddleware', source)
                self.assertIn("AGENT_UNIFIED_ENTRY_READY", source)
                self.assertNotIn('exec(', source)
                self.assertNotIn('import chat_ui', source)

    def test_entrypoint_can_create_asgi_app_without_running_chat_ui(self):
        class FakeApp:
            def __init__(self, script_path, **kwargs):
                self.script_path = script_path
                self.routes = kwargs['routes']
                self.middleware = kwargs['middleware']

        class FakeRoute:
            def __init__(self, path, endpoint, *, methods):
                self.path = path
                self.endpoint = endpoint
                self.methods = methods

        class FakeMiddleware:
            def __init__(self, cls):
                self.cls = cls

        streamlit = types.ModuleType('streamlit')
        streamlit.App = FakeApp
        starlette = types.ModuleType('starlette')
        starlette.__path__ = []
        middleware = types.ModuleType('starlette.middleware')
        middleware.Middleware = FakeMiddleware
        routing = types.ModuleType('starlette.routing')
        routing.Route = FakeRoute
        unified = types.ModuleType('core.unified_web')
        class BrokerReturnMiddleware:
            pass
        unified.BrokerReturnMiddleware = BrokerReturnMiddleware
        unified.login_start = lambda request: None
        unified.login_logout = lambda request: None
        before = os.environ.get('AGENT_UNIFIED_ENTRY_READY')
        try:
            with patch.dict(sys.modules, {'streamlit': streamlit,
                                          'starlette': starlette,
                                          'starlette.middleware': middleware,
                                          'starlette.routing': routing,
                                          'core.unified_web': unified}):
                for name in ('app.py', 'unified_entry.py'):
                    # Execute the launcher just as discovery would; the real
                    # Streamlit UI must never be executed by the launcher.
                    namespace = {'__name__': '__main__', '__file__': str(ROOT / name)}
                    exec(compile((ROOT/name).read_text(encoding='utf-8'), str(ROOT/name), 'exec'), namespace)
                    app = namespace.get('app')
                    self.assertIsInstance(app, FakeApp)
                    self.assertEqual(app.script_path, 'chat_ui.py')
                    self.assertEqual([r.path for r in app.routes],
                                     ['/pa-agent/auth/start', '/pa-agent/auth/logout'])
                    self.assertTrue(all(r.methods == ['GET'] for r in app.routes))
                    self.assertIs(app.middleware[0].cls, BrokerReturnMiddleware)
                    self.assertEqual(os.environ['AGENT_UNIFIED_ENTRY_READY'], '1')
        finally:
            if before is None:
                os.environ.pop('AGENT_UNIFIED_ENTRY_READY', None)
            else:
                os.environ['AGENT_UNIFIED_ENTRY_READY'] = before

    def test_no_extra_dependencies_or_real_secrets_added(self):
        requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('streamlit>=1.57', requirements)
        self.assertIn('cryptography', requirements)
        self.assertFalse((ROOT / '.env').exists())
        self.assertFalse((ROOT / '.streamlit/secrets.toml').exists())


if __name__ == '__main__':
    unittest.main()
