"""Bounded, resumable, evidence-first multi-step marketplace workflows.

This module NEVER authorizes a marketplace mutation. Offer preparation only
prepares an explicitly confirmed platform draft when the integration is enabled.
It does not issue arbitrary model-selected tool calls or execute source code.
"""
import copy
import re
import uuid
from typing import Literal

from pydantic import BaseModel

from agent.tools import ToolDispatcher, ToolEvent
from core.policy import metadata_findings
from core.llm_service import contains_obvious_secret
from agent.llm_intake import _amount_supported, _valid_quote

STEP_LABEL = {
    'recommend': '조건에 맞는 매물 탐색·추천',
    'compare': '상위 후보 비교',
    'inspect': '우선 후보 공개 자료 점검',
    'prepare_offer': '구매 제안 초안 준비',
    'verify': '원래 요청 충족 여부 확인',
}
STEP_MAX = 5


class WorkflowIntent(BaseModel):
    """LLM classifies *task composition*, never permission or verified facts."""
    multi_step: bool
    compare: bool
    inspect: bool
    prepare_offer: bool
    candidate_count: int
    offer_price_krw: int | None
    offer_quote: str | None


class WorkflowAmount(BaseModel):
    intent: Literal['amount', 'other', 'cancel']
    price_krw: int | None
    evidence_quote: str | None


WORKFLOW_PROMPT = """당신은 ProjectAgain 사용자 목표를 단계로 분해하는 분류기입니다.
사용자가 한 번의 목표에서 *추천/탐색 이후* 비교, 공개 자료 검토, 구매 제안 초안 준비 중 하나 이상을 명시하면 multi_step=true로 하세요.
단순 추천 한 가지만 요청하면 false입니다. 요청하지 않은 단계는 false입니다.
후보 개수는 명시된 숫자를 따르되 1~3만 지원합니다. 누락 시 3.
제안 가격과 구매 예산은 별개입니다. '50만원 이하 찾아서 제안 준비'의 50만원은 제안 가격이 아닙니다.
구매 제안 금액을 사용자가 명시한 경우에만 offer_price_krw, offer_quote(가장 최근 메시지의 정확한 원문 구절)을 채우세요. 그 외에는 null.
도구 호출이나 거래 변경 권한은 분류기에 없습니다. 매물명/위험/수익을 지어내지 마세요.
"""


AMOUNT_PROMPT = """현재 사용자는 구매 제안 초안을 준비하기 위한 *제안 금액* 질문에 답하고 있습니다.
최신 메시지에 직접 제안 금액을 명시한 경우만 amount. evidence_quote는 해당 금액의 정확한 원문 인용.
취소 요청은 cancel. 관련 없는 새 요청은 other. 구매 예산과 자동으로 동일한 금액으로 처리하면 안 됩니다.
"""


def recognize_workflow(model, message):
    """Only an OpenAI structured response can opt into a multi-step plan."""
    from langchain_core.messages import SystemMessage, HumanMessage
    value = model.with_structured_output(WorkflowIntent, method='json_schema', strict=True).invoke([
        SystemMessage(content=WORKFLOW_PROMPT), HumanMessage(content=message[:2000])
    ])
    if isinstance(value, dict):
        value = WorkflowIntent.model_validate(value)
    if not isinstance(value, WorkflowIntent) or not value.multi_step:
        return None
    stages = ['recommend']
    if value.compare:
        stages.append('compare')
    if value.inspect:
        stages.append('inspect')
    if value.prepare_offer:
        stages.append('prepare_offer')
    if len(stages) == 1:
        return None
    stages.append('verify')
    amount = value.offer_price_krw
    # A search budget ('50만원 이하') is NOT an offer amount. The first
    # multistep turn must explicitly associate its quoted amount with an
    # offer. Follow-up amounts are separately validated in read_offer_amount.
    quote = value.offer_quote or ''
    explicit_offer_quote = (bool(re.search(r'제안|오퍼|입찰', quote)) and
                            not bool(re.search(r'예산|한도|이하|이내', quote)))
    valid_amount = (type(amount) is int and 0 < amount <= 1_000_000_000
                    and explicit_offer_quote
                    and _valid_quote(message, quote)
                    and _amount_supported(amount, quote))
    return create_plan(message, stages, count=value.candidate_count,
                       offer_price=amount if valid_amount else None)


