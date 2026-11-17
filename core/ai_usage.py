"""Authenticated, database-backed, fail-closed AI metering.

No bearer tokens, user content or API keys are persisted. Counters are atomic
across concurrent Streamlit sessions when PostgreSQL is configured.
All model calls made by the app must use metered_model(); deliberately do not
fall back to unmetered OpenAI on storage/authentication failure.
"""
import contextvars
import hashlib
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

from core.config import OPENAI_MODEL


class AIAccessDenied(RuntimeError):
    pass


class AIQuotaExceeded(AIAccessDenied):
    pass


_identity = contextvars.ContextVar('projectagain_verified_ai_subject', default=None)
_GLOBAL_SUBJECT = '__GLOBAL__'
_SCHEMA = '''CREATE TABLE IF NOT EXISTS agent_ai_quota (
    subject TEXT NOT NULL, bucket TEXT NOT NULL, period TEXT NOT NULL,
    calls BIGINT NOT NULL DEFAULT 0, micro_usd BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (subject,bucket,period)
)'''


def set_ai_identity(subject):
    """Supply ONLY a platform-verified user ID hash or verified OIDC subject."""
    _identity.set(subject if isinstance(subject, str) and subject.startswith(('platform:', 'oidc:'))
                  and len(subject) >= 24 else None)


def current_ai_identity():
    return _identity.get()


def _number(name, default, minimum=0):
    try:
        value = Decimal(str(os.environ.get(name, default)))
        if not value.is_finite() or value < minimum:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise AIAccessDenied('AI 운영 한도 설정이 올바르지 않아요.') from None


def _integer(name, default, minimum=1):
    value = _number(name, str(default), minimum)
    if value != value.to_integral_value():
        raise AIAccessDenied('AI 호출 횟수 설정이 올바르지 않아요.')
    return int(value)


def _pricing():
    # Prices are configurable and *estimates*, not a payment processor/billing ledger.
    # Do not silently apply GPT-4.1-mini prices to a different, potentially pricier model.
    input_override = os.environ.get('AI_INPUT_USD_PER_1M')
    output_override = os.environ.get('AI_OUTPUT_USD_PER_1M')
    if input_override is None or output_override is None:
        if OPENAI_MODEL != 'gpt-4.1-mini':
            raise AIAccessDenied('현재 모델의 API 단가를 AI_INPUT_USD_PER_1M / AI_OUTPUT_USD_PER_1M에 설정해 주세요.')
        return Decimal('0.40'), Decimal('1.60')
    return _number('AI_INPUT_USD_PER_1M', input_override), _number('AI_OUTPUT_USD_PER_1M', output_override)


def _micro_usd(input_tokens, output_tokens):
    i, o = _pricing()
    return max(1, int((Decimal(input_tokens) * i + Decimal(output_tokens) * o).to_integral_value(rounding=ROUND_CEILING)))


def _connection_string():
    return os.environ.get('AI_USAGE_DATABASE_URL', '').strip() or os.environ.get('AGENT_STATE_DATABASE_URL', '').strip()


def storage_kind():
    return 'postgres' if _connection_string() else 'unconfigured'


@contextmanager
def _db():
    url = _connection_string()
    kind = storage_kind()
    if kind == 'postgres':
        if not url.startswith(('postgres://', 'postgresql://')):
            raise AIAccessDenied('AI 사용량 저장소 URL은 PostgreSQL이어야 해요.')
        try:
            import psycopg
            con = psycopg.connect(url, connect_timeout=5, sslmode='require')
        except Exception:
            raise AIAccessDenied('AI 사용량 저장소에 연결할 수 없어 유료 호출을 중지했어.') from None
    else:
        raise AIAccessDenied('공개 AI 사용에는 공용 PostgreSQL 저장소가 필요해요. 관리자가 설정해야 해요.')
    try:
        # Global advisory lock: two app replicas cannot pass budget checks concurrently.
        con.execute('SELECT pg_advisory_xact_lock(1736501601)')
        con.execute(_SCHEMA)
        yield con, kind
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _periods(identity, now):
    day = now.strftime('%Y-%m-%d')
    minute = now.strftime('%Y-%m-%dT%H:%M')
    return [(identity, 'minute', minute), (identity, 'day', day), (_GLOBAL_SUBJECT, 'day', day)]


def _limits():
    return [
        (_integer('AI_CALLS_PER_MINUTE', 4), None),
        (_integer('AI_CALLS_PER_USER_DAY', 30), _dollars_to_micro('AI_USER_DAILY_USD', '0.20')),
        (_integer('AI_GLOBAL_CALLS_PER_DAY', 300), _dollars_to_micro('AI_GLOBAL_DAILY_USD', '2.00')),
    ]


def _dollars_to_micro(name, default):
    return int((_number(name, default, Decimal('0.000001')) * 1000000).to_integral_value(rounding=ROUND_CEILING))


def _sql(command, kind):
    return command.replace('?', '%s') if kind == 'postgres' else command


