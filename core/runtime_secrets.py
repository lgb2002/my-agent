"""Bridge Streamlit Cloud top-level TOML secrets into existing env-based config.

Only call from the Streamlit app, before importing core.config or agent.*.
Never render, log or persist secret values.
"""
import os

SERVER_SETTINGS = (
    'MARKETPLACE_API_URL', 'MARKETPLACE_AUTH_SCHEME',
    'MARKETPLACE_INCLUDE_DEMO', 'OPENAI_API_KEY', 'OPENAI_MODEL',
    'ENABLE_OPENAI_CHAT', 'SHOW_DEVELOPER_TOOLS',
    'AGENT_STATE_DATABASE_URL', 'ENABLE_LIVE_DRAFTS',
    'AI_USAGE_DATABASE_URL', 'AI_CALLS_PER_MINUTE', 'AI_CALLS_PER_USER_DAY',
    'AI_GLOBAL_CALLS_PER_DAY', 'AI_USER_DAILY_USD', 'AI_GLOBAL_DAILY_USD',
    'AI_MAX_RESERVED_CALL_USD', 'AI_INPUT_USD_PER_1M',
    'AI_OUTPUT_USD_PER_1M',
    'PROJECTAGAIN_API_ORIGIN', 'PROJECTAGAIN_BROKER_CLIENT_ID',
    'PROJECTAGAIN_BROKER_CLIENT_SECRET', 'PROJECTAGAIN_BROKER_REDIRECT_URL',
    'AGENT_BROKER_STORE_KEY', 'AGENT_UNIFIED_LOGIN_ENABLED',
)


def configure_from_secrets(secrets, environ=None):
    """Existing nonempty environment variables take priority; return key presence only."""
    target = os.environ if environ is None else environ
    statuses = {}
    for name in SERVER_SETTINGS:
        raw = None
        try:
            raw = secrets.get(name, None)
        except (KeyError, AttributeError, TypeError):
            pass
        if name not in target or not str(target.get(name) or '').strip():
            if raw is not None:
                target[name] = str(raw)
        statuses[name] = bool(str(target.get(name, '')).strip())
    # A shared MARKETPLACE_API_KEY is intentionally NOT copied here.
    return statuses


def ai_activation_reason(key_present, enabled):
    if not key_present:
        return 'OpenAI 키가 설정되지 않았습니다.'
    if not enabled:
        return 'OpenAI 키는 감지되었지만 ENABLE_OPENAI_CHAT이 false여서 비활성화 상태입니다.'
    return 'OpenAI 도구 호출이 설정상 활성화되었습니다. 실제 호출 성공 여부는 별도 확인이 필요합니다.'
