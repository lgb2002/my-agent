# ProjectAgain Agent v0.18.1 — OAuth Broker 자동 갱신 연동

## 범위와 검증 상태

- 기준 소스: ProjectAgain Agent v0.18 전체 프로젝트.
- 플랫폼 계약: 사용자가 제공한 `ProjectAgain_Agent_Broker_API_Contract_v025(1).md` (Platform v0.25).
- **코드 구현 + 로컬 모의 통신 단위 테스트 완료.** 실제 Platform v0.25 배포, Streamlit Cloud 로그인 복귀, Supabase PostgreSQL, 다중 워커 원자성은 **미검증**. 운영 보안을 보증하지 않음.
- 기존 v0.18 Native OIDC 로그인은 Broker 설정이 없으면 전환기간 동안 그대로 동작하지만, **Native 경로에는 자동 갱신이 없다.** Broker 설정을 일부라도 입력하면 안전을 위해 Native 토큰으로 대체하지 않는다.

## 핵심 설계와 로그인 UX

Streamlit은 완전한 브라우저 세션 쿠키를 일반 Python 코드에서 안전하게 새로 발급할 수 없고, `st.session_state`는 OAuth 전체 리디렉션 이후 복원되지 않을 수 있다. 그래서 이 버전은 **기존 `st.login()`을 브라우저 인증의 기반**으로 유지한다.

1. 사용자가 처음 `ProjectAgain 계정으로 로그인`을 선택한다. Streamlit은 플랫폼 v0.23 native OIDC로 로그인하고 **검증된 ID Token의 랜덤 `nonce`와 고유 `sub`**가 Streamlit 인증 쿠키에 연결된다.
2. 다음 `ProjectAgain 작업 권한 연결`을 누른다. 서버가 새 무작위 `client_state`, `session_proof`를 만들고, Streamlit 인증 쿠키의 **개별 로그인 nonce·sub·issuer**에서 계산한 HMAC 연결 키에 묶어 PostgreSQL에 **암호화**한다.
3. 서버는 Broker `/intents`에 **증명값의 SHA-256만** 보낸다. 브라우저는 플랫폼에 접속해 명시적으로 동의한다. 플랫폼은 자기 서버에서 Refresh Token을 보관한다.
4. 60초 단회용 티켓이 Streamlit 홈페이지로 돌아오면 서버는 URL 매개변수를 바로 지운다. **해당 Streamlit OIDC 로그인 쿠키의 nonce, 사용자 ID, DB 보관 상태**가 일치할 때만 `/tickets/exchange`를 호출한다.
5. `broker_session`과 `session_proof`는 별도 Fernet 키로 암호화하여 Streamlit 전용 PostgreSQL에 저장한다. 실제 OAuth Refresh Token은 **절대로 Streamlit에 도착하지 않는다.**
6. 이후 로그인된 개인 API와 유료 AI를 사용하기 전 `/broker/access`를 서버-서버 호출한다. 플랫폼이 남은 Access Token 유효기간이 120초 이하일 때 원자적으로 회전한다. 조용히 갱신되며 백그라운드 타이머는 사용하지 않는다.
7. 안전한 GET에서 downstream 401이면 해당 액세스 토큰의 해시를 함께 보내 **최대 1회 강제 갱신**하고 GET을 한 번만 재시도한다. POST 등 변경 요청은 자동 재전송하지 않는다.
8. 로그아웃 시 `/broker/logout`을 호출하고 Streamlit의 해당 세션 연결·계정 데이터를 폐기한다. 플랫폼 네트워크 장애로 철회를 확인할 수 없으면 플랫폼 계정의 연결 관리에서 확인해야 한다.

**UX 한계:** 이 버전은 *처음 연결 시* 계정 로그인과 Broker 권한 동의를 두 단계로 나누어 진행한다. 이는 Streamlit 내에서 티켓을 안전하게 브라우저 로그인 세션에 바인딩하기 위한 선택이다. 따라서 최초 클릭 한 번으로 모든 동의가 끝나는 사용자 경험은 아직 아니다. 연결 후에는 매 15분 재로그인 없이 자동 갱신한다(갱신 가능한 동안).

## 필수 선행 조건

**플랫폼 Replit:** v0.25 전체 소스를 적용하고 운영 DB를 백업한 뒤 `0011_oauth_broker` 마이그레이션. 기존 OIDC(`OAUTH_ENABLED=true`) 유지, 별도 Client/Secret/Fernet 설정 완료, 플랫폼 브로커 `OAUTH_BROKER_ENABLED=true`는 Streamlit 준비 및 검증에 맞춰 활성화. 자세한 순서는 플랫폼 v0.25 계약서의 200~211행을 따른다. `OAUTH_BROKER_CLIENT_SECRET`은 Native OIDC 비밀값과 **다르게** 생성한다.

**Streamlit requirements.txt:** 기존 의존성을 지우지 않고 추가:

```text
authlib>=1.3.2,<2
psycopg[binary]>=3.2,<4
cryptography>=43,<50
```

**Streamlit Secrets (실제 키는 공개 저장소·채팅에 넣지 말 것):**