def create_plan(goal, stages, *, count=3, offer_price=None):
    """Normalize LLM choices into immutable, allowlisted ordering."""
    allowed = [name for name in STEP_LABEL if name in stages]
    if not allowed or allowed[0] != 'recommend':
        raise ValueError('추천으로 시작하는 계획만 지원해요.')
    if 'verify' not in allowed:
        allowed.append('verify')
    if len(allowed) > STEP_MAX:
        raise ValueError('단계 수 제한을 초과했어요.')
    if contains_obvious_secret(goal):
        raise ValueError('비밀정보를 포함한 계획은 저장하지 않아요.')
    return {
        'id': str(uuid.uuid4()), 'goal': str(goal)[:1500], 'requested_count': max(1, min(3, int(count or 3))),
        'steps': [{'key': name, 'label': STEP_LABEL[name], 'status': 'PENDING', 'note': ''} for name in allowed],
        'status': 'ACTIVE', 'offer_price_krw': offer_price,
        'ranked': [], 'recommendation_criteria': {}, 'inspection': None,
        'offer_listing_id': None, 'remote_action_id': None, 'issues': [], 'verified': {}, 'version': 1,
    }


def _checkpoint(plan, context):
    """Persist only if the visitor opted in and *their own* principal was verified."""
    owner = context.get('_persist_owner')
    if owner:
        try:
            from core.workflow_store import save_workflow
            save_workflow(owner, plan)
        except Exception:
            # Storage loss must not turn a successful read-only workflow into
            # a failed business operation; the UI reports storage separately.
            plan['storage_warning'] = '저장소 접근 실패 · 현재 대화에서만 진행 상태 유지'


def _mark(plan, step, status, note, context):
    step['status'] = status
    step['note'] = str(note)[:350]
    _checkpoint(plan, context)


def _read_step(plan, name):
    return next((s for s in plan['steps'] if s['key'] == name), None)


def _end(plan, status, context):
    plan['status'] = status
    _checkpoint(plan, context)


def workflow_outline(plan):
    return '\n'.join('- {} {}{}'.format(
        {'PENDING':'○', 'RUNNING':'◌', 'COMPLETED':'✓', 'PARTIAL':'△',
         'WAITING_INPUT':'?', 'WAITING_APPROVAL':'◇', 'BLOCKED':'×',
         'FAILED':'×', 'INTERRUPTED':'↻', 'SKIPPED':'–'}.get(s['status'], '·'),
        s['label'], ' — ' + s['note'] if s.get('note') else '') for s in plan['steps'])


def _minimal_ranked(rows):
    safe = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        lid = str(row.get('listing_id') or '')
        try:
            uuid.UUID(lid)
        except ValueError:
            continue
        safe.append({
            'listing_id': lid, 'title': str(row.get('title') or '제목 미확인')[:100],
            'price_krw': row.get('price_krw'), 'score': row.get('score'),
            'base_score': row.get('base_score', row.get('score')),
            'qualitative_adjustment': row.get('qualitative_adjustment', 0),
            'qualitative_assessments': [
                {'preference': str(x.get('preference') or '')[:100],
                 'verdict': str(x.get('verdict') or 'UNKNOWN')[:12],
                 'evidence_quote': str(x.get('evidence_quote') or '')[:130]}
                for x in (row.get('qualitative_assessments') or [])[:3] if isinstance(x, dict)],
            'reasons': [str(x)[:160] for x in (row.get('reasons') or [])[:3]],
            'risks': [str(x)[:160] for x in (row.get('risks') or [])[:4]],
            'risk_label': str(row.get('risk_label') or '미확인')[:35],
            'uncertainty_count': int(row.get('uncertainty_count') or 0),
            'risk_dimensions': [{'label': str(d.get('label') or '')[:35], 'status': str(d.get('status') or '')[:35],
                                 'explanation': str(d.get('explanation') or '')[:100]}
                                for d in (row.get('risk_dimensions') or [])[:7] if isinstance(d, dict)],
            'risk_checks': {str(k)[:30]: str(v)[:45] for k,v in
                            (row.get('risk_checks') or {}).items()} if isinstance(row.get('risk_checks'),dict) else {},
        })
    return safe


