"""Visual-semantic projection only; no API calls, ranking or approval decisions.

Keep display semantics separate from business state. CSS chooses presentation, but
this mapping decides which wording is honest and which viewport width to use.
"""
from __future__ import annotations

from html import escape

WIDE_FOCUSES = frozenset({'search', 'recommend', 'inspection', 'workflow'})
STANDARD_FOCUSES = frozenset({'offer', 'offer_summary', 'account_result'})


def layout_mode(focus: str) -> str:
    if focus in WIDE_FOCUSES:
        return 'wide'
    if focus in STANDARD_FOCUSES:
        return 'standard'
    return 'reading'


# Evidence classifications describe the type of source assertion. A 'PASS'
# from a static check is not proof of a safe asset or clear legal rights.
RISK_STATES = {
    'UNKNOWN': ('미확인', 'unknown'),
    'UNCERTAIN': ('미확인', 'unknown'),
    'PROBLEM': ('문제 발견', 'problem'),
    'ISSUE': ('문제·불일치', 'problem'),
    'CAUTION': ('주의', 'caution'),
    'REVIEW': ('추가 검토', 'caution'),
    'PASS': ('기준 통과 표기', 'reported'),
    'VERIFIED': ('검증 표기', 'reported'),
    'VERIFIED_CLAIM': ('검증 표기된 주장', 'reported'),
    'SELLER_REPORTED': ('판매자 고지', 'reported'),
    'STATIC_CHECKED': ('정적 검사 표시', 'reported'),
    'EXECUTION_CHECKED': ('실행 검사 표시', 'reported'),
}


def risk_display(status: str) -> tuple[str, str]:
    return RISK_STATES.get(str(status or '').upper(), ('자료 확인 필요', 'unknown'))


def evidence_rows(dimensions: list) -> str:
    """Escape all seller/model-provided content before embedding HTML.

    Severity is rendered with a textual status as well as a subtle color cue.
    """
    rows = []
    for dimension in dimensions[:7]:
        if not isinstance(dimension, dict):
            continue
        title = escape(str(dimension.get('label') or '항목')[:60])
        meaning, tone = risk_display(dimension.get('status'))
        details = escape(str(dimension.get('explanation') or '추가 확인이 필요해요.')[:240])
        rows.append(
            '<div role="listitem" class="evidence-row evidence-row--{}">'
            '<span class="evidence-row__title">{}</span>'
            '<span class="evidence-tag evidence-tag--{}">{}</span>'
            '<span class="evidence-row__detail">{}</span></div>'.format(
                tone, title, tone, meaning, details
            )
        )
    return '<div class="evidence-list" role="list">{}</div>'.format(''.join(rows)) if rows else ''


def activity_tone(success: bool) -> str:
    # A successful API result is observational, not risk or transaction verification.
    return 'observed' if success else 'problem'