```toml
MARKETPLACE_API_URL = "https://실제-ProjectAgain-플랫폼-주소"
PROJECTAGAIN_API_ORIGIN = "https://실제-ProjectAgain-플랫폼-주소"
PROJECTAGAIN_BROKER_CLIENT_ID = "projectagain-streamlit-broker"
PROJECTAGAIN_BROKER_CLIENT_SECRET = "Replit의 OAUTH_BROKER_CLIENT_SECRET과 정확히 동일"
PROJECTAGAIN_BROKER_REDIRECT_URL = "https://projectagain.streamlit.app/"
AGENT_STATE_DATABASE_URL = "postgresql://..."  # 기존 Supabase PostgreSQL 연결 문자열
AGENT_BROKER_STORE_KEY = "Streamlit 전용으로 새로 생성한 Fernet 키"

[auth]
redirect_uri = "https://projectagain.streamlit.app/oauth2callback"
cookie_secret = "기존 Streamlit OIDC 쿠키 비밀값 유지"
client_id = "projectagain-streamlit"
client_secret = "기존 Streamlit OIDC 비밀값 유지"
server_metadata_url = "https://실제-ProjectAgain-플랫폼-주소/.well-known/openid-configuration"
expose_tokens = ["access"]

[auth.client_kwargs]
scope = "openid profile email listing:read buyer_profile:read offer:read"
```

`AGENT_BROKER_STORE_KEY`는 **Replit의 `OAUTH_BROKER_ENCRYPTION_KEY`와 별도 키**여야 한다. 로컬 터미널에서 생성한 문자열을 **Streamlit Secrets에만** 입력한다:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

동일 키를 재배포 후에도 유지해야 저장된 연결을 읽을 수 있다. 절대 `.env.example`, ZIP, GitHub에 실키를 기록하지 않는다. 키 분실·임의 변경 시 과거 연결은 복원할 수 없으므로 재로그인해야 한다.

`AI_USAGE_DATABASE_URL`은 기존 Supabase PostgreSQL 설정을 계속 사용한다. Broker는 `AGENT_STATE_DATABASE_URL`만 사용하며, 운영 시 SQLite 대체를 허용하지 않는다. PostgreSQL 연결에는 TLS를 요구한다.

## 실제 사용 시점

| 조건 | 실행 |
|---|---|
| 최초 로그인 + Broker 연결 | 사용자 동의 한 번, 개인 연결 생성 |
| API 요청 전 Access Token 만료 2분 이상 남음 | 기존 Access Token 유지 |
| API 요청 전 만료까지 120초 이하 | Broker 내부 자동 Refresh Token 회전 |
| 아무 요청도 없음 | 별도 자동 타이머 없음 |
| downstream 개인 GET의 401 | 관측 토큰 SHA-256과 함께 한 번 강제 갱신, GET 1회 재시도 |
| 권한 부족 403 | 자동 재동의/승격 없음 |
| 초안 생성 POST 응답 불명확 | 재전송 금지, 실제 플랫폼 상태 확인 필요 |
| Refresh Token 만료·철회·비밀번호 변경 | 개인 API/유료 AI 차단 후 다시 로그인 |
| Broker 503 | 기존 DB 연결 정보를 유지하고 요청 차단; 이전 Refresh Token 재전송 금지 |
| 로그아웃 | 해당 Broker 세션 철회 시도, Streamlit 로그인 쿠키 제거 |

계약서에 따르면 Access Token 15분, Refresh Token **최대 14일**, 처음 발급된 계열의 절대 유효기간 **30일**이다. 30일 지속 로그인을 보장하지 않는다.

## E2E 검증 필수 체크리스트

1. 플랫폼 `/.well-known/openid-configuration`, `/api/v1/oauth/jwks` 정상 및 issuer 일치.
2. Streamlit `st.login`으로 한 번 로그인한 뒤 Broker 연결 권한 동의 → 홈페이지로 복귀 → 사용자 계정 확인.
3. Streamlit 강제 새로고침과 Replit·Streamlit 재배포 후 **동일 브라우저 인증 쿠키 + PostgreSQL** 조건에서 연결을 재사용하는지 확인.
4. 토큰 만료 180초 전에는 갱신하지 않고 115초 전에는 한 번만 갱신, 연속 호출에서 이전 Refresh Token을 재사용하지 않는지 확인.
5. 실제 PostgreSQL에서 동일 세션 3개 동시 요청/서로 다른 사용자 세션/여러 탭의 교차 동작 검사.
6. API GET 실패 401 후 최대 한 번 재시도, 403 및 POST 자동 재시도 금지 확인.
7. 만료·철회·비밀번호 변경/계정 삭제 후 개인 API와 유료 AI 차단 확인.
8. 사용자 A의 브라우저에서 사용자 B의 callback ticket 사용 불가 확인.
9. SessionProof/BrokerSession/Refresh Token이 UI·로그·브라우저 URL·다운로드에 없는지 확인.
10. 실제 모바일 웹과 데스크톱에서 계정 연결/돌아오기/로그아웃 검증.

**아직 미검증:** Platform v0.25 실배포 상태, 네트워크 통합, 브라우저 쿠키·새로고침 바인딩, live PostgreSQL 동시성, 실제 OpenAI 과금 경로, Streamlit 렌더링. 로컬 단위 테스트의 성공만으로 운영 완성을 선언하지 않는다.
