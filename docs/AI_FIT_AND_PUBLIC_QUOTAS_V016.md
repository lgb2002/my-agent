> **과거 버전 참고 문서:** 이 문서에 등장하는 내부 Mock 실행 모드와 가상 거래 기능은 v0.17에서 제거되었습니다. 현재 실행·배포·지원 도구에 관해서는 [`README.md`](../README.md)와 [`API_ONLY_V017.md`](API_ONLY_V017.md)를 우선하세요.

# v0.16 · AI 적합성 평가 / 공개 AI 사용량 제한

## 1. 실제 추천에 AI 적합성 평가를 쓰는 방법

기존 v0.13부터 후보별 AI 정성 평가(`agent/qualitative_review.py`)가 구현되어 있었으며, v0.16에서는 **이 점수가 어디에 반영되었는지 UI에서 보이도록 강화**했다. 완전히 새로운 범용 매물 가치 평가기가 아니다.

- **정량 조건 / 필수 조건은 Python**: 예산, 필수 기술, 위험 허용 수준, 가격/월 운영비 상한, 권리/검증 결손. 부적격 후보를 AI로 되살릴 수 없음.
- **공개 매물의 정성적 적합성은 OpenAI**: 사용자가 확인한 `qualitative_preferences`(예: 관리 편의, 광고 운영 여지)에 대해 각각 `MATCH / MISMATCH / UNKNOWN` 판단 및 정확한 공개 인용을 요구한다. 정성적 적합성은 개인화된 비교이지, 사업 성공 확률이나 수익/법적 권리 보증이 아니다.
- **점수 변경**: 항목별 MATCH +10, MISMATCH -10, UNKNOWN 0; 총 보정 범위 -20~+20. 사용자 선호가 없거나 검증 가능한 인용이 없으면 보정 0. `base_score` / `qualitative_adjustment` / `score`가 개별 후보에 저장된다.
- **후보량 제한**: 규칙 기반 상위 10개까지만 추가 모델 검토(비용 보호). 모형 평가 실패·예산 초과 시 기본 순위 유지. **고객의 선호가 결과를 무조건 바꾼다고 약속하지 않는다.**
- **근거 구분**: 판매자 공개 문구의 인용이 플랫폼 독립 검증과 동일하지 않음을 사용자에게 표시한다. 모델 판단과 원본 정보를 구분한다.

### 구체적인 예

사용자: "50만원 이하이며, 운영이 간단하고 유지 관리가 자동화된 웹서비스가 좋아".

매물 A: 초기 점수 72, 공개 설명 "매일 수작업으로 콘텐츠 갱신 필요" → AI 정성 불일치, 근거 인용이 확인되면 -10 → 62.

매물 B: 초기 점수 68, 공개 설명 "관리 자동화 기능 제공" → AI 정성 일치, 인용이 확인되면 +10 → 78.

이 예시는 작동 방식을 보여주는 가상 사례다. 실제 AI가 해당 판단을 내린다고 보장하지 않는다. 점수는 투자 가치, 가치평가, 성능 인증이 아니다.

## 2. 공개 AI 접근 제어

- **무료 공개 조회와 유료 AI 도구를 분리한다.** 공개 매물 조회는 로그인 없이 계속 가능하다.
- **유료 OpenAI 호출**은 인증된 사용자만 이용한다. 두 가지 방식 중 하나: (1) 개인 ProjectAgain 위임 토큰을 입력하고 플랫폼 `/auth/me` 검증 성공, (2) Streamlit OIDC 로그인으로 `st.user`의 검증된 `sub` 확인.
- Streamlit 방문자 UUID, IP, 사용자가 임의로 입력한 이메일/이름, 공유 Cloud Secrets 위임 토큰은 신원 증명이 아니다.
- 서버는 토큰과 이메일을 카운터 DB에 저장하지 않으며, 제공자/계정별로 해시된 고정 식별자만 사용한다. 로그에도 토큰·프롬프트를 기록하지 않는다.
- 인증되지 않은 방문자는 **제한된 비AI 명령형 도구 모드**만 이용한다. 저장소 접속 실패나 단가 누락이 발생하면 OpenAI 호출이 차단된다.

### 필수 Streamlit Cloud 환경변수 예시 (Secrets TOML)

