# ProjectAgain v0.23 — OAuth 2.0 / OIDC 통합 로그인 API 계약

**상태: 코드 구현 및 격리 테스트 완료. 실제 Replit ↔ Streamlit Cloud E2E 테스트 전.**

## 1. 기존 코드 감사 결과

- `backend/app/models.py` `User.id`: UUID 문자열 영구 식별자. 이메일을 식별자로 사용하지 않는다.
- `backend/app/security.py`: 이메일/비밀번호(PBKDF2), `market_session` HttpOnly SameSite=Lax JWT 쿠키 8시간, CSRF 헤더; 사용자 `auth_version` 변경 시 세션 무효화.
- `backend/app/main.py`: `/api/v1/auth/register`, `/login`, `/logout`, `/me` 재사용. 기존 `ServiceGrant` SHA-256 해시 저장/권한 범위/사용자 철회.
- `backend/app/stage2.py`: 비밀번호 재설정은 `auth_version` 변경, 이메일 인증 재사용.
- 기존 에이전트 전용 `auth_context`/`allowed()` 권한 모델은 `kind=agent`를 인식한다. 새 OAuth 액세스 토큰은 더 제한된 API 경로 화이트리스트로 필터링해 `agent` 컨텍스트에 매핑한다.
- 결제, 실제 권리 이전, 자동 거래 실행 권한은 부여하지 않는다.

## 2. 채택한 프로토콜

- OIDC Core (OAuth 2.0 Authorization Code + PKCE S256) 단일 사전 등록된 confidential client(서버 측 Streamlit).
- ID Token RS256, OIDC Discovery, JWKS, UserInfo 구현. `sub=users.id`.
- OAuth Access Token **opaque 15분**, Refresh Token **opaque 최대 14일/매 사용 회전(계열 총 30일 제한)**, 인증 코드 **120초/단회**.
- 클라이언트 인증: HTTP Basic (`client_secret_basic`) 또는 폼의 `client_secret_post`.
- Streamlit Cloud callback: **정확히** `https://projectagain.streamlit.app/oauth2callback` (환경 변수와 일치해야 함).
- 기존 플랫폼 브라우저 로그인 쿠키는 공유하지 않고, 플랫폼 로그인 URL로 브라우저를 보내 기존 세션을 확인한다. 기존 로그인 중이라면 비밀번호 재입력을 건너뛴다. 동의 화면은 매번 사용자에게 명시적으로 표시한다.
- `state`는 **Streamlit 클라이언트가 생성·브라우저에 바인딩·검증**한다. 서버는 매 요청에서 구문을 검사하고 콜백에 값을 그대로 반환한다. `nonce`는 서버에서 ID Token에 넣으며, Streamlit이 검증한다.
- 기존의 수동 `POST /api/v1/auth/agent-grants`, GET 목록, POST revoke는 변경하지 않는다.
- 배포 시 `OAUTH_ENABLED=true` 전에는 모든 OAuth/OIDC 기능 비활성화. 사용자에게 자동 적용되지 않는다.

## 3. 환경 변수 — 플랫폼 (Replit Secrets)

```ini
APP_ENV=production
OAUTH_ENABLED=true
OAUTH_ISSUER=https://<실제-Replit-공개-도메인>
OAUTH_STREAMLIT_CLIENT_ID=projectagain-streamlit
OAUTH_STREAMLIT_CLIENT_SECRET=<32자 이상 암호학적 난수; Streamlit에도 동일한 값>
OAUTH_STREAMLIT_REDIRECT_URI=https://projectagain.streamlit.app/oauth2callback
OIDC_SIGNING_PRIVATE_KEY_PEM=<안전하게 보관한 고정 RSA 2048+ 개인키 PEM; 개행을 \\n 으로 넣을 수 있음>
OIDC_SIGNING_KID=projectagain-oidc-v1
```

`JWT_SECRET`, `DATABASE_URL`, `PUBLIC_BASE_URL`은 기존 값을 보존한다. `OAUTH_ISSUER`는 `/.well-known/openid-configuration`이 공개되는 **ProjectAgain 플랫폼 주소**와 정확히 같아야 한다. Replit 새 인스턴스와 기존 인스턴스에서 동일한 RSA 키를 보존해야 OIDC 키 검증이 유지된다. 프로덕션에서는 OAuth client secret, HTTPS issuer, HTTPS redirect, RSA signing key가 없으면 503으로 실패한다.

**키 생성 방법(개인키를 Git/ZIP에 넣지 않음):** `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out projectagain_oidc_private.pem`을 로컬의 안전한 장소에서 실행한 후, 개인키를 Replit Secrets에만 저장한다. **키 파일을 웹 루트나 저장소에 복사하지 말 것.**

