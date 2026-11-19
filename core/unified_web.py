"""Secure browser endpoints for v0.37 unified login (ASGI st.App launcher only).

The cookie is issued/cleared by an HTTP response, never JavaScript or a
Streamlit widget. The platform callback is intercepted before Streamlit sees
its one-time ticket, then immediately redirected to a clean URL.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from urllib.parse import parse_qs

from core.oauth_broker import BrokerError
from core.unified_login import (UnifiedClient, UnifiedStore, COOKIE_NAME,
                                COOKIE_MAX_AGE, cookie_binding, UNIFIED_START_URL)

PUBLIC_APP_URL = 'https://projectagain.streamlit.app/'
CALLBACK_KEYS = ('pa_broker_ticket', 'pa_broker_state', 'pa_broker_error')


def _enabled():
    return os.environ.get('AGENT_UNIFIED_LOGIN_ENABLED', '').strip().lower() in ('true', '1', 'yes')


def _services():
    import streamlit as st
    from core.runtime_secrets import configure_from_secrets
    configure_from_secrets(st.secrets)
    # The launcher and the app must use exactly the same public host and issuer.
    origin = os.environ.get('PROJECTAGAIN_API_ORIGIN','').rstrip('/')
    return_uri = os.environ.get('PROJECTAGAIN_BROKER_REDIRECT_URL','')
    if origin != 'https://projectagain.kr' or return_uri != PUBLIC_APP_URL:
        raise BrokerError('configuration_mismatch', '통합 로그인 주소 설정을 확인해 주세요.')
    store = UnifiedStore(os.environ.get('AGENT_STATE_DATABASE_URL',''),
                         os.environ.get('AGENT_BROKER_STORE_KEY',''))
    client = UnifiedClient(origin,os.environ.get('PROJECTAGAIN_BROKER_CLIENT_ID',''),
                           os.environ.get('PROJECTAGAIN_BROKER_CLIENT_SECRET',''))
    return store,client


def _read_enabled():
    import streamlit as st
    from core.runtime_secrets import configure_from_secrets
    configure_from_secrets(st.secrets)
    return _enabled()


def _redirect_to_home(status: str=''):
    from starlette.responses import RedirectResponse
    # Only fixed nonsecret status codes appear in the redirect URL.
    target = PUBLIC_APP_URL + ('?pa_login_notice=' + status if status in ('cancelled','failed') else '')
    response = RedirectResponse(target, status_code=303)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _cookie(response, val=None):
    if val:
        response.set_cookie(COOKIE_NAME, val, max_age=COOKIE_MAX_AGE,
                            httponly=True, secure=True, samesite='lax', path='/')
    else:
        response.delete_cookie(COOKIE_NAME, path='/', secure=True, httponly=True, samesite='lax')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'


def _same_origin_navigation(headers):
    site = headers.get('sec-fetch-site','')
    return site in ('same-origin','none','')


# ASGI route failures are not always visible in Streamlit script logs.
# Expose ONLY predetermined diagnostic stage/status identifiers in HTTP bodies.
# Never include an exception string, request URL, cookie, token, or secret.
_SAFE_START_ERRORS = frozenset({
    'disabled', 'not_configured', 'configuration_mismatch', 'database_required',
    'invalid_encryption_key', 'storage_unavailable', 'unified_unavailable',
    'unified_callback_not_ready', 'unified_denied', 'invalid_response',
    'invalid_redirect', 'invalid_state',
})


class _StartStageFailure(Exception):
    def __init__(self, stage: str, code: str):
        super().__init__('login start failed')
        self.stage = stage
        self.code = code


def _start_step(stage, operation):
    try:
        return operation()
    except BrokerError as exc:
        code = exc.code if exc.code in _SAFE_START_ERRORS else 'broker_failure'
        raise _StartStageFailure(stage, code) from None
    except Exception:
        raise _StartStageFailure(stage, 'unexpected') from None


def _start_failure_response(stage, code):
    from starlette.responses import PlainTextResponse
    status = 500 if code == 'unexpected' else 503
    # All values are from a fixed local vocabulary and cannot echo credentials.
    return PlainTextResponse(
        '통합 로그인 시작 오류\n'
        f'진단 코드: PA-START-{stage}-{code}\n'
        '이 코드만 공유해 주세요. 로그인 URL, 쿠키, 토큰은 공유하지 마세요.',
        status_code=status,
        headers={
            'Cache-Control': 'no-store',
            'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
        },
    )


async def login_route_health(request):
    """Public, side-effect-free route probe to separate proxy errors from app errors."""
    from starlette.responses import PlainTextResponse
    return PlainTextResponse('PA-AUTH-ROUTE-OK', headers={
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


def _start_sync():
    enabled = _start_step('CONFIG', _read_enabled)
    if not enabled:
        raise _StartStageFailure('CONFIG', 'disabled')
    store, client = _start_step('SERVICES', _services)
    _start_step('CAPABILITIES', client.capabilities)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(48)
    proof = secrets.token_urlsafe(48)
    raw_cookie = secrets.token_urlsafe(48)
    _start_step('DATABASE', lambda: store.start(raw_cookie, state, proof, nonce))
    try:
        url = _start_step('INTENT', lambda: client.begin_unified(state, proof, nonce))
    except _StartStageFailure:
        # Existing cleanup semantics: best effort only, never disclose state.
        store.abandon(state)
        raise
    return url, raw_cookie


async def login_start(request):
    from starlette.responses import PlainTextResponse, RedirectResponse
    if not _same_origin_navigation(request.headers):
        return PlainTextResponse('허용되지 않은 요청입니다.', status_code=403)
    try:
        url, raw_cookie = await asyncio.to_thread(_start_sync)
        result = RedirectResponse(url, status_code=303)
        _cookie(result, raw_cookie)
        return result
    except _StartStageFailure as exc:
        return _start_failure_response(exc.stage, exc.code)
    except BrokerError as exc:
        code = exc.code if exc.code in _SAFE_START_ERRORS else 'broker_failure'
        return _start_failure_response('OTHER', code)
    except Exception:
        # Includes unexpected response-creation/middleware exceptions.
        return _start_failure_response('OTHER', 'unexpected')


def _callback_sync(cookie, ticket, state, error):
    if not _read_enabled():
        return 'failed'
    if error:
        # Consent cancellation must not create an Agent session.
        return 'cancelled'
    if not ticket or not state or not cookie_binding(cookie):
        return 'failed'
    store, client = _services()
    store.finish(cookie,state,ticket,client)
    return ''


async def process_callback(request):
    # Never display the ticket/state, and never forward the raw URL to Streamlit.
    query = request.query_params
    for name in CALLBACK_KEYS:
        if len(query.getlist(name)) > 1:
            return _redirect_to_home('failed')
    cookie = request.cookies.get(COOKIE_NAME,'')
    try:
        outcome = await asyncio.to_thread(_callback_sync,cookie,query.get('pa_broker_ticket'),
                                           query.get('pa_broker_state'),query.get('pa_broker_error'))
        return _redirect_to_home(outcome)
    except Exception:
        # Fail closed and clear query parameters, including one-time tickets.
        # Errors are deliberately not logged with request URLs or JWT contents.
        return _redirect_to_home('failed')


def _logout_sync(cookie):
    if not cookie_binding(cookie):
        return True
    try:
        store,client=_services()
        binding=cookie_binding(cookie)
        uid=store.lookup_identity(binding)
        if uid:
            record=store.session(binding,uid)
            if record:
                try:
                    client.logout(record)
                except BrokerError:
                    # Even on platform network failure, revoke the Agent's
                    # local browser binding. Platform logout is best effort.
                    pass
        store.clear(binding)
        return True
    except BrokerError:
        # Do not claim logout success or clear an unrevoked cookie when the
        # local session database is unavailable.
        return False


async def login_logout(request):
    from starlette.responses import PlainTextResponse
    if not _same_origin_navigation(request.headers):
        return PlainTextResponse('허용되지 않은 요청입니다.',status_code=403)
    if not await asyncio.to_thread(_logout_sync,request.cookies.get(COOKIE_NAME,'')):
        return PlainTextResponse('로그아웃 연결을 확인하지 못했어요. 다시 시도해 주세요.',
                                 status_code=503,headers={'Cache-Control':'no-store'})
    from starlette.responses import RedirectResponse
    next_step = request.query_params.get('next')
    if next_step == 'switch':
        redirect = 'https://projectagain.kr/auth/logout'
    elif next_step == 'start':
        redirect = UNIFIED_START_URL
    else:
        redirect = PUBLIC_APP_URL
    response=RedirectResponse(redirect,status_code=303)
    _cookie(response,None)
    return response


class BrokerReturnMiddleware:
    """Legacy root callback protection; unified return MUST use direct ASGI route.

    The Community Cloud public / page is owned by the outer app wrapper.
    This middleware cannot reliably intercept that wrapper's request. The
    v0.37 unified callback instead uses /~/+/pa-agent/auth/callback, exposed
    as a top-level document route by the platform's unified-only return URI.
    """
    def __init__(self, app):
        self.app=app

    async def __call__(self,scope,receive,send):
        if scope.get('type')=='http' and scope.get('method')=='GET' and scope.get('path') in ('/','/~/+/'):
            from starlette.requests import Request
            req=Request(scope,receive)
            if any(k in req.query_params for k in CALLBACK_KEYS):
                # Keep the original v0.25 callback working with the feature flag
                # disabled, even if the Cloud entrypoint is already switched.
                if await asyncio.to_thread(_read_enabled):
                    response=await process_callback(req)
                    return await response(scope,receive,send)
        await self.app(scope,receive,send)
