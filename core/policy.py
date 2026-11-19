"""Reproducible, cost-free policy and negotiation. No LLM or price appraisals."""
import hashlib
import json
from datetime import datetime, timedelta, timezone


def canonical_json(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def payload_sha(payload):
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def expiration_iso(hours=24):
    # Deterministic expiry within a UTC day prevents duplicate form submits
    # from mutating the approved payload before idempotent POST processing.
    next_date = datetime.now(timezone.utc).date() + timedelta(days=2)
    return datetime(next_date.year, next_date.month, next_date.day, tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


def verify_amount(amount):
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
        raise ValueError('금액은 1원 이상의 원화 정수여야 합니다.')
    return amount


def _risk_assessment(listing, skill, risk, monthly_cap, objective):
    """Assess evidence gaps independently of any ranking/LLM opinions.

    An absence of disclosure or independent verification is UNKNOWN, never SAFE.
    LOW tolerance is interpreted conservatively; users can explicitly revise it.
    """
    stack_raw = listing.get('tech_stack')
    stack = {x.casefold() for x in stack_raw if isinstance(x, str)} if isinstance(stack_raw, list) else set()
    category = str(listing.get('category') or '').casefold()
    defects = listing.get('known_defects') if isinstance(listing.get('known_defects'), list) else []
    defects = [str(x)[:180] for x in defects if x is not None]
    verification = str(listing.get('verification_status') or 'UNVERIFIED').upper()
    cost = listing.get('monthly_cost_estimate_krw')
    rights = str(listing.get('sale_rights_type') or '').upper()
    # These are seller disclosures, not an independent inspection.
    high_complexity = bool({'kubernetes', 'docker swarm'} & stack) or category in ('saas', 'ai_agent')
    moderate_complexity = high_complexity or bool({'react', 'next.js'} & stack)
    skill_rank = {'NONE': 0, 'BASIC': 1, 'INTERMEDIATE': 2, 'ADVANCED': 3}.get(skill, 0)
    severe_words = ('노출', '유출', '보안 취약', '악성', '권리 분쟁', '저작권 침해',
                    '작동하지 않', '구동 불가', '유료 외부 API 비용', '높은 운영비')
    severe_defects = [d for d in defects if any(word in d for word in severe_words)]
    technical = 'ISSUE' if ((high_complexity and skill_rank <= 1) or
                            (moderate_complexity and skill_rank == 0)) else ('UNKNOWN' if not stack else 'REVIEW')
    operations = 'UNKNOWN' if cost is None or isinstance(cost, bool) or not isinstance(cost, (int, float)) else 'SELLER_REPORTED'
    if monthly_cap is not None and isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > monthly_cap:
        operations = 'ISSUE'
    rights_state = 'UNKNOWN' if not rights or rights in ('UNKNOWN', 'NOT_PROVIDED') else 'SELLER_REPORTED'
    if ('재판매' in objective or '엑싯' in objective) and rights not in ('FULL_IP_ASSIGNMENT',):
        rights_state = 'ISSUE' if rights else 'UNKNOWN'
    revenue_state = 'UNKNOWN' if listing.get('has_revenue') is not True else (
        'VERIFIED_CLAIM' if str(listing.get('revenue_claim_verification') or '').upper()
        in ('VERIFIED', 'DOCUMENT_VERIFIED', 'ADMIN_VERIFIED') else 'SELLER_REPORTED')
    checks = {'technical': technical, 'operations': operations,
              'revenue': revenue_state, 'rights': rights_state,
              'security': 'ISSUE' if severe_defects else 'UNKNOWN',
              'handover': 'UNKNOWN',
              'verification': 'STATIC_CHECKED' if verification == 'STATIC_CHECKED' else
                  'EXECUTION_CHECKED' if verification == 'EXECUTION_CHECKED' else 'UNKNOWN'}
    exclusions = []
    cautions = []
    if risk == 'LOW':
        if checks['verification'] == 'UNKNOWN':
            exclusions.append('독립 확인된 정적/실행 검사 자료가 없어 저위험 기준 미충족')
        if checks['technical'] == 'ISSUE':
            exclusions.append('현재 개발 경험 대비 기술·운영 복잡도가 높음')
        if checks['operations'] == 'UNKNOWN' and monthly_cap is not None:
            exclusions.append('월 운영비 상한 검증 불가: 운영비 미확인')
        if checks['rights'] == 'UNKNOWN':
            exclusions.append('판매자의 양도·이용허락 권리 범위 미확인')
        if checks['rights'] == 'ISSUE':
            exclusions.append('재판매 목적과 권리 범위가 불일치')
        if severe_defects:
            exclusions.append('심각한 미해결 결함 고지: ' + severe_defects[0][:70])
    # Not filtered? Important gaps must still be visible and lower score.
    if checks['verification'] == 'UNKNOWN':
        cautions.append('실행/정적 검사 여부 확인되지 않음')
    elif checks['verification'] == 'STATIC_CHECKED':
        cautions.append('정적 검사 표시만 확인됨 · 실제 구동은 별도 확인 필요')
    if checks['operations'] == 'UNKNOWN':
        cautions.append('월 운영비 미확인')
    if checks['rights'] == 'UNKNOWN':
        cautions.append('권리 범위 미확인')
    if checks['technical'] == 'ISSUE':
        cautions.append('개발 수준 대비 복잡도가 높음')
    if checks['security'] == 'UNKNOWN':
        cautions.append('보안 검증 자료 미확인')
    if checks['handover'] == 'UNKNOWN':
        cautions.append('인수인계 가능 여부 미확인')
    if revenue_state != 'VERIFIED_CLAIM' and ('수익' in objective or '매출' in objective):
        cautions.append('검증된 수익 자료 미확인')
    labels = {'technical':'기술 난이도', 'operations':'운영비', 'revenue':'수익 근거',
              'rights':'권리', 'security':'보안', 'handover':'인수인계', 'verification':'검증 상태'}
    dimensions = []
    for key, status in checks.items():
        if status == 'ISSUE':
            detail = '문제 또는 조건 불일치가 발견됨'
        elif status == 'UNKNOWN':
            detail = '판단할 자료가 없음 · 안전으로 판단하지 않음'
        elif status in ('SELLER_REPORTED','VERIFIED_CLAIM'):
            detail = '판매자 고지 또는 플랫폼 확인 표기 · 독립 검증 여부 확인 필요'
        elif status == 'STATIC_CHECKED':
            detail = '정적 검사 기록 · 실제 구동 별도 확인 필요'
        else:
            detail = '추가 검증 범위 확인 필요'
        dimensions.append({'key': key, 'label': labels[key], 'status': status,
                           'explanation': detail, 'source': '공개 매물 등록 정보'})
    issues = sum(x['status'] == 'ISSUE' for x in dimensions)
    unknown = sum(x['status'] == 'UNKNOWN' for x in dimensions)
    risk_label = ('문제 확인' if issues else '검증 부족' if unknown else '제한적 검토')
    return {'checks': checks, 'dimensions': dimensions, 'risk_label': risk_label,
            'issue_count': issues, 'exclusions': exclusions, 'cautions': cautions,
            'known_defects': defects, 'high_complexity': high_complexity,
            'moderate_complexity': moderate_complexity,
            'uncertainty_count': sum(x == 'UNKNOWN' for x in checks.values())}


def recommendation(listings, preferences):
    """First enforce factual constraints, then publish an auditable candidate pool.

    The optional LLM preference evaluation runs *after* this step and may not
    reinstate excluded listings or override risk gating.
    """
    max_budget = int(preferences['max_budget_krw'])
    min_budget = int(preferences.get('min_budget_krw', 0))
    max_cost = preferences.get('max_monthly_cost_krw')
    skill = preferences['skill_level']
    risk = preferences['risk_tolerance']
    preferred = {s.casefold() for s in (preferences.get('preferred_tech_stack') or []) if isinstance(s, str)}
    require_stack = bool(preferences.get('require_preferred_stack', False))
    categories = {x.casefold() for x in (preferences.get('preferred_categories') or []) if isinstance(x, str)}
    objective = ' '.join(str(x) for x in (preferences.get('objectives') or [])).lower()
    qualitative = [str(x)[:100] for x in (preferences.get('qualitative_preferences') or [])
                   if isinstance(x, str) and x.strip()][:5]
    max_results = max(1, min(5, int(preferences.get('max_results') or 3)))
    skill_rank = {'NONE': 0, 'BASIC': 1, 'INTERMEDIATE': 2, 'ADVANCED': 3}.get(skill, 0)
    excluded = []
    ranked = []
    for listing in listings:
        lid = str(listing.get('id') or '')
        if not lid:
            continue
        reasons_excluded = []
        if listing.get('status') != 'ACTIVE':
            reasons_excluded.append('비활성 또는 허용되지 않은 매물')
        price = listing.get('price_krw')
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            reasons_excluded.append('가격 정보 누락 또는 형식 오류')
            price = None
        if price is not None and (price > max_budget or price < min_budget):
            reasons_excluded.append('예산 범위 밖')
        cost = listing.get('monthly_cost_estimate_krw')
        if max_cost is not None and isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > max_cost:
            reasons_excluded.append('월 운영비 상한 초과')
        raw_stack = listing.get('tech_stack')
        stack = {s.casefold() for s in raw_stack if isinstance(s, str)} if isinstance(raw_stack, list) else set()
        if require_stack and preferred and not preferred.intersection(stack):
            reasons_excluded.append('필수 기술 조건 불일치')
        if categories and str(listing.get('category') or '').casefold() not in categories:
            reasons_excluded.append('원하는 프로젝트 유형 불일치')
        audit = _risk_assessment(listing, skill, risk, max_cost, objective)
        reasons_excluded.extend(audit['exclusions'])
        if reasons_excluded:
            excluded.append({'listing_id': lid, 'reasons': list(dict.fromkeys(reasons_excluded))[:7]})
            continue
        stack_match = bool(preferred & stack) if preferred else True
        possible = not audit['high_complexity'] or skill_rank >= 2
        verified = listing.get('verification_status') in ('STATIC_CHECKED', 'EXECUTION_CHECKED')
        repair_easy = len(audit['known_defects']) == 0
        score = (35 if stack_match else 12) + (30 if possible else 8) + (20 if verified else 5) + (15 if repair_easy else 4)
        # This is seller disclosure unless separately verified; do not promise returns.
        revenue_verified = (listing.get('has_revenue') is True and
            str(listing.get('revenue_claim_verification') or '').upper() in
            ('VERIFIED', 'DOCUMENT_VERIFIED', 'ADMIN_VERIFIED'))
        lifecycle = str(listing.get('lifecycle_status') or '').upper()
        rights = str(listing.get('sale_rights_type') or '').upper()
        if '학습' in objective or '포트폴리오' in objective:
            score += 12 if possible else -8
            if isinstance(cost, (int, float)) and cost == 0:
                score += 5
        elif '수익' in objective or '매출' in objective:
            score += 20 if revenue_verified else (-7 if not listing.get('has_revenue') else 0)
        elif '운영' in objective:
            score += 12 if lifecycle in ('ACTIVE', 'LIVE', 'OPERATING', 'LAUNCHED') else -8
        elif '재판매' in objective:
            score += 15 if rights == 'FULL_IP_ASSIGNMENT' else -12
        # Uncertainty penalizes ranking; uncertainty is never evidence of safety.
        score -= min(24, 4 * audit['uncertainty_count'])
        reasons = []
        if price is not None:
            reasons.append('예산 상한 이내({:,}원)'.format(price))
        if preferred and stack_match:
            reasons.append('선호 기술과 일치(판매자 등록 정보)')
        if possible:
            reasons.append('기술 수준과 대체로 부합할 가능성(규칙 추정)')
        risks = list(audit['cautions'])
        if audit['known_defects']:
            risks.append('판매자 고지 결함: ' + '; '.join(audit['known_defects'][:2]))
        row = {'listing_id': lid, 'title': str(listing.get('title') or '제목 미확인')[:150],
               'price_krw': price, 'score': score, 'base_score': score,
               'reasons': reasons[:3], 'risks': risks[:7], 'verified': verified,
               'risk_checks': audit['checks'], 'risk_dimensions': audit['dimensions'], 'risk_label': audit['risk_label'],
               'risk_issue_count': audit['issue_count'], 'uncertainty_count': audit['uncertainty_count'],
               'sale_rights_type': rights or '미확인',
               'lifecycle_status': lifecycle or '미확인',
               'observed_vs_inferred': '판매자 등록 정보와 독립 검증 구분 · 정량 점수는 규칙 기반 추정',
               # Only public, bounded fields may be forwarded for an optional qualitative review.
               'public_evidence': {
                   'description': str(listing.get('description') or '')[:500],
                   'tech_stack': sorted(stack)[:12],
                   'category': str(listing.get('category') or '')[:50],
                   'known_defects': audit['known_defects'][:3],
                   'monthly_cost_estimate_krw': cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
                   'verification_status': str(listing.get('verification_status') or 'UNKNOWN')[:40],
                   'has_revenue': listing.get('has_revenue') is True,
                   'sale_rights_type': rights or 'UNKNOWN',
                   'lifecycle_status': lifecycle or 'UNKNOWN'
               }}
        ranked.append(row)
    ranked.sort(key=lambda item: (-item['score'], item['price_krw'], item['listing_id']))
    eligible_count = len(ranked)
    candidates = ranked[:10]
    result = {'ranked': ranked[:max_results], 'candidate_pool': candidates,
              'excluded': excluded, 'count': min(max_results, eligible_count),
              'eligible_count': eligible_count, 'max_results': max_results,
              'qualitative_preferences': qualitative,
              'qualitative_review_status': 'NOT_RUN' if qualitative else 'NOT_REQUESTED',
              'rule_version': 'risk-aware-rules-v0.2', 'is_demo': False}
    return result


def metadata_findings(listing):
    findings = []
    known_defects = listing.get('known_defects')
    if not isinstance(known_defects, list):
        known_defects = []
    for i, defect in enumerate(known_defects, 1):
        findings.append({'finding_id': 'SELLER-{:03d}'.format(i), 'severity': 'MEDIUM',
                         'title': '판매자 고지 결함: ' + str(defect)[:140], 'status': 'INFERRED',
                         'evidence_refs': ['listing://{}/known_defects/{}'.format(listing['id'], i-1)],
                         'recommendation': '증빙 파일·재현 절차를 요청하세요. 고지 내용은 독립 검증되지 않았습니다.'})
    findings.append({'finding_id': 'SCOPE-001', 'severity': 'INFO',
                     'title': '실제 구동 및 이전 가능성은 검사되지 않음', 'status': 'UNKNOWN',
                     'evidence_refs': [], 'recommendation': '허가된 파일 정적 검사와 격리 실행이 별도로 필요합니다.'})
    return {'report_type': 'STATIC', 'verdict': 'UNVERIFIED', 'findings': findings,
            'evidence_refs': [], 'is_demo': bool(listing.get('is_demo', False)), 'dynamic_execution': 'NOT_TESTED'}
