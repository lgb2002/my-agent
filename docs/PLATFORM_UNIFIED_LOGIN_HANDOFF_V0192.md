# ProjectAgain 플랫폼 개발팀 전달 문서 — AI Agent 통합 로그인 UX 단일화 요청

- 작성일: 2026-11-18
- 요청자: ProjectAgain Streamlit AI Agent 개발 담당
- Agent 기준: **v0.19.1** (본 문서와 함께 배포하는 v0.19.2는 디자인만 수정; 인증은 변경하지 않음)
- Platform 계약 기준: **v0.23 Native OIDC**, **v0.25 OAuth Broker**
- 대상 배포 주소: **Platform `https://projectagain.kr`**, **Agent `https://projectagain.streamlit.app/`**
- 문서 성격: **플랫폼 측 신규 개선 요청 / 계약 설계안**. 본 문서의 신규 통합 플로는 **구현 확정이나 실운영 검증 완료를 뜻하지 않음**.

## 1. 현재 구조와 사용자 문제

현재 Streamlit Agent에서는 서로 다른 두 인증 단계를 거칩니다.

1. `st.login()` → Native OIDC 클라이언트 `projectagain-streamlit` → 플랫폼 로그인·동의 → `https://projectagain.streamlit.app/oauth2callback` → `st.user` 식별.
2. OIDC 로그인 완료 후 **별도 버튼**으로 Broker `POST /api/v1/oauth/broker/intents` → `projectagain-streamlit-broker` 권한 동의 → 플랫폼 내부 `/api/v1/oauth/broker/callback` → `https://projectagain.streamlit.app/?pa_broker_ticket=...&pa_broker_state=...` → 서버 간 `/tickets/exchange` → `/access` 및 Refresh Token 자동 갱신.

사용자는 실제로 동일한 ProjectAgain 화면을 연속 방문하고 인증/동의를 두 번 진행하는 것처럼 느낍니다. **목표는 사용자가 에이전트에서 'ProjectAgain으로 시작하기' 한 번으로 로그인과 필요한 API 권한 연결을 완료하게 하는 것**입니다. 이미 플랫폼에 로그인했다면 비밀번호 재입력을 최소화하고, 동의해야 할 권한은 명료하게 표시해야 합니다.

중요: 현재 **두 클라이언트와 두 복귀 경로는 의도적으로 다르며, 동일하게 변경하면 안 됩니다.** 단순 URL 변경이나 두 버튼을 숨기는 편법으로 해결하지 않습니다.

## 2. 플랫폼 측에 요청하는 사용자 경험

```text
[Streamlit AI Agent] ProjectAgain으로 시작하기
       ↓
[ProjectAgain 플랫폼] 계정 로그인(기존 세션 있으면 생략)
       ↓
[ProjectAgain 플랫폼] AI Agent 접근 범위 확인 및 명시적 동의
       ↓
[Streamlit AI Agent] 확인된 사용자 정체성 + Broker 세션 연결 완료
       ↓
개인 데이터 조회 / AI 작업(필요 시 Broker에서 토큰 갱신)
```

- 최초 1회 권한 동의는 **없애지 말고 하나의 사용자 여정으로 합칩니다**.
- 복귀 후 에이전트가 두 번째 인증 버튼을 요구하지 않는 것이 완료 조건입니다.
- 동의 취소, 미가입, 세션 만료, 계정 전환, 권한 갱신은 하나의 흐름에서 안전하게 처리해야 합니다.
- 플랫폼 및 에이전트의 로그인 상태는 서로 다를 수 있으므로 브라우저 세션의 실제 결속을 검증해야 합니다.

## 3. 설계 선택과 플랫폼의 제안 요청

### 권장 검토안: Broker 1회 승인으로 검증된 로그인 정체성과 API 접근 권한을 함께 연결

현재 Broker의 Ticket Exchange 응답은 `sub`(불변 사용자 UUID), scope, `broker_session`, 만료 정보를 돌려줍니다. 이 정보를 **Streamlit의 브라우저별 세션 결속·서버측 인증 검증과 함께** 이용해 1회 왕복으로 Agent 로그인 상태를 구성하는 방법을 우선 검토해주세요.

그러나 `sub` 문자열만 받는 것만으로 현재 `st.user`와 동등한 인증 보장을 제공한다고 가정하면 안 됩니다. 네이티브 OIDC 식별의 대체·연동 방식, 안정적인 브라우저 식별과 쿠키/세션 복원, 권한·서명 검증을 플랫폼과 Agent가 함께 정의해야 합니다. 이 방식을 택하면 Streamlit 앱의 인증 어댑터도 별도 변경이 필요합니다.

### 대안: Native OIDC 동의 여정에서 Broker 연결을 안전하게 연계

Streamlit OIDC 클라이언트와 Broker 클라이언트를 유지하되, 최초 로그인/동의 여정 내에서 Broker에 필요한 서명·세션 증명·scope를 확보하여 **두 번째 수동 동의/브라우저 왕복 없이** Broker 세션을 연결하는 설계도 검토 가능합니다.

이 경우에도 Broker의 별도 클라이언트 동의를 조용히 재사용하거나, 서로 다른 클라이언트에 대한 동의를 임의로 공유해서는 안 됩니다. 별도 클라이언트가 요청하는 권한과 동의 주체를 사용자에게 명확히 알리는 계약이 있어야 합니다.

**플랫폼 측 산출물 요청:** 두 방안의 보안·개발 비용을 비교하고 선택안을 명시한 후, 새 버전의 API 계약서와 구현/테스트를 전달해주세요. 새로운 endpoint 명·payload는 상호 합의 전까지 미확정입니다. **현재 v0.25 URL들을 임의 변경하지 마세요.**

