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


def _money(text):
    matches = list(MONEY.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    unit = m.group(2).replace(' ', '')
    multiplier = {'억': 100000000, '억원': 100000000, '천만': 10000000, '천만원': 10000000,
                  '백만': 1000000, '백만원': 1000000, '만': 10000, '만원': 10000,
                  '천원': 1000, '천': 1000, '원': 1}[unit]
    return int(float(m.group(1).replace(',', '')) * multiplier)


def _extract(text, profile):
    s = text.lower().replace(' ', '')
    if '수익' in s or '매출' in s or '돈벌' in s:
        profile['objective'] = '수익 창출 및 운영'
    elif any(k in s for k in ('학습', '배우', '공부', '연습')):
        profile['objective'] = '개발 학습'
    elif '포트폴리오' in s:
        profile['objective'] = '포트폴리오 제작'
    elif any(k in s for k in ('재판매', '되팔', '엑싯')):
        profile['objective'] = '인수 후 개선·재판매'
    elif any(k in s for k in ('직접운영', '운영하고', '서비스운영', '창업')):
        profile['objective'] = '서비스 운영'

    val = _money(text)
    if val is not None and 0 < val <= 1000000000:
        profile['max_budget_krw'] = val

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
        strict = bool(re.search(r"프로젝트|기반|사용한|만든|개발된|필수|만\s*추천|으로\s*만든|으로\s*개발", text))
        if strict:
            profile['require_preferred_stack'] = True

    for label, categories in CATEGORY_TERMS:
        if label.lower().replace(' ', '') in s:
            profile['preferred_categories'] = categories
            break

    if '초보' in s or '입문' in s or '개발경험없' in s or '개발못' in s:
        profile['skill_level'] = 'NONE'
    elif '기초' in s or '기본수준' in s or '초급' in s:
        profile['skill_level'] = 'BASIC'
    elif '중급' in s or '어느정도' in s:
        profile['skill_level'] = 'INTERMEDIATE'
    elif '고급' in s or '숙련' in s or '전문가' in s:
        profile['skill_level'] = 'ADVANCED'

    if any(x in s for x in ('저위험', '보수적', '안정적인', '위험싫', '위험낮', '안전하게', '위험적게')):
        profile['risk_tolerance'] = 'LOW'
    elif any(x in s for x in ('고위험', '위험감수', '공격적', '도전적')):
        profile['risk_tolerance'] = 'HIGH'
    elif '중위험' in s or '중간위험' in s or '보통위험' in s or s in ('보통','중간'):
        profile['risk_tolerance'] = 'MEDIUM'

    # An explicit maximum recurring expense is optional; no silent 30k cap.
    if re.search(r"월\s*(?:운영비|비용)", text):
        after = re.search(r"월\s*(?:운영비|비용)[^\d]{0,12}(\d[\d,.]*\s*(?:만원|천원|원|만))", text)
        if after:
            v = _money(after.group(1))
            if v is not None:
                profile['max_monthly_cost_krw'] = v


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
    if not state:
        state = {'profile': {}, 'waiting': ''}
        context['recommendation_intake'] = state
    p = state['profile']
    if SKIP_REQUEST.match(message.strip()) and state['waiting'] in ('skill_level', 'risk_tolerance'):
        field = state['waiting']
        p[field] = 'BASIC' if field == 'skill_level' else 'MEDIUM'
        p.setdefault('assumptions', []).append('개발 수준: 기초 가정' if field == 'skill_level' else '위험 허용: 보통 가정')
    else:
        _extract(message, p)
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
        return {'message': question}
    context['confirmed_recommendation'] = dict(p)
    context.pop('recommendation_intake', None)
    return {'args': _create_args(p), 'assumptions': p.get('assumptions', [])}


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
