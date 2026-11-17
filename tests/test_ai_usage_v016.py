"""No-network test coverage for cost reserve/settle, limits and metered calls."""
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


class AIUsageTests(unittest.TestCase):
    def setUp(self):
        from core import ai_usage as usage
        self.m = usage
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'AI_CALLS_PER_MINUTE': '20', 'AI_CALLS_PER_USER_DAY': '20',
            'AI_GLOBAL_CALLS_PER_DAY': '30', 'AI_USER_DAILY_USD': '1',
            'AI_GLOBAL_DAILY_USD': '2', 'AI_MAX_RESERVED_CALL_USD': '0.10',
        })
        self.env.start()
        self.test_db = str(Path(self.temp.name) / 'test_usage.sqlite3')
        self.lock = threading.RLock()
        @contextmanager
        def fake_database():
            # No production SQLite fallback. This is a locked test seam only.
            with self.lock:
                con=sqlite3.connect(self.test_db, timeout=8)
                try:
                    con.execute(usage._SCHEMA)
                    yield con, 'sqlite'
                    con.commit()
                except Exception:
                    con.rollback()
                    raise
                finally:
                    con.close()
        self.db = patch.object(usage, '_db', fake_database)
        self.db.start()
        self.model = patch.object(usage, 'OPENAI_MODEL', 'gpt-4.1-mini')
        self.model.start()
        usage.set_ai_identity('platform:' + hashlib.sha256(b'alice').hexdigest())

    def tearDown(self):
        self.m.set_ai_identity(None)
        self.model.stop()
        self.db.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_no_identity_fails_closed(self):
        self.m.set_ai_identity(None)
        with self.assertRaises(self.m.AIAccessDenied):
            self.m.reserve('hello', 200)

    def test_no_public_sqlite_fallback(self):
        with patch.dict(os.environ, {'AI_LOCAL_SQLITE': 'true'}):
            self.assertEqual(self.m.storage_kind(), 'unconfigured')

    def test_successful_reservation_and_usage_settlement(self):
        ticket = self.m.reserve('hello', 200)
        before = self.m.usage_snapshot(self.m.current_ai_identity())
        self.assertEqual(before['calls'], 1)
        self.m.settle(ticket, SimpleNamespace(usage_metadata={'input_tokens': 100,'output_tokens': 30}))
        after = self.m.usage_snapshot(self.m.current_ai_identity())
        self.assertLess(after['estimated_usd'], before['estimated_usd'])
        self.assertEqual(after['calls'], 1)

    def test_daily_call_limit_and_new_subject_global(self):
        os.environ['AI_CALLS_PER_USER_DAY'] = '2'
        self.m.reserve('hello', 200)
        self.m.reserve('hello', 200)
        with self.assertRaises(self.m.AIQuotaExceeded):
            self.m.reserve('hello', 200)
        self.m.set_ai_identity('oidc:' + hashlib.sha256(b'bob').hexdigest())
        self.m.reserve('hello', 200)

    def test_global_call_limit_cross_user(self):
        os.environ['AI_GLOBAL_CALLS_PER_DAY'] = '2'
        self.m.reserve('hello', 200)
        self.m.set_ai_identity('oidc:' + hashlib.sha256(b'bob').hexdigest())
        self.m.reserve('hello', 200)
        with self.assertRaises(self.m.AIQuotaExceeded):
            self.m.reserve('hello', 200)

    def test_cost_limits_block_before_call(self):
        os.environ['AI_MAX_RESERVED_CALL_USD'] = '0.001'
        with self.assertRaises(self.m.AIQuotaExceeded):
            self.m.reserve('a' * 50000, 800)
        self.assertEqual(self.m.usage_snapshot(self.m.current_ai_identity())['calls'], 0)

    def test_bad_model_price_fails_closed(self):
        self.m.OPENAI_MODEL = 'custom-expensive-model'
        with self.assertRaises(self.m.AIAccessDenied):
            self.m.reserve('hello', 200)

    def test_missing_database_fails_closed(self):
        with patch.object(self.m, '_db', side_effect=self.m.AIAccessDenied('not configured')):
            with self.assertRaises(self.m.AIAccessDenied):
                self.m.reserve('hello', 200)

    def test_model_invoke_metered(self):
        class Fake:
            count = 0
            def invoke(self, prompt, **kwargs):
                self.count += 1
                return SimpleNamespace(content='ok', usage_metadata={'input_tokens': 50,'output_tokens': 4})
        raw = Fake()
        model = self.m.metered_model(raw, max_output_tokens=100)
        self.assertEqual(model.invoke('hi').content, 'ok')
        self.assertEqual(raw.count,1)
        self.assertEqual(self.m.usage_snapshot(self.m.current_ai_identity())['calls'],1)
        os.environ['AI_CALLS_PER_USER_DAY']='1'
        with self.assertRaises(self.m.AIQuotaExceeded):
            model.invoke('hi')
        self.assertEqual(raw.count,1)

    def test_structured_output_collects_raw_usage(self):
        class Fake:
            def with_structured_output(self, schema, include_raw, **kwargs):
                assert include_raw is True
                return SimpleNamespace(invoke=lambda prompt, **kw: {
                    'raw': SimpleNamespace(usage_metadata={'input_tokens':100,'output_tokens':30}),
                    'parsed': {'ok':True}, 'parsing_error':None})
        model=self.m.metered_model(Fake(),max_output_tokens=300)
        self.assertEqual(model.with_structured_output(dict).invoke('hi'),{'ok':True})
        self.assertEqual(self.m.usage_snapshot(self.m.current_ai_identity())['calls'],1)

    def test_failed_model_attempt_keeps_budget(self):
        class Fake:
            def invoke(self, *a, **kw):
                raise ConnectionError('network after server receipt')
        model=self.m.metered_model(Fake(), max_output_tokens=100)
        with self.assertRaises(ConnectionError):
            model.invoke('hi')
        self.assertGreater(self.m.usage_snapshot(self.m.current_ai_identity())['estimated_usd'],0)

    def test_per_minute_limit(self):
        os.environ['AI_CALLS_PER_MINUTE'] = '1'
        self.m.reserve('first', 100)
        with self.assertRaises(self.m.AIQuotaExceeded):
            self.m.reserve('second', 100)

    def test_concurrent_calls_cannot_race_over_quota(self):
        from concurrent.futures import ThreadPoolExecutor
        os.environ['AI_GLOBAL_CALLS_PER_DAY'] = '4'
        os.environ['AI_CALLS_PER_USER_DAY'] = '100'
        os.environ['AI_CALLS_PER_MINUTE'] = '100'
        subject = self.m.current_ai_identity()
        def attempt(i):
            self.m.set_ai_identity(subject)  # ContextVar is thread-local by design.
            try:
                self.m.reserve('parallel-%s' % i, 100)
                return True
            except self.m.AIQuotaExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(sum(results), 4)

    def test_no_private_content_stored_in_ledger(self):
        message = 'private buyer detail: confidential words'
        self.m.reserve(message,100)
        db = Path(self.test_db).read_bytes()
        self.assertNotIn(message.encode(),db)
        self.assertNotIn(b'confidential',db)


if __name__ == '__main__':
    unittest.main()