## 4. 반드시 유지할 불변 조건

1. **기존 회원 시스템·`users.id` UUID·로그인 쿠키·CSRF·기존 OIDC를 삭제/교체하지 않음.** 플랫폼 일반 웹 로그인과 레거시 Native OIDC 클라이언트가 계속 작동해야 함.
2. PKCE S256, OIDC state/nonce/issuer/audience 검증과 Broker의 `session_proof` + 브라우저 세션 바인딩을 동등 이상 수준으로 유지. 여러 브라우저 탭/사용자 사이 credential 섞임 금지.
3. **Access/Refresh Token, `broker_session`, 클라이언트 비밀값, `session_proof`를 브라우저 URL·로그·HTML에 노출 금지.** 기존 일회용 ticket+state 복귀는 유지하거나 동급 안전 계약으로 대체.
4. Refresh Token은 플랫폼 Broker의 암호화 DB에만 보관. 15분 Access Token, 만료 120초 전 온디맨드 갱신, Refresh Token 최대 14일/계열 최대 30일, PostgreSQL 행 잠금·원자적 회전 정책 보존.
5. 기존 scope: `openid profile email listing:read buyer_profile:read offer:read`. `offer:draft`는 **별도 명시적 동의**와 플랫폼의 승인 대기 정책 보존. 거래 승인·실행·결제·권리 이전 등의 권한은 Agent에 제공하지 않음.
6. `/api/v1/oauth/broker/access` 실패 시 개인 API 및 유료 AI 실행 차단(fail closed), 401 시 GET만 최대 한 번 재시도, POST 자동 재전송 금지. 403 우회 금지.
7. 로그아웃/계정 전환 시 **해당 브라우저 Broker 세션을 철회**하고 Agent의 사용자별 캐시/대화 범위를 격리. 플랫폼 웹 로그인 쿠키 삭제와 Agent Broker 철회는 별개임을 명확히 설계.
8. `https://projectagain.kr`의 HTTPS issuer와 `https://projectagain.streamlit.app/`의 복귀 주소를 정확하게 등록. wildcard/도메인 접미사 일치 금지.
9. 기존 Production PostgreSQL의 계정·매물·거래/인증 데이터를 보존. 파괴적 마이그레이션/개발 DB 전체 복사 금지.

## 5. 플랫폼 요청 산출물 및 통합 검증 기준

### 플랫폼 개발자가 전달할 것

- 선택한 인증 아키텍처 설명 및 변경된 **플랫폼 API 계약서(요청/응답/오류/리다이렉트)**.
- 버전별 데이터베이스 마이그레이션(필요할 때만) 및 Replit Production Secrets **변수명만** 정리. 비밀값은 문서·코드에 넣지 않음.
- 최종 로그인 여정, 기존 OIDC와 Broker의 하위 호환 정책, 계정 전환/로그아웃/만료/철회 처리 설명.
- 샘플 요청/응답과 최소 권한 테스트, 기존 API 계약 회귀 테스트 결과.
- Agent 개발자가 구현해야 하는 후속 변경사항(브라우저 바인딩, 서버 세션 저장, 새 콜백·교환 계약 등)을 목록화.

### 양쪽에서 반드시 확인할 시나리오

| 시나리오 | 기대 결과 |
|---|---|
| 비로그인 신규 사용자 | 한 번의 시작 과정에서 로그인 + 동의 + 에이전트 복귀 |
| 플랫폼에 이미 로그인한 사용자 | 계정 재입력을 불필요하게 반복하지 않고 동의 진행 |
| 동의 거부 | 권한 연결 없이 명확한 안내; 개인 API/유료 AI 실행 없음 |
| 동의 완료 후 새로고침/재배포 | 브라우저별 안전한 세션 복원 또는 재인증 요구 |
| 브라우저 A/B에서 서로 다른 계정 사용 | UUID·대화·토큰·Broker 세션 간 교차 접근 없음 |
| 만료/철회/비밀번호 변경 | Broker 401 처리, 안전한 재로그인 유도 |
| 만료 임박 Access Token | 온디맨드 토큰 갱신 정상 |
| 3개 이상의 동시 private GET | 실 PostgreSQL에서 단일 원자적 Refresh Token 회전 |
| `offer:draft` 추가 동의 | 제한된 초안 생성만; 실행·승인 권한 없음 |
| 레거시 Native OIDC 접속 | 기존 `projectagain-streamlit` 콜백 정상 유지 |

## 6. 작업 분담과 진행 순서

1. **플랫폼 개발 채팅**: 통합 인증 방식 선택 → 신규 계약 제시/보안 검토 → 플랫폼 코드와 PostgreSQL 테스트 → 실제 Replit 배포 검증.
2. **AI Agent 개발 채팅**: 확정된 신규 계약서를 전달받은 후, 별도 버전에서 Streamlit 로그인 어댑터를 수정하고 계정/세션/저장소 격리 검증.
3. **양쪽 통합 테스트**: Streamlit Cloud + `projectagain.kr` 간 실제 로그인/동의/자동 갱신/로그아웃/계정 전환 E2E를 완료한 뒤 단일 로그인 UX 완료로 판정.

**이번 Agent v0.19.2 범위:** 사이드바의 새 대화·검색·최근 대화·하단 계정 메뉴 **디자인만 수정**. OIDC/Broker/API 코드는 수정하지 않으며, 플랫폼 통합 인증 구현은 위 계약 협의 이후 진행합니다.
