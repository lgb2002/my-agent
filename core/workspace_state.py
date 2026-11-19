"""Pure workbench projection from existing conversation data (no API/LLM calls).

A workspace is a presentation of the *latest observed* tool event, not a new
claim that a listing or trade remains unchanged. A stored conversation with
sanitized tool summaries must not be shown as current API data.
"""
from __future__ import annotations

from typing import Any

SURFACES = {
    'search_listings': 'search',
    'recommend_listings': 'recommend',
    'compare': 'recommend',
    'inspect_listing': 'inspection',
    'inspect_attached_zip': 'inspection',
    'prepare_offer': 'offer_summary',
    'list_offers': 'account_result',
    'get_handover': 'account_result',
    'get_recent_jobs': 'account_result',
    'get_buyer_preferences': 'account_result',
}
LABELS = {
    'welcome': ('시작', '어떤 프로젝트를 찾고 계신가요?'),
    'intake': ('추천 조건 정리', '나에게 맞는 프로젝트 찾기'),
    'search': ('매물 탐색', '플랫폼 매물 살펴보기'),
    'recommend': ('추천 결과', '후보를 비교하고 선택하기'),
    'inspection': ('공개 자료 검토', '확인된 내용과 남은 위험'),
    'offer': ('사용자 확인', '구매 제안 내용 확인'),
    'offer_summary': ('제안 준비', '구매 제안 준비 현황'),
    'workflow': ('진행 중인 작업', '이어서 할 작업 확인'),
    'account_result': ('조회 결과', '계정 정보 확인'),
    'error': ('확인 필요', '요청 결과를 확인해 주세요'),
    'restored': ('보관된 대화', '현재 플랫폼 정보 다시 확인'),
    'stale': ('조회 조건 변경', '새 조건으로 매물을 다시 확인해 주세요'),
    'conversation': ('대화', '프로젝트에 관해 이어서 이야기하기'),
}


def _last_assistant(turns: list) -> str:
    for turn in reversed(turns):
        if isinstance(turn, dict) and turn.get('role') == 'assistant':
            return str(turn.get('content') or '')
    return ''


def _last_event(turns: list):
    for turn_index in range(len(turns) - 1, -1, -1):
        turn = turns[turn_index]
        if not isinstance(turn, dict):
            continue
        events = turn.get('events') or []
        if not isinstance(events, list):
            continue
        for event_index in range(len(events) - 1, -1, -1):
            event = events[event_index]
            if isinstance(event, dict) and event.get('name'):
                return event, turn_index, event_index
    return None, None, None


def profile_for_display(context: dict) -> dict:
    intake = context.get('recommendation_intake')
    if isinstance(intake, dict) and isinstance(intake.get('profile'), dict):
        return dict(intake['profile'])
    profile = context.get('last_recommendation_profile')
    return dict(profile) if isinstance(profile, dict) else {}


def profile_summary(profile: dict) -> list[str]:
    """Only known fields are shown; missing values are never assumed."""
    if not isinstance(profile, dict):
        return []
    chips = []
    goal = profile.get('objective')
    if not goal:
        goals = profile.get('objectives')
        if isinstance(goals, list):
            goal = goals[0] if goals else ''
    if goal:
        chips.append('목적 · ' + str(goal)[:55])
    budget = profile.get('max_budget_krw')
    if type(budget) is int and budget > 0:
        chips.append('예산 · {:,}원 이하'.format(budget))
    skill = {'NONE': '처음', 'BASIC': '초급', 'INTERMEDIATE': '중급', 'ADVANCED': '고급'}
    if profile.get('skill_level') in skill:
        chips.append('개발 경험 · ' + skill[profile['skill_level']])
    risk = {'LOW': '낮음', 'MEDIUM': '보통', 'HIGH': '높음'}
    if profile.get('risk_tolerance') in risk:
        chips.append('위험 허용 · ' + risk[profile['risk_tolerance']])
    tech = profile.get('preferred_tech_stack') or []
    if isinstance(tech, list) and tech:
        chips.append('기술 · ' + ', '.join(str(t)[:22] for t in tech[:3]))
    monthly = profile.get('max_monthly_cost_krw')
    if type(monthly) is int and monthly >= 0:
        chips.append('월 운영비 · {:,}원 이하'.format(monthly))
    return chips


