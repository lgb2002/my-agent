# ProjectAgain Agent v0.19.3 — Platform v0.37 통합 로그인 어댑터

## 적용 및 검증 상태

- 플랫폼 계약: `ProjectAgain_Agent_Unified_Login_API_Contract_v037.md`
- Agent 기준: v0.19.2 전체 프로젝트에서 누적 수정
- 구현 범위: 신규 `/unified/capabilities`, `/unified/intents`, 기존 `/tickets/exchange`, RS256 ID token 검증, HttpOnly 브라우저별 세션, 암호화 PostgreSQL 보관, 기존 Broker access/refresh, 브라우저별 로그아웃, 선택적 `offer:draft` 추가 동의
- **코드/오프라인 회귀 테스트 완료, Streamlit Cloud + projectagain.kr 운영 E2E는 미검증.**
- 안전한 기본값: `AGENT_UNIFIED_LOGIN_ENABLED=false`. 신규 진입점으로 변경해도 비활성 상태에서는 기존 OIDC+Broker 그대로 작동.

## 왜 `unified_entry.py`가 필요한가?

Streamlit `app.py` 안의 `st.session_state`만으로 플랫폼을 오가는 동일 브라우저를 검증할 수 없다. 브라우저로 돌아온 `ticket`을 단지 state가 비슷하다는 이유로 교환하면 로그인 CSRF·브라우저 혼동 위험이 있다.

v0.19.3은 Streamlit 1.57+의 ASGI `st.App` 진입점으로 **동일 출처의 서버 HTTP 라우트**를 등록한다. `/pa-agent/auth/start`는 Secure/HttpOnly/SameSite=Lax 쿠키를 설정하고 암호화된 서버 DB pending 정보를 만든다. 플랫폼은 명시적 권한 동의를 수행한다. 플랫폼에서 `https://projectagain.streamlit.app/?pa_broker_ticket=...&pa_broker_state=...`로 돌아오면 ASGI 미들웨어가 **Streamlit UI 실행 이전에** 복귀 요청을 확인하고, 쿠키 해시 + 서버 저장 state/nonce/proof를 검증한 뒤 토큰을 교환한다. 서명 검증 후 브라우저 세션을 확정하고 **ticket/state 없는 깨끗한 URL**로 이동한다.

`id_token`은 검증 직후 폐기한다. 쿠키에는 임의 세션 ID만 있고 사용자 UUID/Access/Refresh Token/인증 proof가 없다. 브라우저별 실제 로그인·복원은 Supabase PostgreSQL에만 보관한다.

## 활성화 전 필수 조건

1. Replit 운영에 Platform v0.37 코드를 게시한다.
2. 운영 DB를 백업한 다음 운영 DB에 `0014_unified_login` 마이그레이션이 적용됐는지 확인한다. Development DB를 Production DB로 복사하지 않는다.
3. 운영 서버 `OAUTH_BROKER_UNIFIED_LOGIN_ENABLED=true`, 기존 `OAUTH_BROKER_ENABLED=true` 확인. 기존 OIDC/Broker Secret·RSA 키는 유지한다.
4. Streamlit Cloud의 프로젝트 **Main file path를 `app.py`에서 `unified_entry.py`로 변경**하고 재부팅한다. 이 파일은 UI 코드를 교체하지 않고 기존 `app.py`를 구동하는 안전한 HTTP 진입점이다.
5. Streamlit Secrets의 기존 값은 모두 유지하고 **`AGENT_UNIFIED_LOGIN_ENABLED = false`**를 먼저 추가한다. 기존 로그인과 매물 조회 기능이 정상인지 검사한다.
6. 운영 플랫폼 설정/SSL/`GET /api/v1/oauth/broker/unified/capabilities`가 서버에서 정상인지 확인한 후 `AGENT_UNIFIED_LOGIN_ENABLED = true`로 변경하고 재부팅한다.
7. 서로 다른 브라우저 2개/계정 2개로 로그인 → 명시적 동의 → 복귀 → 새로고침 → 이전 대화 복원 → 개인 API 조회 → 로그아웃/계정 전환을 검증한다. 만료 시 재접속, 401 GET 1회 재시도, 제안 초안 권한 분리도 확인한다.

