"""Context-aware shortcuts. Prompts still pass through normal chat permissions."""
import uuid

PRIVATE_TOOLS = ('get_buyer_preferences', 'list_offers', 'get_handover', 'get_recent_jobs', 'prepare_offer')


def _has_uuid(item):
    try:
        uuid.UUID(str(item.get('id')))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def suggested_actions(context, *, authenticated=False, has_upload=False, limit=4):
    """Build only relevant actions from the current known context; no invented IDs."""
    actions = []
    intake = context.get('recommendation_intake')
    recent = [item for item in (context.get('recent_listings') or []) if isinstance(item, dict) and _has_uuid(item)]
    plan = context.get('workflow') if isinstance(context.get('workflow'), dict) else {}
    if intake:
        actions.append(('추천 조건 확인', '지금까지 확인한 추천 조건과 아직 부족한 조건을 알려줘'))
    elif context.get('last_recommendation_profile'):
        actions.append(('조건으로 다시 추천', '앞서 확인한 구매 조건을 사용해 다시 추천해줘'))
    else:
        actions.append(('맞춤 추천', '나에게 맞는 프로젝트 추천해줘'))
    if recent:
        actions.append(('1번 매물 검토', f"{recent[0]['id']} 매물의 공개 정보를 검토해줘"))
        if len(recent) >= 2:
            actions.append(('후보 비교', '앞서 확인한 매물 중 첫 번째와 두 번째의 가격, 기술, 확인할 위험을 비교해줘'))
    else:
        actions.append(('매물 둘러보기', '현재 등록된 매물 목록 보여줘'))
    if plan and plan.get('status') not in ('COMPLETED', 'CANCELLED'):
        actions.append(('현재 작업 확인', '현재 작업 계획에서 완료된 단계와 다음 행동을 알려줘'))
    if authenticated:
        if not intake:
            actions.append(('내 구매 조건', '내 구매 조건 확인해줘'))
        if recent:
            actions.append(('제안 준비', '앞서 본 1번 매물에 구매 제안을 준비하려고 해. 필요한 조건을 먼저 확인해줘'))
        actions.append(('제안 내역', '내 구매 제안 목록 보여줘'))
        actions.append(('최근 작업', '최근 작업 기록 보여줘'))
        actions.append(('인수인계 조회', '내 거래의 인수인계를 확인하려면 어떤 거래 ID가 필요한지 알려줘'))
    if has_upload:
        actions.append(('ZIP 정적 검사', '첨부한 ZIP 파일을 정적으로 검사해줘'))
    return actions[:max(1,min(6,int(limit)))]


PLATFORM_STATES = {
    'UNKNOWN':'상태 확인 필요', 'DRAFT':'초안', 'CREATED':'초안 등록됨',
    'PENDING':'확인 대기', 'PENDING_APPROVAL':'승인 대기',
    'WAITING_APPROVAL':'승인 대기', 'APPROVED':'플랫폼 승인됨',
    'EXECUTED':'플랫폼 실행 처리됨 (권리 이전 별도 확인)',
    'REJECTED':'반려됨', 'CANCELLED':'취소됨', 'EXPIRED':'유효기간 종료',
    'FAILED':'처리 실패', 'COMPLETED':'작업 단계 완료', 'PARTIAL':'일부만 완료',
    'IN_PROGRESS':'처리 중', 'RUNNING':'처리 중', 'WAITING_INPUT':'추가 정보 대기',
    'WAITING_OFFER_PRICE':'제안 금액 대기', 'BLOCKED':'진행 제한', 'SKIPPED':'실행하지 않음',
    'PASS':'정적 규칙 통과 표기', 'FAIL':'정적 검사에서 주의 항목 발견',
    'NOT_TESTED':'검사하지 않음', 'OBSERVED':'자료에서 확인됨',
}


def friendly_state(value):
    return PLATFORM_STATES.get(str(value or '').upper(), '상태 확인 필요')


TOOL_RESULT_LABELS = {
    'search_listings': '매물 목록 조회됨',
    'recommend_listings': '추천 후보 평가 결과 생성',
    'inspect_listing': '공개 정보 정적 점검 결과 수신',
    'inspect_attached_zip': 'ZIP 정적 검사 결과 수신',
    'list_offers': '제안 내역 조회됨',
    'prepare_offer': '구매 제안 초안 준비됨 · 미제출',
    'get_handover': '인수인계 현황 조회됨',
    'get_recent_jobs': '작업 내역 조회됨',
    'get_buyer_preferences': '구매 조건 조회됨',
}


def tool_result_label(name, success):
    if not success:
        return '도구 응답 실패 · 결과 확인 필요'
    return TOOL_RESULT_LABELS.get(name, '도구 응답 수신 · 검증과 별개')


def request_requires_account(message):
    """Small deterministic UI gate only, NOT intent or business-logic parsing.

    A request to *explain* a private capability should still reach the model.
    """
    s = str(message or '').strip()
    if any(term in s for term in ('뭐야', '무슨', '설명', '어떻게', '알려줄 수 있', '뜻이')):
        return False
    return any(term in s for term in (
        '내 구매 조건 조회', '내 구매 조건 확인', '내 제안 목록',
        '내 구매 제안 목록', '최근 작업 기록', '내 작업 기록',
        '내 인수인계 조회', '제안 초안 제출', '구매 제안 준비',
        '구매 제안 작성', '구매 제안 보내', '인수인계 현황 조회',
    ))