def workspace_view(session: dict) -> dict:
    """Prioritize an active confirmation/request over older tool results.

    Derived only from the caller's currently active, scoped conversation. No
    cross-user caches, guessed IDs, saved credentials or stale approval buttons.
    """
    turns = session.get('turns') or []
    if not isinstance(turns, list):
        turns = []
    context = session.get('context') or {}
    if not isinstance(context, dict):
        context = {}
    plan = context.get('workflow') if isinstance(context.get('workflow'), dict) else None
    profile = profile_for_display(context)
    event, turn_idx, event_idx = _last_event(turns)
    latest_assistant_idx = next((i for i in range(len(turns)-1,-1,-1) if isinstance(turns[i], dict) and turns[i].get('role') == 'assistant'), None)
    focus = 'welcome' if not turns else 'conversation'

    if session.get('pending'):
        focus = 'offer'
    elif context.get('recommendation_intake'):
        focus = 'intake'
    elif plan and plan.get('status') in ('WAITING_INPUT', 'WAITING_OFFER_PRICE', 'WAITING_APPROVAL'):
        focus = 'workflow'
    elif event is not None:
        if not event.get('success'):
            focus = 'error'
        elif 'data' not in event or not isinstance(event.get('data'), dict):
            # Archived tool summaries are not live recommendation/search data.
            focus = 'restored'
        else:
            focus = SURFACES.get(str(event.get('name')), 'conversation')
    elif plan and plan.get('status') not in ('COMPLETED', 'CANCELLED'):
        focus = 'workflow'
    if (context.get('_listing_snapshot_stale') and focus in ('search','recommend','inspection')
            and event is not None):
        focus = 'stale'
    # A newer conversational answer must not disappear behind an older tool
    # snapshot. Keep the previous result available as a reference instead.
    previous_result = None
    if (focus in ('search','recommend','inspection','account_result','offer_summary','error','stale')
            and latest_assistant_idx is not None and turn_idx is not None
            and latest_assistant_idx > turn_idx):
        previous_result = focus if focus != 'stale' else None
        focus = 'conversation'

    eyebrow, title = LABELS[focus]
    return {
        'focus': focus, 'eyebrow': eyebrow, 'title': title,
        'event': event, 'data': (event.get('data') if event else None) or {},
        'turn_index': turn_idx, 'event_index': event_idx,
        'plan': plan, 'profile': profile, 'chips': profile_summary(profile),
        'last_assistant': _last_assistant(turns),
        'turn_count': len(turns), 'previous_result': previous_result,
    }


def focused_actions(view: dict, context: dict, authenticated: bool, *, offer_enabled=False) -> list[tuple[str, str]]:
    """Contextual buttons submit ordinary chat requests, never direct writes."""
    focus = view.get('focus')
    data = view.get('data') or {}
    actions = []
    if focus == 'search':
        records = data.get('listings') or []
        if records and isinstance(records[0], dict):
            ident = records[0].get('id')
            if isinstance(ident, str) and _uuid(ident):
                actions.append(('첫 번째 매물 검토', f'{ident} 매물의 공개 정보를 검토해줘'))
        if data.get('next_cursor') is not None:
            actions.append(('다음 매물 보기', '다음 매물 보여줘'))
        actions.append(('내 조건으로 추천', '나에게 맞는 프로젝트 추천해줘'))
    elif focus == 'recommend':
        rows = data.get('ranked') or []
        if rows:
            first = rows[0].get('listing_id') if isinstance(rows[0], dict) else ''
            if _uuid(first):
                actions.append(('1순위 공개 정보 검토', f'{first} 매물의 공개 정보를 검토해줘'))
            if len(rows) >= 2:
                actions.append(('추천 후보 차이 설명', '방금 추천한 후보들의 가격, 운영 부담, 위험과 근거를 비교해줘'))
            if authenticated and offer_enabled and _uuid(first):
                actions.append(('1순위 제안 준비', f'{first} 매물에 구매 제안을 준비하려고 해. 필요한 조건을 먼저 확인해줘'))
        actions.append(('조건 바꿔 다시 추천', '추천 조건을 바꿔서 다시 찾고 싶어'))
    elif focus == 'inspection':
        actions.append(('미확인 자료 정리', '방금 공개 정보 검토에서 아직 검증되지 않은 내용을 정리해줘'))
        recent = [x for x in (context.get('recent_listings') or []) if isinstance(x, dict) and _uuid(x.get('id'))]
        if len(recent) >= 2:
            actions.append(('다른 후보 비교', '앞서 본 매물들 중 다른 후보와 차이점을 비교해줘'))
        else:
            actions.append(('다른 매물 둘러보기', '현재 등록된 매물 목록 보여줘'))
    elif focus == 'intake':
        actions.append(('현재 추천 조건 확인', '현재까지 확인한 조건과 부족한 조건을 알려줘'))
    elif focus in ('restored','stale'):
        actions.append(('플랫폼 매물 다시 조회', '현재 등록된 매물 목록 보여줘'))
    elif focus == 'error':
        actions.append(('매물 탐색부터 다시 시작', '현재 등록된 매물 목록 보여줘'))
    elif focus == 'workflow':
        actions.append(('현재 작업 단계 확인', '현재 작업에서 완료된 단계와 남은 일을 알려줘'))
    return actions[:3]


def _uuid(value: Any) -> bool:
    from uuid import UUID
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False