def _compare(rows, expected):
    """Brief narrative; structured event carries the evidence-rich comparison."""
    if not rows:
        return None
    actual = min(len(rows),expected)
    text = '**후보 {}건 비교** · 가격, 추천 근거, 위험 상태를 도구 결과에 정리했어.'.format(actual)
    if actual < expected:
        text += '\n\n요청한 {}건 중 {}건은 조건을 통과한 매물이 없어 채우지 않았어.'.format(expected,expected-actual)
    return text


def _safe_summary(event, formatter):
    return formatter(event)


def execute_plan(plan, context, actor_name, *, recommendation_input=None,
                 formatter, model=None, allow_resume=False):
    """Run bounded steps until user input, authorization, or an error blocks it.

    A step already COMPLETED/PARTIAL is NEVER invoked twice by resume.
    The plan holds factual snapshot IDs, not credentials or raw tool payloads.
    """
    from agent.qualitative_review import review_preferences_with_model
    from agent.tools import ToolDispatcher
    if not isinstance(plan, dict) or plan.get('status') in ('CANCELLED', 'COMPLETED'):
        return {'content': '진행 중인 작업 계획이 없어요.', 'events': [], 'pending': None, 'mode': 'workflow'}
    dispatcher = ToolDispatcher(actor_name, context)
    messages = []
    events = []
    pending = None
    max_operations = STEP_MAX
    for step in plan['steps'][:max_operations]:
        kind = step['key']
        if step['status'] in ('COMPLETED', 'PARTIAL', 'SKIPPED', 'WAITING_APPROVAL', 'BLOCKED'):
            continue
        if step['status'] == 'RUNNING' and not allow_resume:
            step['status'] = 'INTERRUPTED'
        if step['status'] == 'FAILED' and not allow_resume:
            break
        if step['status'] == 'FAILED' and allow_resume:
            _mark(plan, step, 'PENDING', '사용자 요청으로 재시도', context)
        if kind == 'recommend' and not recommendation_input:
            _mark(plan, step, 'WAITING_INPUT', '추천 조건 확인 필요', context)
            _end(plan, 'WAITING_INPUT', context)
            break
        from core.config import ENABLE_LIVE_DRAFTS
        if kind == 'prepare_offer' and not ENABLE_LIVE_DRAFTS:
            _mark(plan, step, 'BLOCKED', 'Live에서는 제안 생성·전송 불가', context)
            plan['issues'].append('실플랫폼에서 제안 준비 단계는 현재 읽기 전용 정책으로 차단됨')
            messages.append('**제안 단계 제한:** Live 모드는 읽기 전용이므로 거래 관련 초안을 생성하거나 전송하지 않았어.')
            continue
        if kind == 'prepare_offer' and not plan.get('offer_price_krw'):
            _mark(plan, step, 'WAITING_INPUT', '구매 제안 금액 필요', context)
            _end(plan, 'WAITING_OFFER_PRICE', context)
            messages.append('가장 적합한 후보에 **얼마로 제안할까요?** 구매 예산과 제안 가격은 별개라서 확인이 필요해.')
            break
        attempts = int(step.get('attempts') or 0)
        if attempts >= 3:
            _mark(plan, step, 'BLOCKED', '재시도 한도 도달 · 새 계획 또는 수동 검토 필요', context)
            plan.setdefault('issues', []).append('{} 단계 재시도 한도 도달'.format(step['label']))
            _end(plan, 'PARTIAL', context)
            break
        step['attempts'] = attempts + 1
        _mark(plan, step, 'RUNNING', '도구/검사 실행 중', context)
        try:
            if kind == 'recommend':
                event, pending = dispatcher.invoke('recommend_listings', recommendation_input['args'])
                events.append(event.to_dict())
                if not event.success:
                    _mark(plan, step, 'FAILED', event.summary, context)
                    messages.append(_safe_summary(event, formatter))
                    _end(plan, 'FAILED', context)
                    break
                if model and recommendation_input.get('qualitative_preferences'):
                    try:
                        review_preferences_with_model(model, event.data, recommendation_input['qualitative_preferences'])
                    except Exception:
                        plan['issues'].append('AI 정성 비교를 완료하지 못함; 정량 기준만 사용')
                plan['ranked'] = _minimal_ranked(event.data.get('ranked') or [])
                plan['recommendation_criteria'] = copy.deepcopy(context.get('last_recommendation_profile') or {})
                context['recent_listings'] = [{'id': x['listing_id'], 'title': x['title']} for x in plan['ranked']]
                _mark(plan, step, 'COMPLETED', '{}건 후보'.format(len(plan['ranked'])), context)
                messages.append(_safe_summary(event, formatter))
                if not plan['ranked']:
                    plan['issues'].append('검증 기준에 부합하는 후보 0건')
                    for next_step in plan['steps']:
                        if next_step['key'] in ('compare', 'inspect', 'prepare_offer'):
                            _mark(plan, next_step, 'SKIPPED', '추천 후보 없음', context)
            elif kind == 'compare':
                text = _compare(plan['ranked'], plan['requested_count'])
                if text is None:
                    _mark(plan, step, 'SKIPPED', '비교할 후보 없음', context)
                    continue
                actual = len(plan['ranked'])
                _mark(plan, step, 'COMPLETED' if actual >= plan['requested_count'] else 'PARTIAL',
                      '{} / {}건 비교'.format(actual, plan['requested_count']), context)
                if actual < plan['requested_count']:
                    plan['issues'].append('비교 요청 {}건 중 {}건만 확보'.format(plan['requested_count'], actual))
                messages.append(text)
                events.append(ToolEvent('compare', '후보 비교', True, '{}건 비교'.format(actual),
                                        {'count': actual, 'requested': plan['requested_count'],
                                         'ranked': copy.deepcopy(plan['ranked'][:actual])}).to_dict())
            elif kind == 'inspect':
                if not plan['ranked']:
                    _mark(plan, step, 'SKIPPED', '분석할 후보 없음', context)
                    continue
                selected = plan['ranked'][0]
                lid = selected['listing_id']
                # Reuse the same audited read-only inspection tool as normal chat.
                event, _ = dispatcher.invoke('inspect_listing', {'listing': lid})
                events.append(event.to_dict())
                if not event.success:
                    _mark(plan, step, 'FAILED', event.summary, context)
                    messages.append(_safe_summary(event, formatter))
                    _end(plan, 'FAILED', context)
                    break
                report = event.data.get('report') or {}
                plan['inspection'] = {'listing_id': lid, 'verdict': str(report.get('verdict') or 'UNKNOWN'),
                    'coverage': str(report.get('coverage') or '공개 정보 정적 검사')[:170],
                    'finding_count': len(report.get('findings') or []),
                    'dynamic_execution': 'NOT_TESTED'}
                _mark(plan, step, 'COMPLETED', '공개 정보 정적 점검 · 실행 미검증', context)
                messages.append(_safe_summary(event, formatter))
            elif kind == 'prepare_offer':
                if not plan['ranked']:
                    _mark(plan, step, 'SKIPPED', '제안할 후보 없음', context)
                    continue
                selected = plan['ranked'][0]
                if plan.get('offer_listing_id') and plan['offer_listing_id'] != selected['listing_id']:
                    _mark(plan, step, 'FAILED', '추천 대상 변경됨: 사용자 재확인 필요', context)
                    _end(plan, 'FAILED', context)
                    break
                plan['offer_listing_id'] = selected['listing_id']
                event, pending = dispatcher.invoke('prepare_offer', {
                    'listing': selected['listing_id'],
                    'price_krw': plan['offer_price_krw'],
                    'message': '프로젝트 공개 정보 확인과 추후 인수 조건 협의를 전제로 구매 제안드립니다.',
                })
                events.append(event.to_dict())
                if not event.success:
                    _mark(plan, step, 'FAILED', event.summary, context)
                    messages.append(_safe_summary(event, formatter))
                    _end(plan, 'FAILED', context)
                    break
                # Bind the approval card to the exact plan; an unrelated
                # approval action must never satisfy this workflow step.
                if pending is not None:
                    pending['workflow_id'] = plan['id']
                _mark(plan, step, 'WAITING_APPROVAL',
                      '플랫폼 초안 제출 확인 대기', context)
                messages.append(_safe_summary(event, formatter))
            elif kind == 'verify':
                result = verify_plan(plan)
                plan['verified'] = result
                _mark(plan, step, 'COMPLETED' if result['fulfilled'] else 'PARTIAL',
                      result['summary'], context)
                _end(plan, 'COMPLETED' if result['fulfilled'] else 'PARTIAL', context)
                messages.append('**작업 점검:** ' + result['summary'] + '\n' +
                                '\n'.join('- ' + item for item in result['issues'][:5]))
        except Exception:
            # A crash or remote outage cannot be interpreted as successful completion.
            _mark(plan, step, 'FAILED', '실행 오류 · 상세 정보는 노출하지 않음', context)
            _end(plan, 'FAILED', context)
            messages.append('**단계 실행 실패:** 중복 실행하지 않았어. 상태를 확인하고 재시도해 줘.')
            break
    if plan['status'] == 'ACTIVE':
        _end(plan, 'PARTIAL', context)
    return {'content': '\n\n'.join(messages) or '작업 상태를 확인했어.',
            'events': events, 'pending': pending, 'mode': 'workflow'}


