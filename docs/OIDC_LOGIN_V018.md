> **역사 문서 (v0.18):** 자동 갱신이 없는 OIDC 로그인에 관한 기록입니다. v0.18.1 Broker 구현 및 배포는 [`OAUTH_BROKER_AUTO_REFRESH_V0181.md`](OAUTH_BROKER_AUTO_REFRESH_V0181.md)를 우선 참조하세요.

# ProjectAgain Agent v0.18 — 통합 로그인 연결 및 운영 계약

기준: ProjectAgain 플랫폼 v0.23 OAuth/OIDC API 계약서(동봉). 플랫폼의 실제 공개 도메인·배포·DB 마이그레이션은 이 프로젝트에서 확인하지 않았음.

## 실제 구현 범위

- Streamlit OIDC `st.login()` / `st.user` / `st.logout()`로 기존 ProjectAgain 계정 로그인.
- 수동 ServiceGrant 입력 UI 제거. 기존 서버의 수동 토큰 발급 API는 에이전트에서 더 이상 사용하지 않지만 플랫폼의 호환성은 유지.
- OIDC 서명 검증/state/nonce/PKCE는 Streamlit/Authlib에 위임. 최신 Streamlit에는 공급자의 OIDC Discovery PKCE S256 지원 정보가 있어야 함.
- 로그인해도 바로 유료 AI·개인 API를 열지 않음. 로그인 사용자의 ID Token `iss`/UUID `sub`를 확인하고, **노출된 사용자별 Access Token**으로 `/api/v1/oauth/userinfo`와 `/api/v1/auth/me`를 모두 조회해 `sub == me.id`인 경우에만 연결 상태로 간주.
- 개인 데이터 API는 검증된 Access Token으로만 호출. AI 사용량, 계정별 저장·복원, 대화 아카이브는 영구 사용자 UUID와 플랫폼 URL 기반 동일한 사용자 키를 사용. Access Token이 회전해도 사용자 식별자는 변하지 않음.
- 공개 매물 조회 및 플랫폼 시연 매물 필터는 로그인 없이 이용 가능.
- 로그아웃 시 `POST /api/v1/oauth/revoke`에 액세스 토큰을 보내 가능한 범위에서 철회한 뒤 Streamlit 로컬 세션 로그아웃. 철회 실패 시에도 Streamlit 인증 쿠키는 지움. 플랫폼 브라우저 세션과 별개이며 플랫폼 전체 로그아웃을 뜻하지 않음.
- 에이전트는 거래 승인·실행/권리 이전을 호출하지 않음. 플랫폼 구매 제안 초안은 기존처럼 `ENABLE_LIVE_DRAFTS=false`를 기본값으로 유지하고 `offer:draft`가 없는 사용자에게는 추가 동의가 필요하다고 표시.

## 배포 선행 조건

1. Replit 플랫폼 v0.23이 실제 배포되어 `0010_oauth_oidc` 마이그레이션 적용, `OAUTH_ENABLED=true`, 유효한 RS256 키, 정확한 issuer/redirect URI/클라이언트 등록이 설정되어 있어야 한다. **통합 테스트 전에는 운영 전환을 완료했다고 판단하지 않는다.**
2. Streamlit의 기존 `requirements.txt`에 `authlib>=1.3.2,<2` (또는 `streamlit[auth]`)와 PostgreSQL 필요 시 `psycopg[binary]>=3.2,<4`를 추가한다. 기존 Streamlit은 PKCE 자동 지원 버전 사용을 권장하며, 플랫폼 OIDC Discovery의 `code_challenge_methods_supported`에 `S256`이 표시되어야 한다.
3. Streamlit Cloud Secrets에 다음을 추가한다. 따옴표 안 값은 **예시**이며 실제 값을 공개 채팅/GitHub에 올리지 않는다.

```toml
[auth]
redirect_uri = "https://projectagain.streamlit.app/oauth2callback"
cookie_secret = "충분히_긴_임의의_문자열"
client_id = "projectagain-streamlit"
client_secret = "Replit에서_설정한_동일한_클라이언트_비밀값"
server_metadata_url = "https://플랫폼_공개_도메인/.well-known/openid-configuration"
expose_tokens = ["access"]

[auth.client_kwargs]
scope = "openid profile email listing:read buyer_profile:read offer:read"
```

