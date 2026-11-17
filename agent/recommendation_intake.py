"""Conversational recommendation intake, shared by OpenAI and local tool mode.

Only user-provided criteria (or explicitly accepted defaults) can start a
recommendation. This module does not call an LLM, does not persist profiles on
server disk, and never sees API credentials.
"""
import re

RECOMMEND_REQUEST = re.compile(r"추천|골라\s*줘|맞춤\s*선정|조건에\s*맞는\s*프로젝트|적합한\s*프로젝트")
CANCEL_REQUEST = re.compile(r"^(?:취소|그만|중단|추천\s*취소|다음에\s*할게)[!\s.]*$")
SKIP_REQUEST = re.compile(r"^(?:잘\s*모르겠(?:어|어요|습니다)?|모름|모르겠어|기본(?:값|\s*조건)?으로(?:\s*진행)?|생략|상관없어|아무거나)[.!\s]*$")
MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억\s*원|천만\s*원|백만\s*원|만\s*원|천\s*원|억|천만|백만|만원|천원|만|원)")
TECH = ["Python", "FastAPI", "React", "TypeScript", "JavaScript", "Vue", "Django", "Flutter", "Java", "Spring", "Node.js", "PHP", "Next.js", "Kotlin", "Swift"]
TECH_ALIASES = {"파이썬":"Python", "리액트":"React", "자바스크립트":"JavaScript", "타입스크립트":"TypeScript", "장고":"Django", "플러터":"Flutter", "스프링":"Spring", "자바":"Java"}
CATEGORY_TERMS = [
    ("웹서비스", ["web_app", "saas"]), ("웹앱", ["web_app", "saas"]),
    ("웹사이트", ["web_app"]), ("SaaS", ["saas"]),
    ("게임", ["game"]), ("모바일앱", ["mobile_app"]), ("모바일 앱", ["mobile_app"]),
    ("CLI", ["desktop_tool"]), ("자동화 도구", ["desktop_tool"]),
    ("데스크톱", ["desktop_tool"]),
]


def _money_value(match):
    unit = match.group(2).replace(' ', '')
    multiplier = {'억': 100000000, '억원': 100000000, '천만': 10000000,
                  '천만원': 10000000, '백만': 1000000, '백만원': 1000000,
                  '만': 10000, '만원': 10000, '천원': 1000, '천': 1000,
                  '원': 1}[unit]
    return int(float(match.group(1).replace(',', '')) * multiplier)


def _price_criteria(text, profile):
    """Keep purchase budget separate from monthly operating expenses.

    A line such as '예산 80만원, 월 운영비 5만원' must never set the
    acquisition budget to 5만원. Amounts with no currency units are ignored.
    """
    monthly_prefix = re.compile(
        r'(?:월\s*(?:운영비|유지비|비용|구독료|지출)|월별\s*(?:비용|운영비)|매달\s*(?:운영비|비용|유지비)?|월\s*최대)'
        r'[^\d,;:.]{0,15}$', re.I)
    purchase_prefix = re.compile(r'(?:구매\s*예산|인수\s*예산|예산|구매\s*금액|인수\s*금액|상한|최대|가격)'
                                 r'[^\d,;:.]{0,12}$', re.I)
    purchase = []
    monthly = []
    for match in MONEY.finditer(text):
        value = _money_value(match)
        if not 0 < value <= 1000000000:
            continue
        prefix = text[max(0, match.start()-40):match.start()]
        if monthly_prefix.search(prefix):
            monthly.append(value)
        else:
            purchase.append((value, bool(purchase_prefix.search(prefix))))
    if purchase:
        explicit = [v for v, labeled in purchase if labeled]
        profile['max_budget_krw'] = (explicit or [v for v, _ in purchase])[-1]
    if monthly:
        profile['max_monthly_cost_krw'] = monthly[-1]