def verify_plan(plan):
    steps = {x['key']: x['status'] for x in plan.get('steps', [])}
    issues = list(dict.fromkeys(plan.get('issues') or []))
    if steps.get('recommend') != 'COMPLETED' or not plan.get('ranked'):
        issues.append('조건을 만족하는 추천 후보가 확인되지 않음')
    if 'compare' in steps and steps['compare'] != 'COMPLETED':
        issues.append('요청한 수의 후보를 모두 비교하지 못함')
    if 'inspect' in steps:
        if steps['inspect'] != 'COMPLETED':
            issues.append('우선 후보 공개 자료 점검을 완료하지 못함')
        else:
            issues.append('공개 자료 점검만 수행; 소스 실행·권리·수익 검증은 미완료')
    objective = str((plan.get('recommendation_criteria') or {}).get('objective') or '')
    if ('수익' in objective or '매출' in objective) and plan.get('ranked'):
        if not any(x.get('risk_checks',{}).get('revenue') == 'VERIFIED_CLAIM'
                   for x in plan.get('ranked') or []):
            issues.append('수익화 가능성은 판매자 주장과 자료를 구분해야 하며 검증된 매출 근거가 없음')
    if 'prepare_offer' in steps:
        if steps['prepare_offer'] == 'COMPLETED':
            issues.append('플랫폼의 제안 실행 상태는 확인됐지만 실제 결제·권리 이전·계약 효력은 별도 검증 필요')
        elif steps['prepare_offer'] != 'WAITING_APPROVAL':
            issues.append('구매 제안 초안 준비가 완료되지 않음')
        else:
            issues.append('플랫폼 초안 제출에는 사용자 확인이 필요하고, 승인·실행은 ProjectAgain 웹에서 별도로 수행')
    fulfilled = (not issues and all(state == 'COMPLETED' for key, state in steps.items()
                                      if key != 'verify'))
    # Never claim an entire acquisition workflow is complete merely because tools returned 200.
    summary = '현재 계획의 수행 결과와 남은 확인 사항을 구분했어.'
    return {'fulfilled': fulfilled, 'summary': summary, 'issues': issues,
            'step_statuses': steps}


def read_offer_amount(model, message):
    from langchain_core.messages import SystemMessage, HumanMessage
    parsed = model.with_structured_output(WorkflowAmount, method='json_schema', strict=True).invoke([
        SystemMessage(content=AMOUNT_PROMPT), HumanMessage(content=message[:2000])])
    if isinstance(parsed, dict):
        parsed = WorkflowAmount.model_validate(parsed)
    if parsed.intent != 'amount':
        return parsed.intent, None
    amount = parsed.price_krw
    if (type(amount) is int and 0 < amount <= 1_000_000_000
            and _valid_quote(message, parsed.evidence_quote)
            and _amount_supported(amount, parsed.evidence_quote)):
        return 'amount', amount
    return 'invalid', None


def cancel_plan(plan, context):
    if plan:
        _end(plan, 'CANCELLED', context)
        context.pop('recommendation_intake', None)
        context.pop('confirmed_recommendation', None)