```toml
OPENAI_MODEL = "gpt-4.1-mini"
ENABLE_OPENAI_CHAT = "true"
# OPENAI_API_KEY는 실제 키로 별도 설정
AGENT_MODE = "live"
# AGENT_STATE_DATABASE_URL 또는 AI_USAGE_DATABASE_URL에 PostgreSQL URL 필요
AI_USAGE_DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
AI_CALLS_PER_MINUTE = "4"
AI_CALLS_PER_USER_DAY = "30"
AI_GLOBAL_CALLS_PER_DAY = "300"
AI_USER_DAILY_USD = "0.20"
AI_GLOBAL_DAILY_USD = "2.00"
AI_MAX_RESERVED_CALL_USD = "0.04"
```

`psycopg[binary]`를 `requirements.txt`에 추가하고 배포해야 한다. 사용량 DB에 테이블 생성 권한도 필요하다. Postgres가 없다면 사용자 인증이 정상이어도 **유료 호출은 차단**된다.

프로젝트별 API 키를 변경하거나 모델을 바꾸면 모델 입력/출력 토큰 단가(`AI_INPUT_USD_PER_1M`, `AI_OUTPUT_USD_PER_1M`)를 갱신한다. 코드 기본 단가는 `gpt-4.1-mini`에만 적용한다. 금액은 **토큰 기반 추정치**이고 최종 청구서와 다를 수 있다. 호출 전 보수적인 예약액을 과금 예산에서 확보하고, OpenAI 응답에서 토큰 수가 확인되면 사용량을 정산한다. 응답 누락/네트워크 실패 시 비용이 발생했을 가능성을 고려해 예약액을 유지한다.

### 선택: Streamlit OIDC 로그인

Streamlit 1.67에서는 Google 등 OIDC 설정을 지원한다. 추가 패키지: `python -m pip install "streamlit[auth]"` (`Authlib` 포함). Cloud Secrets의 `[auth]`에 `redirect_uri`, `cookie_secret`, `client_id`, `client_secret`, `server_metadata_url`을 등록한다. Google OAuth 클라이언트를 별도로 생성해야 한다.

```toml
[auth]
redirect_uri = "https://projectagain.streamlit.app/oauth2callback"
cookie_secret = "실제_난수로_생성한_긴_문자열"
client_id = "Google_OIDC_CLIENT_ID"
client_secret = "Google_OIDC_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

OIDC 인증은 Streamlit 서비스 이용자의 신원을 확인하는 용도다. ProjectAgain의 개별 사용자 데이터 조회는 여전히 **ProjectAgain 위임 토큰과 스코프**가 필요하다. 두 인증은 서로 대체되지 않는다.

### 초기 운영 정책과 한계

- per-user 4회/분, 30회/UTC일, 예약 비용 $0.20/UTC일
- global 300회/UTC일, 예약 비용 $2.00/UTC일
- call당 예상 예약 상한 $0.04, 모델 출력 상한 800 토큰(일반 채팅 경로)
- 모든 계정·브라우저 세션·서버 복제본에서 **동일 PostgreSQL DB를 사용해야** 일관되게 제한된다. DB 원자적 잠금을 통해 동시 요청을 직렬화한다.
- 다른 프로젝트/API 키를 통해 발생한 비용, 모델 단가 변경, 이미 청구된 비용과 같은 외부 이벤트까지 제어할 수 없다. 실제 재정적 손실을 막으려면 **OpenAI 프로젝트 예산/알림과 API 키 권한**도 별도로 설정해야 한다.
- 테스트용 `AI_LOCAL_SQLITE=true`는 `AGENT_MODE=mock`에서만 사용한다. Cloud 공개 서비스에서 사용하지 않는다.

## 3. 검증 및 범위

- `python -m scripts.run_tests`로 모의 모델·SQLite 기반 테스트. 무인증 차단, 분당/일별/전체 한도, 다른 사용자 독립성, 단가 오류, 저장소 장애, 성공/실패 예약 처리, 자격정보 미저장, 기존 13개 도구 회귀 검증.
- 실제 Streamlit OIDC 로그인, 외부 PostgreSQL, OpenAI 유료 API 청구액, Replit 서버의 사용자별 위임 토큰 API 응답은 배포 환경에서 별도로 확인해야 한다.
- Live 쓰기 승인/실행 정책에는 변경 없음. 플랫폼 초안 생성 기능은 기존 `ENABLE_LIVE_DRAFTS=false`를 유지한다.
