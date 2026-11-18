# ProjectAgain v0.37 — AI Agent 통합 로그인 API 계약서

**상태**: 플랫폼 코드 구현·로컬 테스트 완료 / 운영 `projectagain.kr` 및 Streamlit Cloud 통합 E2E **미검증**  
**Agent 기준**: v0.19.1(또는 v0.19.2 UI 전용) → Agent 인증 어댑터 신규 개발 필요  
**기존 계약**: v0.23 Native OIDC, v0.25 OAuth Broker 그대로 유지  
**Issuer**: `https://projectagain.kr`  
**Streamlit return**: `https://projectagain.streamlit.app/`

## 1. 선택한 아키텍처

**선택: Broker 1회 승인 + 서명된 신원 증명(서버 간 발급).** Native Streamlit `st.login()`은 **신규 단일 버튼 흐름에서 사용하지 않으며**, 기존 OIDC 연동과 콜백은 하위 호환을 위해 유지한다.

이유: 기존 Broker는 이미 로그인 쿠키 → PKCE S256 → 명시적 scope 동의 → 일회용 브라우저 ticket → 서버 간 session_proof 결속 → 암호화 refresh 관리까지 갖추고 있다. 플랫폼이 기존 승인 단계를 재사용하면 서로 다른 OIDC/Broker 클라이언트의 동의를 몰래 결합할 필요가 없다. 대신 Agent는 `st.user`에 기대던 사용자 인증·영속 브라우저 세션을 **새로운 인증 어댑터**로 교체해야 한다.

대안인 OIDC 먼저+Broker 묵시 연결은 두 클라이언트의 동의 경계가 복잡하고, 안전한 서명·권한 연결 증명을 추가해야 해서 선택하지 않았다.

**한 번의 클릭 = 로그인 필요 시 로그인 + 명시적인 권한 동의 + Agent 복귀를 하나의 여정으로 연결하는 의미.** 사용자가 신규 계정으로 로그인하거나 권한에 동의하는 절차 자체를 없애는 의미가 아니다. 플랫폼 배포만으로 Streamlit UI가 변경되지 않는다.

## 2. 로그인 흐름

```text
Agent 버튼: ProjectAgain으로 시작하기
  ├─ 서버에서 독립 브라우저 세션 ID + session_proof + state + login_nonce 생성
  ├─ Agent 서버 POST /api/v1/oauth/broker/unified/intents (HTTP Basic)
  └─ 해당 브라우저를 authorization_url로 리다이렉트
ProjectAgain /api/v1/oauth/authorize (기존 OIDC 권한 동의)
  ├─ 웹 쿠키가 없으면 기존 /login → 원래 authorize로 복귀
  ├─ 권한 목록과 계정을 명확히 보여주고 approve/deny 요구
  └─ approval → 기존 PKCE 브로커 콜백
ProjectAgain /api/v1/oauth/broker/callback (기존)
  └─ 60초 단발성 ticket + state만 브라우저 URL로 전달
Agent 서버
  ├─ 복귀 요청을 해당 브라우저의 영속 pending 세션과 비교
  ├─ POST /api/v1/oauth/broker/tickets/exchange (기존 URL)
  ├─ 응답 id_token RS256/issuer/audience/nonce/proof+state hash 검사
  ├─ sub UUID와 Broker session을 해당 브라우저 세션으로 결속
  └─ URL에서 ticket/state 제거 → 로그인 완료 (2번째 버튼 필요 없음)
```

**브라우저 쿠키와 Streamlit WebSocket의 연결 식별자는 같지 않다.** Agent 측은 `st.session_state` 단독으로 pending state와 증명 값을 보관해서는 안 된다. 별도 안전한 HttpOnly Secure SameSite=Lax 기반 브라우저별 세션 또는 동급의 검증된 세션 프록시·서버측 저장소를 사용해야 한다. 이 부분은 Agent 구현 책임이며 플랫폼에서는 브라우저 쿠키를 설치해 줄 수 없다. 구현할 수 없다면 통합 로그인을 활성화하지 말고 v0.25 기존 방식 유지.

## 3. 플랫폼 신규 endpoint

### `GET /api/v1/oauth/broker/unified/capabilities`

**서버 간 전용.** HTTP Basic `projectagain-streamlit-broker:<OAUTH_BROKER_CLIENT_SECRET>` 필수. `200`:

```json
{
  "unified_login_enabled": true,
  "flow": "BROKER_CONSENT_AND_SIGNED_IDENTITY",
  "legacy_oidc_supported": true,
  "legacy_broker_supported": true,
  "initial_offer_draft": false
}
```

비활성화라도 `unified_login_enabled:false`로 응답 가능(브로커 자체 미설정 시 503).

### `POST /api/v1/oauth/broker/unified/intents`

**서버 간 전용.** `Content-Type: application/json`, HTTPS, Broker client HTTP Basic. `session_proof` 원문과 비밀키는 절대 요청 본문·URL·HTML에 포함하지 말 것. 브라우저별 독립 무작위 난수 생성(`secrets.token_urlsafe(48)` 수준).