def _risk_value(text, waiting=''):
    """Interpret Korean risk expressions without joining word boundaries.

    Collapsing whitespace used to turn '중급이고 위험...' into a false
    '고위험' match. Prefer clear stated constraints; otherwise ask.
    """
    s = re.sub(r'\s+', ' ', text.lower()).strip()
    low = (
        r'저\s*위험|보수적|안전|안정|위험\s*최소|리스크\s*최소|'
        r'(?:위험|리스크)\s*(?:은|는|이|가|도|을|를)?\s*(?:낮|적|작|싫|없|줄이)|'
        r'(?:낮|적|작)\w*\s*(?:위험|리스크)|'
        r'(?:위험|리스크)\s*부담\s*(?:없|적)|'
        r'위험을\s*피하|리스크를\s*피하|(?:위험|리스크)\s*감수\s*(?:적|낮|못|안)'
    )
    high = (
        r'고위험|높은\s*위험|높은\s*리스크|'
        r'(?:위험|리스크)\s*(?:은|는|이|가|도)?\s*(?:높|크|많)\w*\s*(?:괜찮|감수|상관없)|'
        r'위험\s*감수|리스크\s*감수|공격적|도전적'
    )
    medium = r'중위험|중간\s*위험|보통\s*(?:위험|리스크)|위험\s*보통|리스크\s*보통'
    if re.search(low, s):
        return 'LOW'
    if re.search(high, s):
        return 'HIGH'
    if re.search(medium, s):
        return 'MEDIUM'
    if waiting == 'risk_tolerance':
        if re.fullmatch(r'(?:낮\w*|적\w*|작\w*|싫\w*|안전\w*|보수적\w*)[.!?\s]*', s):
            return 'LOW'
        if re.fullmatch(r'(?:보통|중간|중간정도|적당히)[.!?\s]*', s):
            return 'MEDIUM'
        if re.fullmatch(r'(?:높\w*|크\w*|많\w*|공격적\w*|감수할\s*수\s*있어)[.!?\s]*', s):
            return 'HIGH'
    return None


def _extract(text, profile, waiting=''):
    s = text.lower().replace(' ', '')
    if any(k in s for k in ('수익', '매출', '돈벌', '부업', '수익화', '소득')):
        profile['objective'] = '수익 창출 및 운영'
    elif any(k in s for k in ('학습', '배우', '공부', '연습', '공부용')):
        profile['objective'] = '개발 학습'
    elif '포트폴리오' in s:
        profile['objective'] = '포트폴리오 제작'
    elif any(k in s for k in ('재판매', '되팔', '엑싯')):
        profile['objective'] = '인수 후 개선·재판매'
    elif any(k in s for k in ('직접운영', '운영하고', '서비스운영', '운영할', '창업')):
        profile['objective'] = '서비스 운영'

    _price_criteria(text, profile)

    # Avoid treating JavaScript as a request for Java, for example.
    stacks = []
    for tech in TECH:
        pattern = r'(?<![a-z])' + re.escape(tech.lower()) + r'(?![a-z])'
        if re.search(pattern, text.lower()):
            stacks.append(tech)
    for alias, canonical in TECH_ALIASES.items():
        if alias in text.lower() and canonical not in stacks:
            stacks.append(canonical)
    if stacks:
        profile['preferred_tech_stack'] = stacks[:10]
        # A requested project technology is a strict filter. Merely saying the
        # user has experience with it is not the same as requiring that stack.
        strict = bool(re.search(
            r'(?:\b(?:python|react|vue|django)\b|파이썬|리액트|장고|스프링).{0,17}(?:프로젝트|기반|사용한|만든|개발된|필수|만\s*추천|으로\s*만든|으로\s*개발)|'
            r'(?:프로젝트|필수|반드시|꼭).{0,16}(?:\b(?:python|react|vue|django)\b|파이썬|리액트|장고|스프링)',
            text, re.I))
        # Mentioning skill ('파이썬 중급') is not a hard requirement.
        # But '파이썬 중급, Python 프로젝트 추천' *is* explicit.
        explicit_target = re.search(
            r'(?:\b(?:python|react|vue|django)\b|파이썬|리액트|장고|스프링)\s*'
            r'(?:기반|프로젝트|웹앱|으로\s*(?:개발|만든))|'
            r'(?:프로젝트|웹앱)\s*(?:는|은|중에)?\s*'
            r'(?:\b(?:python|react|vue|django)\b|파이썬|리액트|장고|스프링)',
            text, re.I)
        mentions_skill = re.search(
            r'(?:\b(?:python|react|vue|django)\b|파이썬|리액트|장고).{0,8}'
            r'(?:중급|초급|고급|경험|할\s*줄)', text, re.I)
        if mentions_skill and not explicit_target and not re.search(
                r'(?:기반|만든|사용한)\s*프로젝트|필수|만\s*추천|꼭\s*해당', text):
            strict = False
        if explicit_target:
            strict = True
        profile['require_preferred_stack'] = strict

    for label, categories in CATEGORY_TERMS:
        if label.lower().replace(' ', '') in s:
            profile['preferred_categories'] = categories
            break

    if any(x in s for x in ('초보', '입문', '개발경험없', '개발못', '개발안해', '개발처음', '코딩못')):
        profile['skill_level'] = 'NONE'
    elif any(x in s for x in ('기초', '기본수준', '초급', '개발약간')):
        profile['skill_level'] = 'BASIC'
    elif any(x in s for x in ('중급', '어느정도', '중간수준')):
        profile['skill_level'] = 'INTERMEDIATE'
    elif any(x in s for x in ('고급', '숙련', '전문가', '시니어')):
        profile['skill_level'] = 'ADVANCED'
    elif waiting == 'skill_level' and s in ('조금', '약간', '기본만', '기초정도'):
        profile['skill_level'] = 'BASIC'

    risk = _risk_value(text, waiting)
    if risk:
        profile['risk_tolerance'] = risk


