"""Opt-in, read-only PostgreSQL connection diagnosis for ProjectAgain Broker.

Only expose a fixed vocabulary. Never show/log exception strings, DSNs,
usernames, hostnames, passwords or driver tracebacks to the browser.
Run only after the native OIDC browser login, from an explicit button click.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


# No raw exception strings, remote SQL errors or host values are returned.
_SQLSTATE = re.compile(r'^[A-Z0-9]{5}$')


def _categorize(exc):
    """Map driver exceptions into coarse, low-disclosure categories."""
    raw_state = getattr(exc, 'sqlstate', None)
    state = raw_state if isinstance(raw_state, str) and _SQLSTATE.fullmatch(raw_state) else None
    if state == '28P01' or (state and state.startswith('28')):
        return '인증 오류', state, 'Supabase 연결 문자열의 사용자명과 비밀번호를 확인해 주세요.'
    if state == '3D000':
        return '데이터베이스 이름 오류', state, '연결 문자열의 데이터베이스 이름을 확인해 주세요.'
    if state == '42501':
        return '접근 권한 오류', state, '연결 계정의 데이터베이스 접근 권한을 확인해 주세요.'
    if state in ('53300', '53400'):
        return '연결 수 또는 자원 한도', state, 'Supabase 연결 수와 프로젝트 자원 한도를 확인해 주세요.'
    if state in ('57P03', '57P01'):
        return '데이터베이스 서버 준비 중', state, 'Supabase 프로젝트 실행 상태를 확인해 주세요.'
    # Read exception text ONLY for internal classification; never return it.
    detail = str(exc).lower()
    if any(term in detail for term in ('password authentication failed', 'invalid password', 'no password supplied')):
        return '인증 오류', state, 'Supabase 연결 문자열의 사용자명과 비밀번호를 확인해 주세요.'
    if any(term in detail for term in ('tenant or user not found', 'no such user')):
        return 'Pooler 사용자 식별 오류', state, 'Supabase Connect 화면의 Session pooler URI를 다시 확인해 주세요.'
    if any(term in detail for term in ('could not translate host', 'name or service not known', 'nodename nor servname', 'temporary failure in name resolution')):
        return 'DNS 이름 조회 오류', state, 'Supabase Connect에서 복사한 호스트와 외부 DNS 연결을 확인해 주세요.'
    if isinstance(exc, (TimeoutError,)) or any(term in detail for term in ('timeout expired', 'timed out', 'connection timeout')):
        return '연결 시간 초과', state, 'Supabase 프로젝트 상태와 Streamlit Cloud의 외부 연결을 확인해 주세요.'
    if any(term in detail for term in ('connection refused', 'network is unreachable', 'no route to host', 'could not connect to server')):
        return '네트워크 연결 오류', state, 'Supabase 연결 호스트·포트·프로젝트 가동 상태를 확인해 주세요.'
    if any(term in detail for term in ('ssl', 'tls', 'certificate')):
        return 'TLS 연결 오류', state, 'Supabase Pooler의 TLS 설정을 확인해 주세요.'
    if any(term in detail for term in ('too many connections', 'max client connections')):
        return '연결 수 한도', state, 'Supabase 연결 수 한도를 확인해 주세요.'
    return '기타 데이터베이스 연결 오류', state, 'Streamlit 앱의 배포 상태와 Supabase 프로젝트 연결 설정을 확인해 주세요.'


def diagnose_broker_storage(database_url, *, secret_url=None, connect=None):
    """Perform SELECT-only connectivity check. The returned report has no secrets.

    `connect` is a deterministic unit-test hook, not exposed in production UI.
    When both env and Secrets exist, only their equality is reported (no hash).
    This function does NOT write tables, credentials or logs.
    """
    result = {
        'status': '연결 실패',
        'stage': '설정 확인',
        'category': '설정 오류',
        'sqlstate': None,
        'environment_override_differs': bool(
            secret_url is not None and str(secret_url).strip()
            and str(database_url or '') != str(secret_url)
        ),
        'schema_create': None,
        'advice': 'AGENT_STATE_DATABASE_URL 설정을 확인해 주세요.',
    }
    if not isinstance(database_url, str) or not database_url.strip():
        result['category'] = '연결 주소 없음'
        return result
    try:
        parsed = urlsplit(database_url)
        if (parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname
                or not parsed.username or parsed.password is None or not (1 <= (parsed.port or 5432) <= 65535)):
            result['category'] = '연결 주소 형식 오류'
            return result
    except (TypeError, ValueError):
        result['category'] = '연결 주소 형식 오류'
        return result

    if connect is None:
        try:
            import psycopg
        except (ImportError, OSError):
            result['stage'] = '드라이버 로딩'
            result['category'] = 'PostgreSQL 드라이버 오류'
            result['advice'] = 'requirements.txt에 psycopg[binary]가 설치되었는지 확인해 주세요.'
            return result
        connect = psycopg.connect

    result['stage'] = 'DB 접속'
    try:
        # Same timeout/TLS options as BrokerStore._db(); never echo DSN.
        with connect(database_url, connect_timeout=5, sslmode='require') as conn:
            result['stage'] = '읽기 쿼리'
            value = conn.execute('SELECT 1').fetchone()
            if value is None or value[0] != 1:
                result['category'] = '읽기 검증 실패'
                result['advice'] = 'DB 연결은 됐지만 읽기 검증에 실패했습니다.'
                return result
            # Read-only check; BrokerStore creates tables in public when needed.
            try:
                permission = conn.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')").fetchone()
                result['schema_create'] = bool(permission[0]) if permission else None
            except Exception:
                # A successful SELECT 1 still proves DB connectivity.
                result['schema_create'] = None
        result['status'] = '연결 성공'
        result['stage'] = '완료'
        result['category'] = '정상'
        result['advice'] = ('DB 연결은 정상입니다. public 스키마의 CREATE 권한을 확인해 주세요.'
                            if result['schema_create'] is False
                            else 'DB 연결은 정상입니다. 권한 연결 오류가 계속된다면 Broker API 응답을 별도로 확인해야 합니다.')
        return result
    except Exception as exc:
        result['category'], result['sqlstate'], result['advice'] = _categorize(exc)
        return result
