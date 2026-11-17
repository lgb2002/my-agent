# -*- coding: utf-8 -*-
"""Pure, source-backed view models for the Streamlit marketplace workspace.

These functions never decide whether a trade is authorized, whether a listing is
safe or whether a workflow is complete. They present the underlying states
without counting skipped/blocked/approval-pending work as completed.
"""
from __future__ import annotations

WORKFLOW_STATES = {
    'ACTIVE': '작업 진행 중',
    'PARTIAL': '일부 작업만 완료',
    'COMPLETED': '작업 단계 완료',
    'WAITING_INPUT': '정보 입력 대기',
    'WAITING_OFFER_PRICE': '제안 금액 입력 대기',
    'WAITING_APPROVAL': '사용자 승인 대기',
    'FAILED': '실행 실패',
    'INTERRUPTED': '작업 중단',
    'CANCELLED': '사용자가 중단함',
}
STEP_STATES = {
    'COMPLETED': ('완료', '✓'),
    'PARTIAL': ('부분 완료', '△'),
    'WAITING_INPUT': ('정보 대기', '?'),
    'WAITING_APPROVAL': ('승인 대기', '◇'),
    'BLOCKED': ('진행 제한', '!'),
    'FAILED': ('실패', '×'),
    'INTERRUPTED': ('중단', '↻'),
    'SKIPPED': ('실행하지 않음', '–'),
    'RUNNING': ('실행 중', '◌'),
    'PENDING': ('대기', '○'),
}


def workflow_view(plan: dict) -> dict:
    """Present completed/remaining work without manufacturing success.

    Partial completion, approval waits, skipped work and blocks all count as
    *not completed*. A verified workflow may still have a caveat about rights
    transfer; this view does not imply transaction settlement.
    """
    steps = [step for step in (plan.get('steps') or []) if isinstance(step, dict)]
    total = len(steps)
    completed = sum(step.get('status') == 'COMPLETED' for step in steps)
    outstanding = total - completed
    statuses = [str(step.get('status') or 'PENDING') for step in steps]
    counts = {name: statuses.count(name) for name in STEP_STATES}
    state = str(plan.get('status') or 'ACTIVE')
    verified = plan.get('verified') if isinstance(plan.get('verified'), dict) else {}
    if 'WAITING_INPUT' in statuses or state in ('WAITING_INPUT', 'WAITING_OFFER_PRICE'):
        if state == 'WAITING_OFFER_PRICE' or any(s.get('key') == 'prepare_offer' and s.get('status') == 'WAITING_INPUT' for s in steps):
            next_action = '구매 예산이 아닌 실제 제안 금액을 대화에 입력해 주세요.'
        else:
            next_action = '추천에 필요한 조건을 대화로 알려주세요.'
    elif 'WAITING_APPROVAL' in statuses or state == 'WAITING_APPROVAL':
        next_action = '제안 초안 상태를 확인하세요. 승인·실행은 플랫폼 웹에서 별도로 진행해요.'
    elif 'FAILED' in statuses or state == 'FAILED':
        next_action = '실패한 단계를 확인하고 필요한 경우 재시도해 주세요.'
    elif 'BLOCKED' in statuses:
        next_action = '진행할 수 없었던 단계와 사유를 확인해 주세요.'
    elif 'INTERRUPTED' in statuses or state == 'INTERRUPTED':
        next_action = '중단된 작업을 이어서 실행하거나 종료할 수 있어요.'
    elif 'PARTIAL' in statuses or state == 'PARTIAL' or 'SKIPPED' in statuses:
        next_action = '일부 요청이 충족되지 않았어요. 미완료 단계와 확인 사항을 살펴보세요.'
    elif completed == total and total and state == 'COMPLETED' and verified.get('fulfilled') is True:
        next_action = '요청한 작업 단계는 완료됐어요. 실제 거래·권리 이전은 별도 확인이 필요해요.'
    else:
        next_action = '남은 단계를 대화 또는 작업 이어하기로 진행할 수 있어요.'
    details = []
    for step in steps:
        key = str(step.get('status') or 'PENDING')
        label, icon = STEP_STATES.get(key, ('상태 확인', '·'))
        details.append({
            'label': str(step.get('label') or '작업 단계')[:120],
            'state': label, 'icon': icon,
            'note': str(step.get('note') or '')[:250],
            'completed': key == 'COMPLETED',
        })
    return {
        'label': WORKFLOW_STATES.get(state, '작업 상태 확인'),
        'total': total, 'completed': completed, 'outstanding': outstanding,
        'fraction': completed / total if total else 0.0,
        'waiting_approval': counts['WAITING_APPROVAL'],
        'waiting_input': counts['WAITING_INPUT'],
        'partial': counts['PARTIAL'],
        'blocked': counts['BLOCKED'] + counts['FAILED'],
        'skipped': counts['SKIPPED'],
        'next_action': next_action,
        'steps': details,
    }


def _price(value):
    return f'{value:,}원' if type(value) is int and value >= 0 else '가격 미확인'


def recommendation_view(data: dict) -> dict:
    """Bounded comparison from existing, source-backed recommendation data.

    Never synthesizes a listing, verification or revenue claim. Does not change
    tool ranking, approval permissions or eligibility filters.
    """
    rows = data.get('ranked') or []
    if not isinstance(rows, list):
        rows = []
    cards = []
    for number, entry in enumerate(rows[:3], 1):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('title') or '제목 미확인')[:95]
        reasons = entry.get('reasons') if isinstance(entry.get('reasons'), list) else []
        risks = entry.get('risks') if isinstance(entry.get('risks'), list) else []
        dimensions = entry.get('risk_dimensions') if isinstance(entry.get('risk_dimensions'), list) else []
        assessments = entry.get('qualitative_assessments') if isinstance(entry.get('qualitative_assessments'), list) else []
        notes = [x for x in assessments if isinstance(x, dict) and x.get('verdict') in ('MATCH','MISMATCH')]
        uncertainty = entry.get('uncertainty_count')
        try:
            unverified = int(uncertainty) if uncertainty is not None else None
        except (TypeError, ValueError):
            unverified = None
        reason = str(reasons[0])[:160] if reasons else '적합 이유의 근거 확인 필요'
        risk = str(risks[0])[:160] if risks else '구체적인 위험 근거 확인 필요'
        label = str(entry.get('risk_label') or '판단 자료 부족')[:55]
        cards.append({
            'number': number, 'listing_id': str(entry.get('listing_id') or ''),
            'title': title, 'price': _price(entry.get('price_krw')),
            'reason': reason, 'risk': risk, 'risk_label': label,
            'unverified': unverified,
            'base_score': entry.get('base_score', entry.get('score')),
            'score': entry.get('score'),
            'adjustment': entry.get('qualitative_adjustment', 0),
            'assessments': notes[:3], 'dimensions': [d for d in dimensions[:7] if isinstance(d, dict)],
        })
    comparison = [{
        '후보': f"{x['number']}. {x['title'][:28]}",
        '가격': x['price'],
        '맞는 이유': x['reason'][:49],
        '확인할 점': x['risk'][:49],
    } for x in cards]
    return {'cards': cards, 'comparison': comparison,
            'eligible': data.get('eligible_count', len(cards)),
            'qualitative': bool(data.get('qualitative_preferences'))}