```json
{
  "client_state": "URL_SAFE_RANDOM_STATE_MIN_16_CHAR",
  "session_binding_hash": "lowercase_sha256_of_server_only_session_proof_64_hex_chars",
  "login_nonce": "URL_SAFE_RANDOM_NONCE_MIN_32_CHAR",
  "scope": "openid profile email listing:read buyer_profile:read offer:read"
}
```

`client_state` 16–256자 `STATE_PATTERN`(`A-Za-z0-9_~.-`), `session_binding_hash` 64자리 소문자 hex, `login_nonce` URL-safe 32–256자. `scope` 미지정 시 위 읽기 범위 기본값. `openid` 필수. 알 수 없는 권한 또는 중복 scope 거부. **`offer:draft`는 초기 통합 시작에 포함 불가**, 별도 명시적 추가 동의(v0.25 기존 Broker intents)가 필요. `offer:execute`, 결제, 정산 등 실행권한은 지원하지 않음.

`200`:

```json
{
  "authorization_url": "https://projectagain.kr/api/v1/oauth/authorize?response_type=code&...",
  "expires_in": 300,
  "flow": "unified_login"
}
```

서버가 응답한 정확한 `authorization_url`로 **그 브라우저만** 이동. 상대경로 임의 합성·도메인 wildcard·동적 콜백 등록 금지. 플랫폼은 OIDC state/nonce, PKCE S256 검증 유지.

오류: `400 invalid_request`, `400 invalid_scope`, `400 invalid_nonce`, `400 incremental_consent_required`, `401 invalid_client`, `503 unified_login_disabled` 또는 기존 OAuth/Broker 설정 오류. 오류 본문은 `{"error":"..."}`이며 API 공통 에러 래퍼가 적용될 수 있으므로 Agent는 둘 다 처리.

## 4. 기존 Ticket Exchange의 **신규 통합 flow 한정 확장**

### `POST /api/v1/oauth/broker/tickets/exchange`

**요청·주소는 v0.25와 동일.** HTTP Basic + JSON:

```json
{
  "ticket": "opaque_one_time_ticket_from_return_url",
  "client_state": "same_original_browser_state",
  "session_proof": "server_only_original_random_proof"
}
```

Agent 서버는 교환 요청 전에 **복귀한 브라우저가 시작한 pending 세션과 정확히 일치하는지** 검증해야 함. 타 브라우저 쿠키/전역 캐시에서 state·proof 차용 금지. 티켓은 60초 만료·1회 사용. 실패 시 세션 발급 금지.

신규 통합 flow `200` 예시(값은 예시용):

```json
{
  "broker_session": "opaque_server_only_broker_session",
  "sub": "existing-immutable-user-uuid",
  "scope": "openid profile email listing:read buyer_profile:read offer:read",
  "expires_at": "2026-12-18T09:00:00+00:00",
  "id_token": "eyJ...RS256-signed-JWT...",
  "identity_token_type": "JWT"
}
```

기존 `broker_session`, `sub`, `scope`, `expires_at`는 유지. **신규 flow에서만** `id_token` 및 `identity_token_type`이 추가된다. 기존 v0.25 Broker intents로 시작한 로그인에는 `id_token`을 추가하지 않는다. Refresh Token, Access Token은 이 응답에 없음. 절대 브라우저 URL·로그·HTML·JavaScript에 `id_token`, `broker_session`, `session_proof`를 공개하지 않는다.

`id_token`은 **Streamlit 서버만** 처리하며, 다음을 반드시 검증:

- RS256, `kid`→`https://projectagain.kr/api/v1/oauth/jwks` 제공 키, 서명 확인(다른 알고리즘/`none` 불허)
- `iss == https://projectagain.kr` 정확히 일치
- `aud == projectagain-streamlit-broker` 정확히 일치
- `exp`, `iat`, 필요 시 clock skew 소량, `token_use == broker_unified_identity`
- `nonce == 시작 시 생성한 login_nonce`
- `session_binding_hash == SHA256(서버 보관 session_proof)`
- `client_state_hash == SHA256(시작 시 생성한 client_state)`
- `sub`는 교환 응답 `sub`와 동일하고 형식이 UUID인 기존 계정 ID
- `auth_time`은 기존 플랫폼에서 인증한 시각; `email`과 `email_verified`는 email scope에 한해 포함

JWT 유효기간은 발급 후 **5분**. 이 JWT를 매 API 요청에 사용하는 세션 쿠키로 쓰지 말고, **검증 즉시 Agent의 브라우저별 서버 세션을 확립하는 신원 증명**으로만 사용. 서버측 연결 정보는 `broker_session`/`session_proof`와 함께 암호화 저장; 다른 브라우저·계정 전환 시 재사용 금지.

기존 Native OIDC issuer/discovery/JWKS/authorization/redirect `https://projectagain.streamlit.app/oauth2callback`는 그대로. `st.login()` 레거시 접속을 계속 지원.

## 5. 기존 보호 API — 계약 보존

