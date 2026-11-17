"""Platform handoff demo: Streamlit native OIDC login (NO automatic refresh).

This file is a reference snippet, not the user's actual Streamlit repository.
Install streamlit[auth] and configure Streamlit secrets as in docs/..._V023.md.
"""
import os
import streamlit as st
import httpx

if not st.user.is_logged_in:
    st.title('ProjectAgain AI 에이전트')
    if st.button('ProjectAgain 계정으로 로그인',type='primary'):
        st.login()
    st.stop()

st.write('연결된 계정 ID:', st.user.get('sub'))

# expose_tokens = ["access"] must be configured in Streamlit Secrets.
# This is a short-lived 15-minute API access token, NOT a stored manual grant.
access = None
try:
    access = st.user.tokens.access
except (KeyError, AttributeError):
    pass

if access:
    api_base = os.environ.get('PROJECTAGAIN_API_BASE', 'https://YOUR-REPLIT-DOMAIN/api/v1')
    if st.button('내 구매 기준 불러오기'):
        try:
            response = httpx.get(api_base+'/buyer-preferences/me',
                headers={'Authorization':'Bearer '+access},timeout=12)
            response.raise_for_status()
            st.json(response.json())
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 401:
                st.warning('액세스 토큰이 만료됐습니다. 현재 st.login 기반 예시는 자동 갱신을 지원하지 않습니다.')
            else:
                st.error('API 조회 실패')
else:
    st.warning('Streamlit Secrets에 expose_tokens=["access"] 설정이 필요합니다.')

if st.button('Streamlit에서 로그아웃'):
    # NOTE: This clears the Streamlit session only. Revoke platform tokens via
    # ProjectAgain account settings or a confidential client-side revoke call.
    st.logout()