def _profile_summary(p):
    labels = []
    if p.get('objective'):
        labels.append('목적: ' + str(p['objective'])[:40])
    if p.get('max_budget_krw'):
        labels.append('예산: {:,}원 이하'.format(p['max_budget_krw']))
    if p.get('skill_level'):
        labels.append('개발 수준: ' + {'NONE':'초보', 'BASIC':'기초', 'INTERMEDIATE':'중급', 'ADVANCED':'고급'}.get(p['skill_level'], '확인 필요'))
    if p.get('risk_tolerance'):
        labels.append('위험 허용: ' + {'LOW':'낮음', 'MEDIUM':'보통', 'HIGH':'높음'}.get(p['risk_tolerance'], '확인 필요'))
    if p.get('preferred_tech_stack'):
        stack_text = ', '.join(p['preferred_tech_stack'][:3])
        labels.append(('필수 기술: ' if p.get('require_preferred_stack') else '익숙한 기술: ') + stack_text)
    if p.get('max_monthly_cost_krw') is not None:
        labels.append('월 운영비: {:,}원 이하'.format(p['max_monthly_cost_krw']))
    if p.get('qualitative_preferences'):
        labels.append('추가 선호: ' + ', '.join(p['qualitative_preferences'][:2]))
    return ' · '.join(labels)


def _missing_question(p):
    if not p.get('objective'):
        return ('**어떤 목적으로 프로젝트를 인수하고 싶으세요?**\n\n'
                '예: 직접 운영해 수익 창출, 개발 학습, 포트폴리오, 개선 후 재판매. 원하는 분야나 형태도 함께 알려줘.')
    if not p.get('max_budget_krw'):
        return ('**구매 예산의 상한은 얼마인가요?**\n\n'
                '예: 30만원, 80만원, 100만원. 금액 단위를 포함해 알려줘.')
    if not p.get('skill_level'):
        return ('**프로젝트를 직접 수정·운영할 개발 경험은 어느 정도인가요?**\n\n'
                '초보 / 기초 / 중급 / 고급 중 하나로 답하거나, 잘 모르겠으면 **모름**이라고 해줘.')
    if not p.get('risk_tolerance'):
        return ('**어느 정도 위험까지 받아들일 수 있나요?**\n\n'
                '보수적(낮은 위험) / 보통 위험 / 고위험 감수 중 선택해줘. '
                '잘 모르겠으면 **모름**이라고 답할 수 있어.')
    return ''