`POST /api/v1/oauth/broker/access`: HTTP Basic + `x-broker-session` + JSON `session_proof`. Access Token은 15분, 만료 120초 전 필요 시 갱신. Refresh Token은 플랫폼 암호화 DB에만 보관, 최대 14일, 계열 최대 30일. PostgreSQL `SELECT FOR UPDATE`와 원자적 회전 보존. 여러 동시 GET에서도 Agent는 오직 이 API로 신선한 토큰 요청.

- `/broker/access` 오류 → **개인 API·유료 AI 실행 금지**(fail closed).
- 보호 GET 401 → Broker 강제 재확인 후 **최대 1회만** GET 재시도. 403 재시도·우회 금지.
- POST/거래 액션 401 → 자동 재전송 금지. 판매자 승인, 거래 실행, 결제, 소유권 이전 권한 없음.
- `POST /api/v1/oauth/broker/logout` → **해당 브라우저 Broker 세션/토큰 계열만 철회**, 관련 Agent 서버 세션·개인 캐시/대화 연결도 제거.
- 플랫폼 웹사이트 `/auth/logout` 쿠키 삭제는 Broker 철회와 별개. 비밀번호 변경·계정 전체 연결 철회는 기존 `auth_version` 및 revoke 로직 유지.
- `offer:draft`는 기존 `/api/v1/oauth/broker/intents`에서 별도 scope 동의 후 초안만 작성 가능, 플랫폼 승인 대기 정책 유지.

## 6. 운영 설정(비밀값 입력 금지)

**Platform Replit Production Secrets** 기존 값 보존:

- `OAUTH_ENABLED=true`, `OAUTH_ISSUER=https://projectagain.kr`
- `OAUTH_STREAMLIT_CLIENT_ID`, `OAUTH_STREAMLIT_CLIENT_SECRET`, `OAUTH_STREAMLIT_REDIRECT_URI` (레거시용, 값 변경하지 않음)
- `OIDC_SIGNING_PRIVATE_KEY_PEM`, `OIDC_SIGNING_KID` (기존 RSA 개인키 재생성 금지)
- `OAUTH_BROKER_ENABLED=true`, `OAUTH_BROKER_CLIENT_ID`, `OAUTH_BROKER_CLIENT_SECRET`, `OAUTH_BROKER_ENCRYPTION_KEY`, `OAUTH_BROKER_STREAMLIT_RETURN_URI` (기존 값 변경 금지)
- **신규** `OAUTH_BROKER_UNIFIED_LOGIN_ENABLED=true` (검증 전 `false`로 유지 가능)
- 기존 DB·App Storage·CSRF·일반 로그인 비밀값 유지. 신규 OAuth 클라이언트 등록 불필요.

Agent Streamlit Cloud 서버: 기존 Broker Basic client ID·secret 유지, 새로운 영속 브라우저별 세션 저장소, URL callback 처리 및 RS256 JWT 검사 어댑터 추가. 서버에서만 Broker 호출. 초기 버전에서 원치 않으면 기존 로그인 버튼 유지하고 새 흐름은 feature flag로 단계 적용.

### 마이그레이션

신규 Alembic `0014_unified_login` → `oauth_broker_intents.flow` 컬럼 추가(`legacy_broker` 기본값). 기존 DB row, access/refresh tokens, OAuth 코드, 사용자는 손대지 않음. **Development/Production DB 개별 백업 후 각각 upgrade head**; 절대 Development DB 내용을 Production에 덮어쓰지 않음.

## 7. 검증 시나리오

| 케이스 | 플랫폼 로컬 테스트 | 실환경 확인 필요 |
|---|---|---|
| 기존 계정 로그인 및 동의 후 JWT+Broker 교환 | 테스트 있음 | Replit + Streamlit E2E |
| 두 사용자/브라우저 상태 결속·교차 차단 | 테스트 있음 | 실브라우저 2개 |
| 동의 취소 → 티켓·토큰 없음 | 테스트 있음 | 실브라우저 |
| 기존 Broker·OIDC 하위 호환 | 회귀 테스트 | 실제 기존 Agent |
| 기본 범위·`offer:draft` 별도 동의 | 신규 scope 테스트 | UI 및 승인 대기 검사 |
| Access 120초 갱신·Refresh 회전 | 기존 Broker 테스트 | 실제 PostgreSQL 병렬 GET 3+ |
| 앱 새로고침/재배포·계정 전환 시 캐시 격리 | 서버 결속 테스트 일부 | **Agent 어댑터 구현 후 필수** |
| 원본 URL에 토큰 미노출 | URL 테스트 | 실제 proxy/logs 점검 |
| 기존 서비스 데이터/계정 보존 | 파괴적 migration 없음 | Production backup/upgrade/E2E |

**배포 상태**: 여기 문서가 생성되었다는 사실만으로 실제 Production 또는 Agent에서 단일 로그인 UX가 작동하는 것은 아니다. 플랫폼 v0.37 배포, Agent 인증 어댑터 연결, 양쪽 E2E가 모두 끝난 뒤 완료 판정한다.