**선택적 `offer:draft` 추가 동의:** 실제 플랫폼 초안 API 계약 및 OAuth 흐름을 검증하고 `ENABLE_LIVE_DRAFTS=true`로 켠 경우에만 사용. 다음 **별도의 등록된 provider 설정**을 추가하면 로그인 중 `제안 초안 권한 추가` 버튼이 나타난다. 사용자 동의가 실제로 `offer:draft`를 발급하는지 E2E 검증 필요.

```toml
[auth.drafts]
client_id = "projectagain-streamlit"
client_secret = "Replit에서_설정한_동일한_클라이언트_비밀값"
server_metadata_url = "https://플랫폼_공개_도메인/.well-known/openid-configuration"
[auth.drafts.client_kwargs]
scope = "openid profile email listing:read buyer_profile:read offer:read offer:draft"
```

`[auth]`와 `[auth.drafts]` 구성 조합의 실제 Streamlit 동작은 검증 전까지 활성화하지 않는 것이 안전하다.

기존 최상위 `MARKETPLACE_API_URL`은 `OAUTH_ISSUER`와 동일한 HTTPS 호스트를 가리켜야 한다. 기존 `AGENT_STATE_DATABASE_URL`, `AI_USAGE_DATABASE_URL`, OpenAI Secret은 유지한다. 사용자별 OpenAI 호출은 공용 PostgreSQL이 연결되어야 허용된다.

## 액세스 토큰의 15분 제한

플랫폼의 Access Token은 15분, 인증 코드는 2분, Refresh Token은 최대 14일/계열 30일(회전 방식). **Streamlit `st.login()`은 Refresh Token을 앱 코드에 노출하지 않는다.** 이 버전에서는 무중단 갱신을 구현했다고 주장하지 않는다. 토큰이 만료되면 개인 API와 유료 AI를 차단하고 사용자가 다시 로그인하도록 안내한다. 로그인 제공자의 기존 8시간 웹 쿠키는 별개로 동작하므로 비밀번호 입력을 건너뛸 수 있으나 재동의가 필요할 수 있다.

진정한 자동 갱신은 별도의 서버측 OAuth 토큰/세션 관리(BFF), PKCE 발급·교환, 암호화된 refresh 저장, 회전 원자성·재사용 탐지·계정별 폐기 처리가 필요하다. Streamlit 세션이나 전역 캐시에 리프레시 토큰을 편법 저장하지 않는다.

## 최종 통합 E2E 체크

- 플랫폼 Discovery/JWKS 200, issuer와 공개 도메인 및 PKCE S256 메타데이터 확인
- Streamlit 로그인 클릭 → ProjectAgain 로그인/동의 → 정확한 `/oauth2callback` 복귀
- `st.user.sub == /oauth/userinfo.sub == /auth/me.id` 확인, 잘못된 ID·issuer·권한 요청 차단
- 공개 조회/시연 필터/개인 구매 조건/제안 목록 확인, 다른 사용자 데이터 접근 차단
- 로그인 15분 후 개인 API 차단 → 재인증 후 정상 복구 및 계정별 기억 유지
- 다른 계정으로 전환 시 이전 사용자의 대화·작업·AI 잔여 한도가 섞이지 않는지 확인
- `offer:draft` 없이 쓰기 차단 및 실제 거래 승인/실행 API 호출 불가 확인
- 로그아웃·플랫폼 연결 철회·비밀번호 변경 후 인증 무효화 확인
- Streamlit Cloud Secrets/API 오류를 화면에서 비밀정보 없이 안내, 브라우저/모바일 검증

## 검증 범위

코드 및 오프라인 단위/회귀 테스트만 실행. 실제 플랫폼 v0.23 공개 배포, 로그인 왕복, Streamlit Cloud 브라우저, Refresh 자동 갱신은 **미완료**.