## 4. Streamlit Secrets 예시

Streamlit 최신 `st.login`은 OIDC를 지원하며 `authlib`가 필요하다. 아래 구성은 **로그인/ID 확인 및 15분 Access Token 사용**까지 호환된다. `st.login`은 Refresh Token을 노출하지 않으므로, 15분 이후 무중단 자동 갱신까지 필요하면 별도의 **서버측 OAuth 세션/토큰 저장 어댑터**를 사용한다.

```toml
[auth]
redirect_uri = "https://projectagain.streamlit.app/oauth2callback"
cookie_secret = "<Streamlit 전용 임의 문자열>"
client_id = "projectagain-streamlit"
client_secret = "<Replit OAUTH_STREAMLIT_CLIENT_SECRET과 동일>"
server_metadata_url = "https://<실제-Replit-공개-도메인>/.well-known/openid-configuration"
expose_tokens = ["access"]

[auth.client_kwargs]
scope = "openid profile email listing:read buyer_profile:read offer:read"
```

Streamlit 앱은 `st.login()`, `st.user.is_logged_in`, `st.user.sub`, `st.logout()`을 사용한다. Streamlit의 `st.user.tokens.access`가 있는 경우 서버에서 ProjectAgain API에 Bearer로 첨부한다. 발급받은 토큰은 화면에 표시하거나 사용자가 복사하게 만들지 않는다.

**중요:** 이 방법은 일반 OIDC 로그인 가능성을 제공하지만, 기본 Streamlit의 ID 쿠키는 30일까지 남는 반면 ProjectAgain Access Token은 15분이다. Streamlit은 Refresh Token을 `st.user`에 노출하지 않으므로 **`st.login()`만으로 자동 갱신까지 완료되었다고 간주하지 않는다.** 자동 갱신을 구현하려면 Streamlit 앱 측에서 PKCE + confidential code exchange를 수행하고 Refresh Token을 사용자별 암호화된 서버 저장소에 유지하거나, 별도의 BFF를 사용해야 한다. 다른 사용자/세션 간 `st.cache_resource` 등에 토큰을 공용 저장하지 말 것.

## 5. Endpoint 계약

### 5.1 Discovery / JWKS

- `GET /.well-known/openid-configuration` → `200`, `issuer`, `authorization_endpoint`, `token_endpoint`, `userinfo_endpoint`, `jwks_uri`, `revocation_endpoint`, 지원 scope/alg/PKCE 메타데이터.
- `GET /api/v1/oauth/jwks` → `200`, `keys[0]`: `{kty:"RSA", use:"sig", alg:"RS256", kid, n, e}`. 개인키 비공개.

### 5.2 인증 시작

`GET /api/v1/oauth/authorize?response_type=code&client_id=projectagain-streamlit&redirect_uri=https%3A%2F%2Fprojectagain.streamlit.app%2Foauth2callback&scope=openid%20profile%20email%20listing%3Aread%20buyer_profile%3Aread%20offer%3Aread&state=<랜덤 16~256자>&nonce=<랜덤 16~256자>&code_challenge=<S256 base64url>&code_challenge_method=S256`

- 등록된 **하나의 exact `redirect_uri`**만 허용. 잘못된 redirect URI는 400으로 거부하며 외부로 리디렉트하지 않는다.
- 아직 ProjectAgain 로그인하지 않았다면 303 → `/login?next=/api/v1/oauth/authorize?...`. 기존 로그인 완료 후 `next`로 돌아온다.
- 기존 플랫폼 쿠키 로그인 중이면 303 → `/oauth/consent?...`.
- `prompt=none`은 대화형 동의 없이 성공시키지 않으며 `login_required` 또는 `consent_required` 오류를 등록된 콜백에 반환한다.

### 5.3 동의 정보 / 동의 결정

- `GET /api/v1/oauth/authorize/details?<인증 시작 query>` — 기존 쿠키 세션 필요. `200` 응답 예:

```json
{"client_id":"projectagain-streamlit","client_name":"ProjectAgain AI 에이전트 (Streamlit)","redirect_uri":"https://projectagain.streamlit.app/oauth2callback","scopes":["openid","profile","email","listing:read","buyer_profile:read","offer:read"],"account_email":"user@example.com","user_id":"<영구-UUID>","execute_permissions":false,"private_asset_access":false}
```

- `POST /api/v1/oauth/authorize/decision` — **기존 HttpOnly 쿠키 + `X-CSRF-Token` 필수**.

```json
{"query":"response_type=code&client_id=...&...","approve":true}
```

