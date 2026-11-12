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
    preferred = set(s.lower() for s in preferences.get('preferred_tech_stack', []))
    difficulty = {'NONE': 0, 'BASIC': 1, 'INTERMEDIATE': 2, 'ADVANCED': 3}
    excluded = []
    ranked = []
    for listing in listings:
        reasons_excluded = []
        if listing.get('status') != 'ACTIVE' or (demo_only and not listing.get('is_demo', False)):
            reasons_excluded.append('비활성 또는 허용되지 않은 매물')
        if listing['price_krw'] > max_budget or listing['price_krw'] < min_budget:
            reasons_excluded.append('예산 범위 밖')
        cost = listing.get('monthly_cost_estimate_krw')
        if max_cost is not None and cost is not None and cost > max_cost:
            reasons_excluded.append('월 운영비 상한 초과')
        known_defects = listing.get('known_defects') or []
        if risk == 'LOW' and any('유료 외부 API 비용' in d for d in known_defects):
            reasons_excluded.append('저위험 조건에 부적합한 고비용 결함')
        if reasons_excluded:
            excluded.append({'listing_id': listing['id'], 'reasons': reasons_excluded})
            continue
        stack = set(s.lower() for s in listing.get('tech_stack', []))
        stack_match = bool(preferred & stack) if preferred else True
        complicated = bool({'react', 'kubernetes', 'next.js'} & stack) or listing['category'] in ('saas', 'ai_agent')
        possible = not complicated or difficulty.get(skill, 0) >= 2
        verified = listing.get('verification_status') in ('STATIC_CHECKED', 'EXECUTION_CHECKED')
        repair_easy = len(known_defects) == 0
        score = (35 if stack_match else 12) + (30 if possible else 8) + (20 if verified else 5) + (15 if repair_easy else 4)
        reasons = []
        if listing['price_krw'] <= max_budget:
            reasons.append('예산 상한 이내({:,}원)'.format(listing['price_krw']))
        if stack_match:
            reasons.append('선호 기술과 일치')
        if possible:
            reasons.append('현재 기술 수준에서 상대적으로 관리 가능하다고 추정')
        risks = []
        if not possible:
            risks.append('기술 수준 대비 복잡도가 높을 가능성')
        if known_defects:
            risks.append('판매자 고지 결함: ' + '; '.join(known_defects[:2]))
        if not verified:
            risks.append('운영 및 권리 이전 여부 미검증')
        if cost is None:
            risks.append('월 운영비 자료 없음')
        ranked.append({'listing_id': listing['id'], 'title': listing['title'],
                       'price_krw': listing['price_krw'], 'score': score,
                       'reasons': reasons[:3], 'risks': risks, 'verified': verified,
                       'sale_rights_type': listing['sale_rights_type'],
                       'lifecycle_status': listing['lifecycle_status'],
                       'observed_vs_inferred': '가격/스택/고지결함: 판매자 정보, 점수/운영 난이도: 규칙 기반 추정'})
    ranked.sort(key=lambda i: (-i['score'], i['price_krw'], i['listing_id']))
    return {'ranked': ranked, 'excluded': excluded, 'count': len(ranked),
            'rule_version': 'static-rules-v0.1', 'is_demo': demo_only}


def metadata_findings(listing):
    findings = []
    for i, defect in enumerate(listing.get('known_defects') or [], 1):
        findings.append({'finding_id': 'SELLER-{:03d}'.format(i), 'severity': 'MEDIUM',
                         'title': '판매자 고지 결함: ' + defect[:140], 'status': 'INFERRED',
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
