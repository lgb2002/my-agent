"""Optional LangChain chat: strictly read-only, no marketplace tools or secrets."""
import re
from .config import OPENAI_MODEL, OPENAI_API_KEY

# Detect a few obvious API credential prefixes. NOT a comprehensive secret scanner.
SECRET_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_-]{20,})", re.I)


def contains_obvious_secret(text):
    return bool(SECRET_PATTERN.search(text))

SYSTEM = (
    '당신은 디지털 자산 거래 플랫폼의 국비 시연용 분석 보조 에이전트입니다. '
    '사용자가 제공한 정보만 바탕으로 설명하고, 확인되지 않은 자산 상태/권리/수익성을 단정하지 마세요. '
    '실시간 플랫폼 조회, 매수·매각·협상 전송, 결제, 계약 확정, 소스코드 실행 권한이 없습니다. '
    '추천 기준을 설명하고 다음 검증 사항을 제시하는 데 집중하세요. '
    '인증 키·비밀번호·토큰을 요청하거나 노출하지 마세요. '
    '원격 AI로 전달되는 내용을 사용자에게 투명하게 다루세요.'
)


def answer_user(message, history):
    """Only invoked by explicitly enabled endpoint. No tool bindings."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    if not OPENAI_API_KEY:
        raise RuntimeError('OpenAI 키 없음')
    model = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0,
        max_tokens=400,
        timeout=20,
        max_retries=0,
    )
    messages = [SystemMessage(content=SYSTEM)]
    for item in history:
        role = item['role']
        messages.append(HumanMessage(content=item['content']) if role == 'user'
                        else AIMessage(content=item['content']))
    messages.append(HumanMessage(content=message))
    response = model.invoke(messages)
    content = response.content
    if isinstance(content, str):
        return content[:4000]
    return str(content)[:4000]