def _create_args(p):
    args = {'max_budget_krw': p['max_budget_krw'], 'objective': p['objective'],
            'skill_level': p['skill_level'], 'risk_tolerance': p['risk_tolerance'],
            'preferred_tech_stack': p.get('preferred_tech_stack', []),
            'require_preferred_stack': p.get('require_preferred_stack', False),
            'preferred_categories': p.get('preferred_categories', []), 'max_results': 3}
    if 'max_monthly_cost_krw' in p:
        args['max_monthly_cost_krw'] = p['max_monthly_cost_krw']
    if p.get('qualitative_preferences'):
        args['qualitative_preferences'] = p['qualitative_preferences'][:5]
    return args


def advance(message, context):
    """Return None if unrelated; else {'message':...} or {'args':...}.

    The ongoing intake lives only inside the per-conversation Streamlit session.
    Explicit user omissions are annotated; otherwise no defaults are inserted.
    """
    state = context.get('recommendation_intake')
    interested = bool(RECOMMEND_REQUEST.search(message))
    if not state and not interested:
        return None
    if state and CANCEL_REQUEST.match(message.strip()):
        context.pop('recommendation_intake', None)
        return {'message': '맞춤 추천 조건 입력을 취소했어. 다른 요청을 해줘.'}
    # An independent tool request should not be swallowed by an ongoing form.
    if state and not interested and re.search(r'(?:매물\s*(?:목록|검색)|최근\s*작업|작업\s*기록|제안\s*내역)', message):
        return None
    if not state:
        state = {'profile': {}, 'waiting': ''}
        context['recommendation_intake'] = state
    p = state['profile']
    if SKIP_REQUEST.match(message.strip()) and state['waiting'] in ('skill_level', 'risk_tolerance'):
        field = state['waiting']
        p[field] = 'BASIC' if field == 'skill_level' else 'MEDIUM'
        p.setdefault('assumptions', []).append('개발 수준: 기초 가정' if field == 'skill_level' else '위험 허용: 보통 가정')
    else:
        _extract(message, p, state['waiting'])
        if state['waiting'] == 'objective' and not p.get('objective') and not interested and len(message.strip()) >= 3:
            # A free-text purpose should not be thrown away simply because it
            # does not match one of the example keywords.
            p['objective'] = message.strip()[:90]
    question = _missing_question(p)
    if question:
        for field in ('objective','max_budget_krw','skill_level','risk_tolerance'):
            if not p.get(field):
                state['waiting'] = field
                break
        known = _profile_summary(p)
        reply = ('**확인한 조건:** ' + known + '\n\n' if known else '') + question
        return {'message': reply}
    context['confirmed_recommendation'] = dict(p)
    context.pop('recommendation_intake', None)
    return {'args': _create_args(p), 'assumptions': p.get('assumptions', []),
            'criteria_summary': _profile_summary(p)}


def from_saved_profile(payload):
    """Whitelist the user's own platform buyer profile after authenticated GET.

    Missing/invalid values are NOT guessed. The dialog asks for them instead.
    """
    if not isinstance(payload, dict):
        return {}
    p = {}
    budget = payload.get('max_budget_krw')
    if isinstance(budget, int) and not isinstance(budget, bool) and 0 < budget <= 1000000000:
        p['max_budget_krw'] = budget
    objectives = payload.get('objectives')
    if isinstance(objectives, list) and objectives and isinstance(objectives[0], str):
        p['objective'] = objectives[0][:90]
    if payload.get('skill_level') in ('NONE', 'BASIC', 'INTERMEDIATE', 'ADVANCED'):
        p['skill_level'] = payload['skill_level']
    if payload.get('risk_tolerance') in ('LOW', 'MEDIUM', 'HIGH'):
        p['risk_tolerance'] = payload['risk_tolerance']
    stack = payload.get('preferred_tech_stack')
    if isinstance(stack, list):
        p['preferred_tech_stack'] = [x[:40] for x in stack[:10] if isinstance(x, str)]
    cost = payload.get('max_monthly_cost_krw')
    if isinstance(cost, int) and not isinstance(cost, bool) and cost >= 0:
        p['max_monthly_cost_krw'] = cost
    return p
