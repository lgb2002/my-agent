"""v0.18.6 diagnostics: safe class, libpq URI and Supabase network layering."""
import unittest
from pathlib import Path
from core.broker_storage_diagnostics import diagnose_broker_storage, _categorize, _is_supabase_db_host

URI = 'postgresql://postgres.private:encoded%40PASS@test.pooler.supabase.com:5432/postgres'

class FailingDB(Exception):
    pass

class BrokerDiagnosticsV0186(unittest.TestCase):
    def assertNoSecrets(self, result):
        report = str(result)
        for secret in ('postgres.private', 'encoded', 'PASS', 'test.pooler.supabase.com',
                       'postgresql://', 'SECRET', '@'):
            self.assertNotIn(secret, report)

    def test_libpq_uri_mismatch_stops_before_connect_or_probe(self):
        report = diagnose_broker_storage(URI,
            connect=lambda *_a, **_kw: self.fail('should not connect'),
            conninfo_parser=lambda _u: {'host':'wrong','user':'postgres.private','dbname':'postgres','port':'5432'},
            network_probe=lambda *_a: self.fail('should not probe'))
        self.assertEqual(report['category'], 'PostgreSQL 연결 문자열 해석 오류')
        self.assertEqual(report['uri_libpq'], '불일치/해석 오류')
        self.assertNoSecrets(report)

    def test_valid_libpq_uri_returns_normal_flag_before_connect(self):
        report = diagnose_broker_storage(URI,
            connect=lambda *_a, **_kw: (_ for _ in ()).throw(FailingDB('SECRET')),
            conninfo_parser=lambda _u: {'host':'test.pooler.supabase.com','user':'postgres.private','dbname':'postgres','port':'5432'},
            network_probe=lambda *_a: ('성공','성공'))
        self.assertEqual(report['uri_libpq'],'정상')
        self.assertEqual(report['category'],'DB 협상/인증 단계 확인 필요')
        self.assertEqual(report['dns_lookup'],'성공')
        self.assertEqual(report['tcp_connect'],'성공')
        self.assertEqual(report['exception_type'],'기타 예외')
        self.assertNoSecrets(report)

    def test_failed_dns_and_tcp_are_separate(self):
        def fail(*_a,**_kw):
            raise FailingDB('private SECRET')
        dns = diagnose_broker_storage(URI,connect=fail,network_probe=lambda *_:('실패','미검사'))
        self.assertEqual(dns['category'],'DNS 접속 확인 실패')
        self.assertEqual(dns['tcp_connect'],'미검사')
        tcp = diagnose_broker_storage(URI,connect=fail,network_probe=lambda *_:('성공','실패'))
        self.assertEqual(tcp['category'],'TCP 접속 확인 실패')
        self.assertNoSecrets(dns)
        self.assertNoSecrets(tcp)

    def test_probes_only_supabase_hostnames_and_db_ports(self):
        for host,port in [('evilpooler.supabase.com.attacker.tld',5432), ('localhost',5432),
                          ('aws-0.pooler.supabase.com',1234), ('evil.supabase.co',5432)]:
            self.assertFalse(_is_supabase_db_host(host,port))
        self.assertTrue(_is_supabase_db_host('aws-0-ap-northeast-1.pooler.supabase.com',5432))
        self.assertTrue(_is_supabase_db_host('db.abcdef.supabase.co',5432))

    def test_psycopg_unknown_exception_type_never_returned_verbatim(self):
        class SecretSensitiveException(Exception):
            pass
        result = diagnose_broker_storage(URI, connect=lambda *_a,**_kw: (_ for _ in ()).throw(SecretSensitiveException('SECRET')),
                                        network_probe=lambda *_a: ('성공','성공'))
        self.assertEqual(result['exception_type'],'기타 예외')
        self.assertNoSecrets(result)

    def test_new_classification_patterns(self):
        cases = [('invalid percent-encoded token', 'PostgreSQL 연결 문자열 해석 오류'),
                 ('server closed the connection unexpectedly','서버 연결 종료'),
                 ('sasl authentication failed','인증 오류')]
        for message,expected in cases:
            with self.subTest(message=message):
                self.assertEqual(_categorize(FailingDB(message))[0],expected)

    def test_no_network_when_auth_error_is_known(self):
        report = diagnose_broker_storage(URI, connect=lambda *_a,**_kw: (_ for _ in ()).throw(FailingDB('password authentication failed SECRET')),
            network_probe=lambda *_a: self.fail('network should not be called'))
        self.assertEqual(report['category'],'인증 오류')
        self.assertEqual(report['dns_lookup'],'미검사')
        self.assertNoSecrets(report)

    def test_app_ui_does_not_display_dsn_or_raw_exception(self):
        app = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf8')
        self.assertNotIn("st.caption('TCP 포트 접속 · '+report['tcp_connect'])",app)
        self.assertNotIn("st.caption('드라이버 오류 종류 · '+report['exception_type'])",app)
        self.assertNotIn('st.exception(exc)',app)