**추가하는 Streamlit Secret은 `AGENT_UNIFIED_LOGIN_ENABLED` 하나뿐이다.** 기존 `PROJECTAGAIN_BROKER_CLIENT_ID/SECRET`, `PROJECTAGAIN_API_ORIGIN=https://projectagain.kr`, `PROJECTAGAIN_BROKER_REDIRECT_URL=https://projectagain.streamlit.app/`, `AGENT_STATE_DATABASE_URL`, `AGENT_BROKER_STORE_KEY`는 변경/재생성하지 않는다.

## 신규 구현 파일

- `unified_entry.py`: Streamlit ASGI 서버와 커스텀 라우트/콜백 미들웨어
- `core/unified_web.py`: 서버 전용 시작·복귀·종료 처리. 브라우저 쿠키 발급과 정리. 민감한 query 제거
- `core/unified_login.py`: Broker v0.37 클라이언트, RSA 서명·issuer·audience·nonce·state/proof 검증, PostgreSQL 세션
- `tests/test_unified_login_v0193.py`: 브라우저 간 접근 차단, 재사용 방지, 서명 검증, 쿠키 보안, 비활성 시 레거시 유지 등

## PostgreSQL 저장 구조

기존 DB 및 사용자 데이터는 수정·삭제하지 않는다. 첫 unified 로그인 때 자동으로 생성되는 **신규 테이블만** 사용한다.

- `agent_unified_login_pending`: 일회용 `state_hash`, `cookie_hash`, 암호화 proof/nonce, 만료 시각
- `agent_unified_login_sessions`: `cookie_hash`, UUID `sub`, scope, 암호화 Broker 세션/증명, 만료 시각

비밀번호/Access/Refresh Token/JWT 원문은 저장하지 않는다. 기존 `agent_broker_sessions`, `agent_broker_pending`, 대화·사용량·작업 테이블은 건드리지 않는다.

## 안전성 / 하위 호환

- 신규 로그인 `offer:draft`는 포함하지 않고, 필요한 경우 기존 `/broker/intents`에 별도 명시적 동의한다. 결제/정산/실거래 실행은 Agent 불가.
- 브라우저 쿠키는 `HttpOnly; Secure; SameSite=Lax`, 임의 48바이트. 웹소켓과 Streamlit `st.session_state`로 state/proof를 공유하지 않는다.
- JWT는 issuer의 고정 JWKS로 `RS256`만 허용. `kid`, 서명, `aud`, `iss`, `exp`, `iat`, `auth_time`, `token_use`, nonce, state/proof hash, UUID `sub` 모두 검증한다.
- 이전 Broker의 `POST /access`로만 Access Token 갱신하며 인증 문제 발생 시 유료 AI/개인 API를 중단한다. 거래 POST 자동 재전송 금지, GET 401만 1회 재시도.
- 통합 로그인 비활성화 시 기존 `st.login()` + Broker 두 단계 사용 유지. 레거시 URL의 콜백도 ASGI 미들웨어가 가로채지 않는다.
- **Streamlit Cloud ASGI 실행/쿠키 전달, 플랫폼 운영 API 응답을 포함한 실환경 E2E는 완료되지 않았다.**

## 문제 시 롤백

1. Streamlit의 `AGENT_UNIFIED_LOGIN_ENABLED = false`로 변경한 뒤 앱 재시작한다.
2. 필요하다면 Main file path를 기존 `app.py`로 되돌린다.
3. 기존 `[auth]`, Broker Secret, PostgreSQL, OIDC 키, 대화 데이터는 변경하지 않는다.
4. 신규 테이블을 삭제할 필요는 없다. 이미 발급된 신규 세션은 로그인 방식을 되돌리면 사용되지 않는다.

## 주의

- 플랫폼 비밀키, 세션 쿠키, JWT, 원본 ticket/state, DB 비밀번호를 로그·GitHub·채팅에 공유하지 않는다.
- Streamlit `st.App` 커스텀 라우트는 Streamlit 1.57+ 기능으로, 클라우드 프록시의 실제 동작 확인이 필요하다.
- 신규 방식에서 '다른 계정으로 로그인'을 선택하면 Agent 세션 종료 후 플랫폼의 `/auth/logout`으로 이동한다. 플랫폼 로그아웃 후 Agent로 돌아와 새 로그인을 시작한다. **플랫폼 쿠키와 Agent 쿠키는 별개**다.