def reserve(prompt, max_output_tokens):
    identity = current_ai_identity()
    if identity is None:
        raise AIAccessDenied('AI 대화를 사용하려면 계정 인증이 필요해요. ProjectAgain 위임 토큰 또는 로그인으로 연결해 주세요.')
    if max_output_tokens < 1 or max_output_tokens > 4096:
        raise AIAccessDenied('모델 출력 한도 설정이 올바르지 않아요.')
    # UTF-8 bytes are a conservative prompt token bound for this application;
    # account for tool schemas, messages and serialization overhead separately.
    try:
        import json
        raw = json.dumps(prompt, default=str, ensure_ascii=False)
    except (ValueError, TypeError):
        raw = str(prompt)
    input_upper = len(raw.encode('utf-8')) + 5500
    reserved = _micro_usd(input_upper, max_output_tokens)
    max_call = _dollars_to_micro('AI_MAX_RESERVED_CALL_USD', '0.04')
    if reserved > max_call:
        raise AIQuotaExceeded('입력이 길어 예상 AI 비용이 요청 한도를 초과했어. 메시지를 줄여 줘.')
    now = datetime.now(timezone.utc)
    keys = _periods(identity, now)
    limits = _limits()
    try:
        with _db() as (con, kind):
            for (subject, bucket, period), (max_calls, max_cost) in zip(keys, limits):
                row = con.execute(_sql('SELECT calls, micro_usd FROM agent_ai_quota WHERE subject=? AND bucket=? AND period=?', kind),
                                  (subject, bucket, period)).fetchone()
                calls, cost = tuple(row) if row else (0, 0)
                if int(calls) + 1 > max_calls or (max_cost is not None and int(cost) + reserved > max_cost):
                    raise AIQuotaExceeded('AI 사용 한도에 도달했어. 다음 사용 가능 시간에 다시 시도해 줘.')
            for subject, bucket, period in keys:
                con.execute(_sql('''INSERT INTO agent_ai_quota (subject,bucket,period,calls,micro_usd)
                    VALUES(?,?,?,1,?) ON CONFLICT(subject,bucket,period) DO UPDATE SET
                    calls=agent_ai_quota.calls+1, micro_usd=agent_ai_quota.micro_usd+excluded.micro_usd''', kind),
                    (subject, bucket, period, reserved))
    except AIAccessDenied:
        raise
    except Exception:
        raise AIAccessDenied('AI 사용량 확인에 실패했어. 안전을 위해 유료 호출을 중단했어.') from None
    return (tuple(keys), reserved)


def settle(ticket, raw_response):
    """Settle reported usage; keep the reservation if no reliable usage is supplied."""
    if raw_response is None:
        return
    usage = getattr(raw_response, 'usage_metadata', None) or {}
    meta = getattr(raw_response, 'response_metadata', None) or {}
    if not usage and isinstance(meta, dict):
        usage = meta.get('token_usage') or {}
    if not isinstance(usage, dict):
        return
    try:
        in_tokens = int(usage.get('input_tokens', usage.get('prompt_tokens', -1)))
        out_tokens = int(usage.get('output_tokens', usage.get('completion_tokens', -1)))
    except (TypeError, ValueError):
        return
    if in_tokens < 0 or out_tokens < 0:
        return
    keys, reserved = ticket
    actual = _micro_usd(in_tokens, out_tokens)
    # If actual cost exceeds estimated reservation, record it; the global
    # provider's billing hard limit is still the final safety net.
    diff = actual - reserved
    if diff == 0:
        return
    try:
        with _db() as (con, kind):
            for subject, bucket, period in keys:
                con.execute(_sql('''UPDATE agent_ai_quota SET micro_usd=CASE WHEN micro_usd+? >= 0
                    THEN micro_usd+? ELSE 0 END WHERE subject=? AND bucket=? AND period=?''', kind),
                    (diff, diff, subject, bucket, period))
    except Exception:
        # Fail closed on future requests only if DB is unavailable; never retry
        # model calls after receiving a potentially chargeable response.
        pass


def usage_snapshot(identity):
    if not identity:
        return None
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        with _db() as (con, kind):
            row = con.execute(_sql('''SELECT calls,micro_usd FROM agent_ai_quota
                WHERE subject=? AND bucket='day' AND period=?''', kind), (identity, day)).fetchone()
        return {'calls': int(row[0]) if row else 0,
                'estimated_usd': float(Decimal(int(row[1]) if row else 0) / Decimal(1000000)),
                'max_calls': _integer('AI_CALLS_PER_USER_DAY', 30),
                'daily_limit_usd': float(_number('AI_USER_DAILY_USD','0.20'))}
    except Exception:
        return None


class _MeteredRunnable:
    def __init__(self, runnable, max_output_tokens, structured=False):
        self._runnable = runnable
        self._max_output = max_output_tokens
        self._structured = structured

    def invoke(self, messages, **kwargs):
        # A valid browser identity alone must never authorize a paid request.
        # Broker revalidates/renews the per-session OAuth access on demand.
        from core.request_context import ensure_broker_access
        try:
            ensure_broker_access()
        except Exception:
            raise AIAccessDenied('계정 연결을 확인할 수 없어 AI 요청을 실행하지 않았어요.') from None
        ticket = reserve(messages, self._max_output)
        try:
            result = self._runnable.invoke(messages, **kwargs)
        except Exception:
            # Keep cost reservation: network failures can occur after billing.
            raise
        raw = result.get('raw') if self._structured and isinstance(result, dict) else result
        settle(ticket, raw)
        if self._structured:
            if not isinstance(result, dict) or result.get('parsing_error') is not None or result.get('parsed') is None:
                raise ValueError('AI 구조화 응답을 해석하지 못했어.')
            return result['parsed']
        return result


class MeteredModel:
    def __init__(self, underlying, max_output_tokens=800):
        self._underlying = underlying
        self._max_output = max_output_tokens

    def invoke(self, messages, **kwargs):
        return _MeteredRunnable(self._underlying, self._max_output).invoke(messages, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        kwargs.pop('include_raw', None)
        underlying = self._underlying.with_structured_output(schema, include_raw=True, **kwargs)
        return _MeteredRunnable(underlying, self._max_output, structured=True)

    def bind_tools(self, *args, **kwargs):
        return _MeteredRunnable(self._underlying.bind_tools(*args, **kwargs), self._max_output)


def metered_model(underlying, max_output_tokens=800):
    return MeteredModel(underlying, max_output_tokens)
