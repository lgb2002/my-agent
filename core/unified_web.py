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
                                COOKIE_MAX_AGE, cookie_binding)

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


def _start_sync():
    if not _read_enabled():
        raise BrokerError('disabled', '통합 로그인이 비활성화되어 있어요.')
    store, client = _services()
    client.capabilities()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(48)
    proof = secrets.token_urlsafe(48)
    raw_cookie = secrets.token_urlsafe(48)
    store.start(raw_cookie, state, proof, nonce)
    try:
        url = client.begin_unified(state, proof, nonce)
    except BrokerError:
        store.abandon(state)
        raise
    return url,raw_cookie


async def login_start(request):
    from starlette.responses import PlainTextResponse, RedirectResponse
    if not _same_origin_navigation(request.headers):
        return PlainTextResponse('허용되지 않은 요청입니다.', status_code=403)
    try:
        url, raw_cookie = await asyncio.to_thread(_start_sync)
    except BrokerError:
        return PlainTextResponse('ProjectAgain 로그인을 시작하지 못했어요. 설정과 플랫폼 상태를 확인해 주세요.',
                                 status_code=503, headers={'Cache-Control':'no-store'})
    result = RedirectResponse(url,status_code=303)
    _cookie(result,raw_cookie)
    return result


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
    except (BrokerError,ValueError,TypeError):
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
        redirect = 'https://projectagain.streamlit.app/pa-agent/auth/start'
    else:
        redirect = PUBLIC_APP_URL
    response=RedirectResponse(redirect,status_code=303)
    _cookie(response,None)
    return response


class BrokerReturnMiddleware:
    """Intercept root callback BEFORE Streamlit, clearing ticket from browser URL."""
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
