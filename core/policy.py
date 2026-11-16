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


def recommendation(listings, preferences, demo_only=True):
    """Strict hard filters, followed by deterministic, inspectable ranking."""
    max_budget = int(preferences['max_budget_krw'])
    min_budget = int(preferences.get('min_budget_krw', 0))
    max_cost = preferences.get('max_monthly_cost_krw')
    skill = preferences['skill_level']
    risk = preferences['risk_tolerance']
    preferred = set(s.lower() for s in (preferences.get('preferred_tech_stack') or []) if isinstance(s, str))
    require_stack = bool(preferences.get('require_preferred_stack', False))
    categories = set(x.lower() for x in (preferences.get('preferred_categories') or []) if isinstance(x, str))
    objective = ' '.join(str(x) for x in (preferences.get('objectives') or [])).lower()
    max_results = max(1, min(5, int(preferences.get('max_results') or 3)))
    difficulty = {'NONE': 0, 'BASIC': 1, 'INTERMEDIATE': 2, 'ADVANCED': 3}
    excluded = []
    ranked = []
    for listing in listings:
        reasons_excluded = []
        if listing.get('status') != 'ACTIVE' or (demo_only and not listing.get('is_demo', False)):
            reasons_excluded.append('비활성 또는 허용되지 않은 매물')
        price = listing.get('price_krw')
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            reasons_excluded.append('가격 정보 누락 또는 형식 오류')
            price = None
        if price is not None and (price > max_budget or price < min_budget):
            reasons_excluded.append('예산 범위 밖')
        cost = listing.get('monthly_cost_estimate_krw')
        if max_cost is not None and isinstance(cost, (int, float)) and cost > max_cost:
            reasons_excluded.append('월 운영비 상한 초과')
        raw_stack = listing.get('tech_stack')
        stack = set(s.lower() for s in raw_stack if isinstance(s, str)) if isinstance(raw_stack, list) else set()
        if require_stack and preferred and not preferred.intersection(stack):
            reasons_excluded.append('필수 기술 조건 불일치')
        if categories and str(listing.get('category') or '').lower() not in categories:
            reasons_excluded.append('원하는 프로젝트 유형 불일치')
        known_value = listing.get('known_defects')
        known_defects = [str(x) for x in known_value if x is not None] if isinstance(known_value, list) else []
        if risk == 'LOW' and any('유료 외부 API 비용' in d for d in known_defects):
            reasons_excluded.append('저위험 조건에 부적합한 고비용 결함')
        if reasons_excluded:
            excluded.append({'listing_id': listing['id'], 'reasons': reasons_excluded})
            continue
        stack_match = bool(preferred & stack) if preferred else True
        complicated = bool({'react', 'kubernetes', 'next.js'} & stack) or str(listing.get('category') or '').lower() in ('saas', 'ai_agent')
        possible = not complicated or difficulty.get(skill, 0) >= 2
        verified = listing.get('verification_status') in ('STATIC_CHECKED', 'EXECUTION_CHECKED')
        repair_easy = len(known_defects) == 0
        score = (35 if stack_match else 12) + (30 if possible else 8) + (20 if verified else 5) + (15 if repair_easy else 4)
        # Buying purpose matters. Never equate seller revenue claims with verified
        # profit, and never claim that likely difficulty is objectively established.
        has_revenue = listing.get('has_revenue') is True
        revenue_verified = str(listing.get('revenue_claim_verification') or '').upper() in (
            'VERIFIED', 'DOCUMENT_VERIFIED', 'ADMIN_VERIFIED')
        lifecycle = str(listing.get('lifecycle_status') or '').upper()
        rights = str(listing.get('sale_rights_type') or '').upper()
        if '학습' in objective or '포트폴리오' in objective:
            score += 12 if possible else -8
            if isinstance(cost, (int, float)) and cost == 0:
                score += 5
        elif '수익' in objective or '매출' in objective:
            score += 20 if has_revenue and revenue_verified else (-7 if not has_revenue else 0)
        elif '운영' in objective:
            score += 12 if lifecycle in ('ACTIVE', 'LIVE', 'OPERATING', 'LAUNCHED') else -8
        elif '재판매' in objective:
            score += 15 if rights == 'FULL_IP_ASSIGNMENT' else -12

        reasons = []
        if price is not None and price <= max_budget:
            reasons.append('예산 상한 이내({:,}원)'.format(listing['price_krw']))
        if stack_match:
            reasons.append('선호 기술과 일치')
        if possible:
            reasons.append('현재 기술 수준에서 상대적으로 관리 가능하다고 추정')
        risks = []
        if ('수익' in objective or '매출' in objective) and not (has_revenue and revenue_verified):
            risks.append('검증된 수익 자료가 확인되지 않음 · 수익을 보장할 수 없습니다')
        if not possible:
            risks.append('기술 수준 대비 복잡도가 높을 가능성')
        if known_defects:
            risks.append('판매자 고지 결함: ' + '; '.join(known_defects[:2]))
        if not verified:
            risks.append('운영 및 권리 이전 여부 미검증')
        if cost is None:
            risks.append('월 운영비 자료 없음')
        ranked.append({'listing_id': listing['id'], 'title': listing.get('title') or '제목 미확인',
                       'price_krw': price, 'score': score,
                       'reasons': reasons[:3], 'risks': risks, 'verified': verified,
                       'sale_rights_type': listing.get('sale_rights_type') or '미확인',
                       'lifecycle_status': listing.get('lifecycle_status') or '미확인',
                       'observed_vs_inferred': '가격/스택/고지결함: 판매자 정보, 점수/운영 난이도: 규칙 기반 추정'})
    ranked.sort(key=lambda i: (-i['score'], i['price_krw'], i['listing_id']))
    eligible_count = len(ranked)
    ranked = ranked[:max_results]
    return {'ranked': ranked, 'excluded': excluded, 'count': len(ranked),
            'eligible_count': eligible_count,
            'rule_version': 'static-rules-v0.1', 'is_demo': demo_only}


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
            'evidence_refs': [], 'is_demo': True, 'dynamic_execution': 'NOT_TESTED'}


def offer_payload(listing, price, message, repair_requests=None, support_days=1):
    verify_amount(price)
    if not listing.get('is_demo') or listing.get('status') != 'ACTIVE':
        raise ValueError('활성 데모 매물에만 제안할 수 있습니다.')
    if not message or len(message) > 4000:
        raise ValueError('협상 메시지는 1~4000자여야 합니다.')
    terms = {'handover_deadline_days': 7,
             'seller_support_days': int(support_days),
             'repair_requests': repair_requests or [],
             'acceptance_criteria': ['허가된 환경의 기능 검증은 별도 완료 확인 필요'],
             'message': message}
    return {'listing_id': listing['id'], 'offered_price_krw': price,
            'terms': terms, 'expires_at': expiration_iso(), 'is_demo': True}
