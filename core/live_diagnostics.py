"""Explicit, safe, synchronous live diagnostics. No network calls on import.

Public listing requests are anonymous; personal authentication is tested
separately using a per-session delegated token. Only safe metadata is returned.
"""
from core.marketplace_client import MarketplaceClient, MarketplaceError


def _status_error(exc):
    if isinstance(exc, MarketplaceError):
        return {'ok': False, 'http_status': exc.status,
                'code': exc.code, 'detail': _safe_detail(exc.code, exc.status)}
    return {'ok': False, 'http_status': None, 'code': 'UNEXPECTED_ERROR',
            'detail': '요청 처리 중 오류가 발생했습니다.'}


def _safe_detail(code, status):
    if code == 'NETWORK_ERROR':
        return '네트워크 또는 원격 서버 연결 실패'
    if code in ('INVALID_RESPONSE','CONTRACT_MISMATCH'):
        return '플랫폼 응답 JSON 또는 items 배열 형식 확인 필요'
    if status in (401, 403):
        return '인증 또는 접근 권한 확인 필요'
    if status == 404:
        return 'API 경로 또는 대상 확인 필요'
    if status == 429:
        return 'API 요청 제한'
    if status is not None and status >= 500:
        return '플랫폼 서버 오류'
    return 'API 요청 또는 설정 확인 필요'


def check_public_listings(base_url, include_demo, *, limit=15):
    """Public GET never sends a Bearer token even when auth diagnostics use one."""
    params = {'limit': limit, 'cursor': 0, 'include_demo': str(bool(include_demo)).lower()}
    try:
        client = MarketplaceClient('', base_url=base_url)
        payload = client.listings(**params)
        return {'ok': True, 'http_status': 200, 'code': 'OK',
                'include_demo': bool(include_demo), 'count': len(payload['items']),
                'total_estimate': payload.get('total_estimate'),
                'has_next_page': payload.get('next_cursor') not in (None, ''),
                'path': '/api/v1/listings', 'detail': ('정상 조회 · 선택한 필터에서 0건' if not payload['items'] else '정상 조회')}
    except Exception as exc:
        result = _status_error(exc)
        result.update({'path': '/api/v1/listings', 'include_demo': bool(include_demo),
                       'count': None, 'total_estimate': None, 'has_next_page': None})
        return result


def check_delegation(base_url, token):
    if not token:
        return {'ok': False, 'http_status': None, 'code': 'NO_USER_TOKEN',
                'detail': '개인별 위임 토큰이 연결되지 않았습니다.'}
    try:
        client = MarketplaceClient(token, base_url=base_url)
        result = client.me()
        if not isinstance(result, dict) or not result.get('id'):
            return {'ok': False, 'http_status': 200, 'code': 'INVALID_PRINCIPAL',
                    'detail': '인증 API는 응답했으나 사용자 식별 필드가 없습니다.'}
        return {'ok': True, 'http_status': 200, 'code': 'OK',
                'detail': '사용자별 Bearer 위임 토큰 인증 성공',
                'scope_count': len(result.get('scopes') or [])}
    except Exception as exc:
        return _status_error(exc)


def run_diagnostics(base_url, token='', include_demo=False):
    """Only invoked by an explicit Streamlit button, no secrets in the result."""
    standard = check_public_listings(base_url, False)
    demo = check_public_listings(base_url, True)
    auth = check_delegation(base_url, token)
    if not standard['ok'] or not demo['ok']:
        explanation = '매물 수를 판단할 수 없습니다. HTTP 오류와 네트워크·응답 형식을 먼저 확인하세요.'
    elif standard['count'] == 0 and demo['count'] > 0:
        explanation = '일반 공개 목록에는 0건이고 시연 매물을 포함하면 조회됩니다.'
    elif standard['count'] == 0 and demo['count'] == 0:
        explanation = '두 조회 조건에서 모두 0건입니다. ACTIVE 상태 및 서버/필터를 확인하세요.'
    else:
        explanation = '플랫폼 조회가 정상 응답했습니다. 선택한 시연 필터에 따라 결과가 달라집니다.'
    return {'mode': 'live', 'selected_include_demo': bool(include_demo),
            'public': standard, 'with_demo': demo, 'delegation': auth,
            'interpretation': explanation}
