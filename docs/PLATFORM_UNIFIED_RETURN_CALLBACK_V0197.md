# ProjectAgain Platform v0.37 후속 수정 요청 — 통합 로그인 전용 복귀 경로

## 문제 재현 및 원인

- Agent v0.19.6에서 통합 로그인 시작은 `https://projectagain.streamlit.app/~/+/pa-agent/auth/start`로 성공하고 `projectagain.kr`의 로그인/권한 동의까지 성공함.
- 플랫폼 동의 후 `https://projectagain.streamlit.app/?pa_broker_ticket=...&pa_broker_state=...`로 복귀하나 Streamlit Community Cloud의 **외부 래퍼 루트(`/`)**에서 무한 로딩.
- Streamlit 앱 서버 ASGI 라우트는 Community Cloud 프록시의 **`/~/+/`** 아래에서 직접 접근해야 함. 플랫폼은 기존 루트 반환을 사용하므로 브라우저 최상위 문서에 ASGI 콜백이 도달하지 않음.
- 기존 Broker API, 자격증명, OAuth 서명키, 토큰 회전의 문제가 아님. 일회용 티켓을 채팅/로그에 복사하지 말 것.

## 플랫폼 측 최소 변경 (v0.37 후속)

1. **신규 통합 로그인 flow에서만** Streamlit 복귀 주소를 아래의 정확한 HTTPS URL로 사용:

   `https://projectagain.streamlit.app/~/+/pa-agent/auth/callback`

2. 레거시 `OAUTH_BROKER_STREAMLIT_RETURN_URI=https://projectagain.streamlit.app/` 및 OIDC `.../oauth2callback`은 **절대로 바꾸지 않음**. 하위 호환을 위해 신규 `OAUTH_BROKER_UNIFIED_RETURN_URI` 환경변수에 위 주소를 별도로 등록하고, `flow == unified_login`인 인텐트/콜백에만 적용. 콜백 URL을 브라우저 입력이나 임의의 리다이렉트 파라미터로 받지 말 것.
3. `GET /api/v1/oauth/broker/unified/capabilities`(HTTP Basic 필수)에 다음 문자열 필드 추가:

   `"unified_return_uri": "https://projectagain.streamlit.app/~/+/pa-agent/auth/callback"`

   Agent v0.19.7은 값이 **완전히 일치하지 않으면 로그인 시작을 차단**한다. 이 확인은 플랫폼 배포 전에 설정 누락을 감지하기 위한 것이다.
4. `/api/v1/oauth/broker/unified/intents`, 60초 일회용 티켓, 클라이언트 state/nonce, PKCE, 서버 간 ticket 교환 및 RSA 신원 토큰은 v0.37 그대로 유지. `offer:draft`는 초기 동의에 넣지 않음.
5. 코드·설정 변경 후 Replit Production 적용, Alembic 스키마 추가 변경이 필요하지 않은지 확인하고 종전 운영 DB/Secret 보존. 레거시 OIDC/Broker 회귀 테스트 유지.

## Agent 측 구현 (v0.19.7)

- `app.py`와 `unified_entry.py`에 `/pa-agent/auth/callback` GET 라우트 등록.
- 브라우저 `HttpOnly Secure SameSite=Lax` 쿠키와 Supabase pending 세션의 state/proof를 바탕으로 서버측 일회용 티켓 교환; RS256 `id_token` 검증; 성공/실패 결과와 상관없이 303으로 **토큰 없는** `https://projectagain.streamlit.app/`에 복귀.
- Secret/Ticket 원문을 HTML·로그·DB 평문에 공개하지 않음. 쿠키 없는 브라우저는 거절. 기존 `st.login` 2단계 방식은 feature flag OFF로 사용 가능.

## 필수 운영 E2E

1. 브라우저 로그인 버튼 → 직접 ASGI `/~/+/pa-agent/auth/start` → 플랫폼 권한 동의.
2. 플랫폼 리다이렉트 → 브라우저 최상위 문서가 `/~/+/pa-agent/auth/callback?pa_broker_ticket=...`로 들어옴 → 303 응답 → **깨끗한 루트 URL**로 이동.
3. Streamlit 계정 연결 완료, 개인 API GET, Supabase 대화 복원 및 자동 갱신.
4. 거부/만료/중복 티켓/다른 브라우저, 로그아웃/계정 전환/레거시 로그인 E2E.
5. 초기 운용 중 문제면 `AGENT_UNIFIED_LOGIN_ENABLED=false`로 Streamlit 구 방식 복원. 플랫폼 신규 설정만 비활성화하고 레거시 `OAUTH_BROKER_STREAMLIT_RETURN_URI`와 기존 토큰 저장은 건드리지 않음.

*주의: 이 문서는 플랫폼 변경 요청이다. Agent 코드를 배포하는 것만으로 신규 return URI가 적용되지는 않는다.*
