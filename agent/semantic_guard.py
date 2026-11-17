"""Conservative meaning checks for LLM-extracted categorical preferences.

These checks are not a replacement for language understanding. They reject
unambiguous contradictions and abstain when the source is unclear, so that the
user can clarify instead of receiving a confidently wrong recommendation.
"""
import re


def _clean(text):
    return re.sub(r'\s+', ' ', str(text or '').strip()).casefold()


def _has(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


SKILL_PATTERNS = {
    'NONE': [r'초보', r'입문', r'처음', r'개발\s*경험\s*(?:이\s*)?없',
             r'코딩\s*(?:못|안\s*해)', r'개발\s*(?:못|안\s*해)'],
    'BASIC': [r'기초', r'초급', r'기본\s*(?:만|정도)', r'조금\s*(?:할|알)', r'약간\s*(?:할|알)'],
    'INTERMEDIATE': [r'중급', r'중간\s*(?:정도|수준)', r'어느\s*정도\s*(?:할|알)'],
    'ADVANCED': [r'고급', r'숙련', r'전문가', r'시니어'],
}

# Value expressed as a negation should not count as positive evidence.
NEGATED_SKILL = r'(?:초보|입문|중급|고급|기초|초급|전문가|숙련).{0,10}(?:아니|아님|아닌|않아|못해)'


def skill_supported(value, quote):
    text = _clean(quote)
    if _has(text, [NEGATED_SKILL]):
        return False
    labels = {label for label, patterns in SKILL_PATTERNS.items() if _has(text, patterns)}
    return labels == {value}


def risk_supported(value, quote):
    text = _clean(quote)
    # Respect polarity: '고위험은 싫어' is low tolerance, not high.
    if _has(text, [r'(?:고\s*위험|높은\s*위험|큰\s*위험).{0,14}(?:싫|피하|원치|안\s*원|부담)',
                   r'(?:위험|리스크).{0,12}(?:최소|줄이|낮|적|싫|피하|없|안\s*감수)',
                   r'저\s*위험', r'보수적', r'안전(?:한|하게|했으면|위주)',
                   r'리스크\s*(?:낮|적)']):
        return value == 'LOW'
    if _has(text, [r'(?:위험|리스크).{0,12}(?:높|많|크|감수|상관없)',
                   r'고\s*위험', r'공격적']):
        # Vague '위험을 감수' needs a level; only explicit high tolerance qualifies.
        return value == 'HIGH' and _has(text, [r'고\s*위험', r'높은\s*위험', r'위험.{0,12}(?:높|많|상관없)', r'공격적'])
    if _has(text, [r'(?:위험|리스크).{0,12}(?:보통|중간|중립)',
                   r'(?:보통|중간)\s*(?:수준|정도)?\s*(?:위험|리스크)']):
        return value == 'MEDIUM'
    return False


OBJECTIVE_CONCEPTS = {
    'income': (r'수익|매출|돈\s*벌|부업|소득|수익화', r'수익|매출|돈\s*벌|부업|소득|수익화'),
    'learning': (r'학습|공부|배우|연습|교육', r'학습|공부|배우|연습|교육'),
    'portfolio': (r'포트폴리오', r'포트폴리오'),
    'resale': (r'재판매|되팔|엑싯|양도\s*차익', r'재판매|되팔|엑싯|양도\s*차익'),
    'operate': (r'직접\s*운영|서비스\s*운영|창업', r'직접\s*운영|서비스\s*운영|창업'),
}


def objective_supported(value, quote):
    """Reject direct intent inversion; allow goals not in this small vocabulary."""
    source, target = _clean(quote), _clean(value)
    a = {key for key, (src, _) in OBJECTIVE_CONCEPTS.items() if re.search(src, source)}
    b = {key for key, (_, dst) in OBJECTIVE_CONCEPTS.items() if re.search(dst, target)}
    return not (a and b and not a.intersection(b))


def tech_is_only_proficiency(quote):
    """Skill disclosure is not itself a purchase preference for that technology."""
    source = _clean(quote)
    has_skill = bool(re.search(r'중급|초보|초급|고급|개발\s*경험|코딩\s*경험|할\s*줄', source))
    asks_project = bool(re.search(r'프로젝트|웹앱|서비스|필수|반드시|만\s*추천|기반\s*매물', source))
    return has_skill and not asks_project


def requires_stack_supported(quote):
    source = _clean(quote)
    return bool(re.search(r'필수|반드시|꼭|\b만\b|\S+\s*기반\s*(?:프로젝트|웹앱)|'
                          r'(?:프로젝트|웹앱|서비스).{0,12}만|(?:기술|스택).{0,12}(?:필수|반드시)', source))