- `200` 응답 `{ "redirect_to": "https://projectagain.streamlit.app/oauth2callback?code=<120초-단회-코드>&state=<원래-state>" }`.
- `approve=false`면 `{ "redirect_to": "https://projectagain.streamlit.app/oauth2callback?error=access_denied&state=..." }`.
- 동의 응답 URL은 서버가 등록한 callback 기준으로 조합된다. 인증 코드는 브라우저 주소를 지나지만 Access/Refresh Token은 서버간 POST에서만 반환한다.

### 5.4 인증 코드 교환

`POST /api/v1/oauth/token` (`application/x-www-form-urlencoded`, Basic client auth):

```text
grant_type=authorization_code
code=<콜백의 code>
redirect_uri=https://projectagain.streamlit.app/oauth2callback
code_verifier=<원래 PKCE verifier>
```

`200` (예시):

```json
{"access_token":"<opaque>","token_type":"Bearer","expires_in":900,"refresh_token":"<opaque>","scope":"openid profile email listing:read buyer_profile:read offer:read","id_token":"<RS256 JWT>"}
```

- `id_token.sub = users.id`, `aud = client_id`, `iss = OAUTH_ISSUER`, `nonce = 요청 nonce`, `auth_time`, `iat`, `exp`, `email`, `email_verified`.
- 동시 2회 또는 재사용 시 `400 {"error":"invalid_grant"}`. 인증 코드 만료 120초. PKCE S256 필수.

### 5.5 사용자 정보 조회

`GET /api/v1/oauth/userinfo` 헤더 `Authorization: Bearer <access_token>`

`200 {"sub":"<영구-UUID>","email":"user@example.com","email_verified":false}` (`email` scope 없으면 이메일 속성 생략). 만료/철회는 `401`.

플랫폼 기존 `GET /api/v1/auth/me` 역시 제한된 OAuth Bearer를 인식한다. 반환 `id`는 동일한 사용자 UUID. `GET /api/v1/listings`는 기존처럼 공개 조회가 가능하다.

### 5.6 허용된 API와 권한

| HTTP | 리소스 | 필요 scope |
|---|---|---|
| GET | `/api/v1/auth/me` | `openid` |
| GET | `/api/v1/my/listings`, `/api/v1/listings/{id}` | `listing:read` |
| GET | `/api/v1/buyer-preferences/me` | `buyer_profile:read` |
| GET | `/api/v1/offers`, `/api/v1/offers/{id}` | `offer:read` |
| GET | `/api/v1/agent/listings/{id}/preparation-context` | `listing:read` |
| GET | `/api/v1/favorites` | `listing:read` |
| GET/POST | `/api/v1/agent-actions` | `offer:draft` (POST는 기존 승인 대기만 생성) |
| GET | `/api/v1/agent-actions/{id}` | `offer:draft` |

OAuth Bearer는 **경로 화이트리스트**에 없는 요청을 403으로 차단한다. 예: `POST /api/v1/offers`, `/api/v1/agent-actions/{id}/approve`, 토큰 발급/권한 수정, 비공개 원본 파일 접근 등. `offer:draft`은 기본 로그인 권한에 포함되지 않으며, 사용자에게 별도 동의를 받은 경우만 요청할 수 있다. 기존 `AGENT_WRITE_MODE`와 서버의 거래 승인 검사도 그대로 적용된다.

### 5.7 갱신

`POST /api/v1/oauth/token` Basic client auth, form:

```text
grant_type=refresh_token
refresh_token=<opaque>
```

`200` → 새 15분 Access Token + 최대 14일 Refresh Token (계열 최초 발급 후 총 30일 이내, + 선택적 ID Token). **기존 Refresh Token 즉시 사용 중지**. 회전된 Refresh Token이 재사용되면 해당 발급 계열의 Access/Refresh Token을 전부 철회. 계열의 절대 유효기간은 최초 인증부터 30일로 제한되고 이후에는 재인증이 필요함.

### 5.8 로그아웃 / 연결 철회

- **Streamlit 사용자 화면:** `st.logout()` → Streamlit identity cookie 삭제. **이 명령만으로 서버 토큰이 철회되는 것은 아님.** 서버 측 토큰을 보관하는 어댑터 사용 시 먼저 revoke를 호출한다.
- **API 클라이언트 철회:** `POST /api/v1/oauth/revoke` Basic client auth, form `token=<access 또는 refresh>`. 200 `{}`. 토큰이 알려져 있지 않아도 200. 해당 발급 계열 전체 무효화.
- **ProjectAgain 계정 설정:** `GET /api/v1/oauth/connections` (기존 로그인 쿠키); `POST /api/v1/oauth/connections/revoke` (기존 쿠키 + CSRF). 해당 사용자/Streamlit 클라이언트의 활성 연결 전부 즉시 철회.
- **기존 플랫폼 로그아웃:** `POST /api/v1/auth/logout` → 기존 플랫폼 세션 쿠키 제거. 이미 발급된 OAuth 액세스 토큰은 자동 철회되지 않으므로 별도 철회가 필요하다.
- **비밀번호 초기화/계정 비활성화:** 기존 `auth_version`과 `is_active` 검사를 통해 OAuth 토큰도 무효화된다.

