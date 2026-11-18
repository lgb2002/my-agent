"""Broker DB diagnostics are read-only, opt-in and reveal no connection secrets."""
import unittest
from pathlib import Path

from core.broker_storage_diagnostics import diagnose_broker_storage

SECRET_URL = 'postgresql://private.account:supER@private.hostname.example:5432/postgres'


class QueryConnection:
    def __init__(self, create_permission=True, *, fail_query=False):
        self.queries = []
        self.create_permission = create_permission
        self.fail_query = fail_query

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.queries.append(sql)
        if self.fail_query:
            raise RuntimeError('DB failure private.hostname.example superSECRET')
        if sql == 'SELECT 1':
            self.value = (1,)
        elif sql == "SELECT has_schema_privilege(current_user, 'public', 'CREATE')":
            self.value = (self.create_permission,)
        else:
            raise AssertionError('Unexpected query')
        return self

    def fetchone(self):
        return self.value


class SQLFailure(Exception):
    def __init__(self, sqlstate, message):
        self.sqlstate = sqlstate
        super().__init__(message)


class BrokerStorageDiagnosticTests(unittest.TestCase):
    def test_select_only_success(self):
        con = QueryConnection()
        def fake_connect(dsn, **kwargs):
            self.assertEqual(dsn, SECRET_URL)
            self.assertEqual(kwargs, {'sslmode': 'require', 'connect_timeout': 5})
            return con
        result = diagnose_broker_storage(SECRET_URL, connect=fake_connect)
        self.assertEqual(result['status'], '연결 성공')
        self.assertEqual(result['schema_create'], True)
        self.assertEqual(con.queries, ['SELECT 1',
            "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"])

    def test_create_permission_false_is_reported_without_writing(self):
        result = diagnose_broker_storage(SECRET_URL, connect=lambda *_args, **_kw: QueryConnection(False))
        self.assertEqual(result['status'], '연결 성공')
        self.assertIs(result['schema_create'], False)
        self.assertIn('CREATE', result['advice'])

    def test_no_database_url_fails_without_calling_connector(self):
        result = diagnose_broker_storage('', connect=lambda *_a,**_kw: self.fail('should not connect'))
        self.assertEqual(result['category'], '연결 주소 없음')

    def test_invalid_url_fails_without_calling_connector(self):
        for url in ('sqlite://x', 'postgresql://x', 'postgresql://a:p@host:abc/postgres'):
            with self.subTest(url=url):
                result = diagnose_broker_storage(url, connect=lambda *_a,**_kw: self.fail('must not connect'))
                self.assertEqual(result['category'], '연결 주소 형식 오류')

    def test_password_failure_maps_sqlstate_without_leaking_raw_exception(self):
        def fail(*_a,**_kw):
            raise SQLFailure('28P01','password authentication failed for user private.account on private.hostname.example: supER')
        result = diagnose_broker_storage(SECRET_URL, connect=fail)
        self.assertEqual(result['category'], '인증 오류')
        self.assertEqual(result['sqlstate'], '28P01')
        self.assertSafe(result)

    def assertSafe(self, report):
        output = str(report)
        for substring in ('private.account','private.hostname.example','supER','postgresql://','@'):
            self.assertNotIn(substring, output)

    def test_timeout_category_and_private_exception_removed(self):
        def fail(*_a,**_kw):
            raise TimeoutError('timed out private.hostname.example with supER')
        result = diagnose_broker_storage(SECRET_URL, connect=fail)
        self.assertEqual(result['category'], '연결 시간 초과')
        self.assertSafe(result)

    def test_dns_classification_and_private_host_removed(self):
        def fail(*_a,**_kw):
            raise OSError('could not translate host name "private.hostname.example" to address')
        result = diagnose_broker_storage(SECRET_URL, connect=fail)
        self.assertEqual(result['category'], 'DNS 이름 조회 오류')
        self.assertSafe(result)

    def test_pooler_user_error_without_raw_account(self):
        def fail(*_a,**_kw):
            raise Exception('Tenant or user not found private.account')
        result = diagnose_broker_storage(SECRET_URL, connect=fail)
        self.assertEqual(result['category'], 'Pooler 사용자 식별 오류')
        self.assertSafe(result)

    def test_secret_environment_mismatch_only_boolean(self):
        result = diagnose_broker_storage(SECRET_URL,
            secret_url='postgresql://another-user:another-PASS@another.domain:5432/postgres',
            connect=lambda *_a,**_kw: QueryConnection())
        self.assertIs(result['environment_override_differs'], True)
        self.assertSafe(result)
        self.assertNotIn('another', str(result))
        good = diagnose_broker_storage(SECRET_URL,secret_url=SECRET_URL,
            connect=lambda *_a,**_kw: QueryConnection())
        self.assertIs(good['environment_override_differs'], False)

    def test_query_error_caught_without_leaking(self):
        result = diagnose_broker_storage(SECRET_URL, connect=lambda *_a,**_kw: QueryConnection(fail_query=True))
        self.assertEqual(result['stage'], '읽기 쿼리')
        self.assertEqual(result['status'], '연결 실패')
        self.assertSafe(result)

    def test_database_diagnostic_ui_is_hidden_in_public_app(self):
        app=(Path(__file__).resolve().parents[1]/'chat_ui.py').read_text(encoding='utf8')
        self.assertNotIn("st.button('DB 연결 진단 실행'", app)
        self.assertNotIn("with st.expander('로그인 저장소 오류 진단'", app)
        self.assertIn("storage_diagnosis_needed = exc.code == 'storage_unavailable'",app)
        self.assertNotIn('st.exception(exc)',app)


if __name__=='__main__':
    unittest.main()