### 5.9 오류 계약

| 상태 | 본문/동작 | 원인 |
|---|---|---|
| 303 | 정상/오류 callback redirect | 로그인/동의 또는 OIDC 오류 처리 |
| 400 | `{"detail":"..."}` | 잘못된 client ID/redirect/scopes/state/challenge |
| 400 | `{"error":"invalid_grant"}` | 만료·재사용·검증 실패 코드/Refresh Token |
| 400 | `{"error":"unsupported_grant_type"}` | 허용하지 않은 grant |
| 401 | `{"error":"invalid_client"}` | 잘못된 client secret |
| 401 | `{"detail":"invalid_token"}` | UserInfo 액세스 토큰 무효 |
| 403 | `{"detail":"..."}` | 쿠키 CSRF 실패, OAuth 경로/권한 불허 |
| 503 | `{"detail":"..."}` | OAuth 비활성/운영 필수 설정 누락 |

모든 토큰 응답 `Cache-Control: no-store`. 클라이언트는 redirect된 state를 최초 저장 값과 constant-time 비교하고, ID Token의 issuer/audience/signature/nonce를 검증한다.

## 6. 보안·배포 체크

1. Replit Secrets에 `OAUTH_ISSUER`, client secret, RSA private key를 입력한 뒤 신규 DB 마이그레이션 `0010_oauth_oidc` 적용.
2. 승인·거절 UI는 `X-CSRF-Token`을 포함한 기존 `api()` 사용. 이미 로그인된 계정이면 비밀번호를 다시 묻지 않는다.
3. 클라이언트 등록·Redirect URI는 런타임 사용자 입력/와일드카드/도메인 접미사 비교를 사용하지 않는다.
4. TLS reverse proxy, CSP, 사용자 입력 정화, Referrer-Policy 등을 공개 배포 앞에서 별도로 검증. 외부 도메인으로 인증 코드를 보내는 URI 확장은 별도 보안 리뷰 필요.
5. OAuth 발급은 암호학적 난수 기반; DB에는 코드/토큰의 SHA-256만 남고 원문은 반환 시 한 번만 등장.
6. JWT 서명키를 분실하거나 교체하면 진행 중인 로그인 검증이 실패할 수 있다. 키 회전은 별도 운영 절차로 준비.
7. `OAUTH_ENABLED=false`로 신규 발급 차단 가능. 이미 발급된 OAuth 토큰을 즉시 전부 무효화하려면 DB의 OAuth 토큰 계열을 철회하거나 계정 설정의 연결 철회를 사용해야 한다.
8. 이메일 수신/인증이 프로덕션에서 설정되어 있는지는 별도로 확인. 현재 OAuth는 일반 로그인과 동일하게 미인증 계정에도 `email_verified=false`를 반환한다.
9. 운영 DB 및 데이터는 절대 초기화하지 말 것. 기존 `ServiceGrant` API는 마이그레이션 기간 유지.

## 7. 테스트 결과 및 남은 확인

- `backend/tests/test_oauth_oidc_v023.py`: OAuth/OIDC 신규 보안 테스트(세션 재사용, JWT/JWKS, 등록 콜백 일치, PKCE 불일치, 인증 코드 만료/재사용, 범위 제한, 기존 ServiceGrant 호환, Refresh Token 회전·재사용 공격·철회, CSRF, 비밀번호 변경 후 무효화).
- `backend/tests/conftest.py`는 테스트 전 `DATABASE_URL`을 임시 SQLite로 교체하고 끝나면 DB를 초기화하므로 운영 PostgreSQL에는 연결하지 않는다.
- 테스트 명령: `cd backend && APP_ENV=test python -m pytest -q tests/test_oauth_oidc_v023.py`.
- **실제 Replit↔Streamlit 연결, 토큰 갱신을 위한 Streamlit 측 안전한 저장, 모바일/브라우저 UX는 배포 뒤 별도 E2E 검증 필요**. 이 문서는 그 완료를 주장하지 않는다.

## 참고 규격

- OAuth 2.0 Security BCP RFC 9700: https://www.rfc-editor.org/rfc/rfc9700
- Streamlit st.login/OIDC: https://docs.streamlit.io/develop/api-reference/user/st.login
- Streamlit authentication: https://docs.streamlit.io/develop/concepts/connections/authentication
