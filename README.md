# ProjectAgain Agent v0.19.2 — 간결한 대화 사이드바 · 플랫폼 통합 로그인 설계 요청

**이번 Agent 변경은 디자인 전용**입니다. 사이드바의 큰 `새 대화` 버튼과 상시 검색창을 접고, 위쪽은 아이콘/텍스트 메뉴, 가운데는 최근 대화, 하단은 `내 계정`으로 재구성했습니다. 계정 메뉴는 작은 팝오버로 통합했으며, 기존 대화 선택·검색·삭제·자동 저장과 계정 전환·설정·로그아웃 동작은 보존했습니다.

**플랫폼 개발 채팅에 전달할 별도 요청 문서:** [`docs/PLATFORM_UNIFIED_LOGIN_HANDOFF_V0192.md`](docs/PLATFORM_UNIFIED_LOGIN_HANDOFF_V0192.md). OIDC 로그인과 Broker 권한 연결을 한 번의 사용자 여정으로 만들기 위한 요구사항이며, 이 Agent v0.19.2에서는 인증 흐름·API를 변경하지 않았습니다. 실제 단일 로그인 기능은 플랫폼 신규 계약과 Agent 후속 작업이 모두 필요합니다.

**배포:** v0.19.1 전체 소스 기반 신규 ZIP. 기존 GitHub 프로젝트에 병합 후 Streamlit Cloud 재시작. 새로운 Secrets, `requirements.txt` 변경, Supabase DB 변경, Replit 거래 플랫폼 재배포는 필요하지 않습니다. `data/`, 사용자별 데이터, `.env`, `.venv`, 실 Secret은 기존 값을 보존하세요.

**검증:** Python 오프라인 304개 테스트 모두 통과. 정적 Chromium fixture 390/768/1280px에서 가로 넘침 및 하단 메뉴 겹침 없음. 정적 미리보기는 실제 Streamlit UI 실행 검증이 아닙니다. 상세: [`docs/SIDEBAR_DESIGN_V0192.md`](docs/SIDEBAR_DESIGN_V0192.md).

---

# ProjectAgain Agent v0.19.1 — 빠른 대화·도구 실행 상태·작은 사이드바

**핵심 변경**: 대화 목록의 불필요한 Supabase 반복 조회와 대화 전체 해시 계산을 줄이고, 이전 대화를 선택하면 추가 재실행 없이 메인에 복원합니다. 긴 대화는 최근 메시지를 먼저 표시하며 과거 기록은 보존합니다. 실제 실행된 도구가 **지금 어떤 작업을 하는지 한국어로 단계별** 표시됩니다. 답변 생성 후 반복 화면 갱신을 줄이고 계정 메뉴와 새 대화 버튼의 세로 크기를 낮췄습니다.

**배포 필수**: 루트 `requirements.txt`에 **`psycopg_pool>=3.2,<4`**가 추가됐습니다. 전체 ZIP의 `requirements.txt`를 GitHub 프로젝트에 반영하면 Streamlit Cloud가 설치합니다. 별도 설치 스크립트·신규 Secret·Supabase DB 마이그레이션·Replit 플랫폼 재배포는 필요하지 않습니다.

**보존**: v0.19.0의 대화·조회 스냅샷 저장, 기존 Supabase DB, 계정별 소유권·권한 검증, OIDC/Broker·자동 갱신, 9개 도구, 기존 거래 승인 정책, `DESIGN.md` 유지. 사용자 `.env`, `.venv`, `data/`, 실제 Secret/DB는 덮어쓰지 마세요.

**검증**: Python 오프라인 299개 테스트 통과(실패 0). 실제 Cloud·OpenAI·Supabase 동시 사용자·실모바일·재렌더링 속도는 현장 검증이 필요합니다. **실시간 LLM 토큰 스트리밍은 제외**했으며 완료를 가장한 가짜 스트리밍은 없습니다.

[상세 변경 및 점검](docs/PERFORMANCE_AND_PROGRESS_V0191.md).

---

# ProjectAgain Agent v0.19.0 — 대화 중심 복원과 작업 이력 저장

**이번 버전:** 기존 대화를 열면 메시지가 메인 채팅에 직접 나타나고, 새 조회부터 매물 검색·추천·검토·개인 조회의 허용된 결과 스냅샷을 당시 시점과 함께 저장합니다. 이전 v1 기록은 이미 저장된 내용만 복구할 수 있습니다. 과거 거래/매물 상태는 실시간 정보가 아니며 필요할 때 별도 최신 조회를 진행합니다.

**UI:** 사이드바 중복 바로가기 제거, 날짜별 대화 목록과 검색 개선, 계정 전환/회원가입 안내/설정 팝오버, 간격 및 버튼 높이 재정비, 상단 헤더 잘림 보완. 메인 대화에 과거 도구 결과를 시간순으로 표시합니다. ZIP은 관련 대화에서 명시적으로 실행할 수 있습니다.

**보존 및 안전:** 기존 Supabase의 동일 `agent_saved_conversations` 테이블을 그대로 사용합니다. 이전 대화, 계정, 사용자 데이터, OIDC/Broker·권한·승인 정책을 유지합니다. 승인 카드, 토큰, 원본 HTTP 응답, ZIP 파일은 영구 저장하지 않습니다. Secrets나 새 패키지는 필요 없습니다.

**배포:** v0.18.9 기반 전체 프로젝트 ZIP을 GitHub에 병합하고 Streamlit Cloud를 재시작합니다. 기존 `.env`, `.venv`, `data/`, Secrets는 덮어쓰지 마세요. Replit 거래 플랫폼 재배포는 필요하지 않습니다.

**검증:** 286개 오프라인 테스트 통과. 실제 Streamlit Cloud+Supabase 다중 기기/계정 전환/모바일 렌더링은 실배포에서 추가 검증이 필요합니다. 상세: [docs/CHRONOLOGICAL_HISTORY_V0190.md](docs/CHRONOLOGICAL_HISTORY_V0190.md).

---

# ProjectAgain Agent v0.18.9 — 컴팩트 대화형 화면과 설정 모달

**최신 변경:** 첫 진입의 큰 소개 카드와 2×2 대형 버튼을 간결한 질문·입력창·작은 빠른 시작 버튼 네 개로 교체했습니다. 왼쪽은 새 대화와 매물 탐색/맞춤 추천 바로가기 아래에 최근 대화 목록을 집중 배치하고, 대화 관리·매물 표시·조건·작업 계획·ZIP 검사·계정·도구 안내는 하단 **⚙ 설정** 모달로 이동했습니다. 모든 버튼은 실제 기능에 연결되고, 기존 디자인 컬러와 승인 정책은 유지합니다.

**데이터:** 로그인 계정의 Supabase 자동 대화 저장, 과거 대화 복원, 본인 대화 삭제, 조건/작업 계획 동의 저장은 그대로입니다. ZIP은 현재 대화에서 명시적으로 검사를 시작한 경우에만 임시로 전달하며 DB에 영구 보관하지 않습니다.

**배포:** 기존 v0.18.8 전체 소스를 기준으로 누적 반영한 전체 프로젝트입니다. `my-agent` GitHub 저장소에 코드를 병합하고 Streamlit Cloud만 재시작하세요. Secrets, 실제 `.env`, 개인 `data/`, Supabase 데이터는 보존하세요. Replit 플랫폼 재배포 및 새 패키지 설치는 필요하지 않습니다.

**검증:** 오프라인 280개 테스트 통과, Chromium 정적 390/768/1280px 검수 완료. **실제 Streamlit Cloud 설정 모달·로그아웃·ZIP 검사·대화 복원 상호작용은 배포 후 검증이 필요**합니다. 상세: [docs/COMPACT_SHELL_V0189.md](docs/COMPACT_SHELL_V0189.md).

---

# ProjectAgain Agent v0.18.8 — 대화 중심 화면 · 로그인 계정 자동 저장

**변경:** 첫 화면의 자연어 입력창을 안내 영역 바로 아래로 이동하고 시작 카드를 간소화했습니다. 왼쪽 메뉴는 `새 대화 → 대화 검색 → 날짜별 대화 목록`을 중심으로 구성하고, 계정 메뉴는 하단으로 이동했습니다. 필요 없는 상시 도구 나열과 일반 사용자용 진단 버튼은 제거하거나 숨겼습니다.

**대화 저장:** 본인 ProjectAgain 계정 연결이 확인되고 `AGENT_STATE_DATABASE_URL`의 PostgreSQL에 접근 가능하면 대화 문장과 안전한 도구 요약을 **자동 저장**합니다. 기존 수동 저장/자동 저장 선택 토글은 더 이상 노출하지 않습니다. 로그인하지 않은 사용자의 대화는 기존처럼 브라우저 세션에만 남습니다. 대화별 삭제와 전체 대화 삭제를 제공하며, 전체 삭제는 구매 조건·작업 계획·계정을 지우지 않습니다. 비밀정보가 포함되었다고 감지된 대화나 저장 용량을 초과한 경우에는 저장을 건너뛰고 일반 메시지로 안내합니다. 작업 승인카드·원본 API 데이터·토큰·ZIP 첨부는 저장하지 않습니다.

**배포:** 기존 v0.18.7 ZIP 파일을 기준으로 누적 변경했습니다. 새로운 Secrets·패키지·Replit 재배포·Supabase 스키마 초기화가 필요하지 않습니다. GitHub에 전체 프로젝트 코드를 반영하고 Streamlit Cloud 앱을 재시작하세요. 사용자 데이터, 개인 `.env` 및 Streamlit Secrets는 덮어쓰지 마세요. 실제 Streamlit Cloud 브라우저 상호작용과 타 기기 복원 검증은 아직 필요합니다.

상세: [`docs/CHAT_UI_AUTOSAVE_V0188.md`](docs/CHAT_UI_AUTOSAVE_V0188.md).

---

# ProjectAgain Agent v0.18.7 — 대화 중심 UI · Supabase 대화 저장

이번 버전은 첫 화면에 윤곽이 있는 시작 영역·4개의 작업 카드와 **독립된 대화 목록을 사이드바에 바로 표시**합니다. 사용자용 DB/운영 진단 버튼은 숨겼으며, 기존 진단 모듈은 개발자용 코드로 유지합니다.

**(v0.18.7 당시 동작, v0.18.8에서 변경됨)** 클라우드 대화 저장은 기본 OFF였습니다. 실제 ProjectAgain 계정으로 로그인하고 왼쪽의 `Supabase에 자동 저장`을 켜면, 기존 `AGENT_STATE_DATABASE_URL`의 PostgreSQL에 대화 문장과 안전한 도구 요약을 계정별로 저장합니다. 별도 Supabase 키나 새로운 Secrets는 필요하지 않습니다. 과거 저장 대화는 동일한 목록에서 복원할 수 있습니다. 상세 설명: [`docs/CHAT_NAVIGATION_V0187.md`](docs/CHAT_NAVIGATION_V0187.md).

기존 OAuth Broker 자동 갱신, 실제 API 전용 정책, 9개 도구, 승인/거래 경계, `DESIGN.md` 원칙을 유지합니다. `data/`, `.env`, `.venv`, 기존 Secrets 및 사용자 DB는 덮어쓰지 마세요. 오프라인 테스트 및 정적 CSS QA는 완료했고 **실제 Streamlit Cloud/Supabase 다중 기기 검증은 미완료**입니다.

---

> **v0.18.6 DB 진단 확장:** 연결 오류가 `기타 데이터베이스 연결 오류`로 분류되면, DNS·TCP 포트·libpq URI 해석·안전한 드라이버 오류 종류를 단계별로 추가 확인합니다. [진단 가이드](docs/BROKER_STORAGE_DIAGNOSTICS_V0186.md).

# ProjectAgain Agent v0.18.5 — 로그인 저장소 연결 진단

> OAuth 로그인 후 **로그인 저장소 연결에 실패했어요**가 표시되면 왼쪽의 **로그인 저장소 오류 진단 → DB 연결 진단 실행**을 선택하세요. DB 주소·비밀번호·호스트·원본 예외를 출력하지 않고, 접속 오류 유형·SQLSTATE(있을 경우)·조치 안내만 표시합니다. DB에는 읽기 쿼리만 실행합니다. 자세한 내용: [`docs/BROKER_STORAGE_DIAGNOSTICS_V0185.md`](docs/BROKER_STORAGE_DIAGNOSTICS_V0185.md).
>
> 기존 v0.18.4의 설정, 9개 도구, API 권한, OAuth Broker 자동 갱신, DESIGN.md, 사용자별 저장소, 승인 정책을 보존합니다. 신규 패키지 설치·Secret 재생성은 필요하지 않습니다. 전체 ZIP 배포 시 `.env`, `.venv`, `data/` 및 사용자 정의 패키지 항목을 유지하세요. 실제 외부 DB 연결 검증은 배포 환경에서 진행해야 합니다.

---

# ProjectAgain Agent v0.18.4 — Streamlit 대화 보관함 첫 실행 수정

> **v0.18.4 배포 수정:** Streamlit Cloud 최초 방문에서 대화 보관함이 `None`으로 초기화되어 앱이 중단되던 오류를 수정했습니다. 추가 명령이나 Secrets 변경 없이 전체 프로젝트를 GitHub에 반영하면 됩니다. 기존 계정 저장소/사용자 설정은 유지하세요.


이번 버전은 Streamlit Cloud가 읽는 루트 `requirements.txt`를 **직접 포함**합니다.
`cryptography`, `authlib`, `psycopg[binary]` 및 기존 실행 필수 의존성을 함께 선언했으며,
별도 설치 스크립트는 필요하지 않습니다. GitHub의 `app.py`와 같은 위치에 있는 `requirements.txt`를
이 파일로 업데이트한 뒤 커밋·푸시하면 됩니다.

기존 GitHub `requirements.txt`에 프로젝트 외 추가 패키지가 있었다면 해당 항목은 삭제하지 말고 새 파일에
유지해 주세요. `.env`, `.venv`, `data/`, 실제 Streamlit Secrets 및 PostgreSQL 사용자 데이터는 변경하지 않습니다.
대화 보관함 초기화 오류 외의 기능, API 권한, OAuth Broker 로직, DESIGN.md는 유지합니다.
실제 Streamlit Cloud/플랫폼 통합 검증은 별도입니다.

---

# ProjectAgain Agent v0.18 — 통합 로그인 적용 (플랫폼 v0.23 연동)

이번 버전부터 사용자는 **ProjectAgain 계정으로 로그인** 버튼으로 연결합니다. 에이전트 안에 위임 토큰을 복사·붙여넣는 입력창은 없습니다. 단, **플랫폼 v0.23의 OAuth/OIDC 활성화 및 실제 배포가 선행**되어야 개인 기능을 이용할 수 있습니다. 실운영 로그인 왕복은 아직 검증하지 않았습니다.

- 시작 순서와 정확한 Streamlit Cloud Secrets: [`docs/OIDC_LOGIN_V018.md`](docs/OIDC_LOGIN_V018.md)
- 플랫폼 계약서: [`docs/PLATFORM_OIDC_CONTRACT_V023.md`](docs/PLATFORM_OIDC_CONTRACT_V023.md)
- 기존 `requirements.txt`에 `authlib>=1.3.2,<2`를 추가하세요. PostgreSQL이 없는 경우 `psycopg[binary]>=3.2,<4`도 필요합니다. 기존 다른 패키지를 삭제하지 마세요.
- 공개 매물은 비로그인으로 이용 가능합니다. **개인 조회·저장·유료 AI는 `/oauth/userinfo`와 `/auth/me` 양쪽에서 동일한 UUID를 검증한 로그인 사용자만 이용**합니다.
- 중요한 제한: **API 액세스 토큰 만료 15분 후 재로그인 필요**. `st.login()`만으로 Refresh Token 자동 갱신을 구현하지 않았습니다. 무중단 자동 갱신은 별도 안전한 BFF/세션 어댑터가 필요합니다.
- `offer:draft`는 기본 로그인 범위에서 제외됩니다. 거래 승인·실행은 플랫폼 웹에서만 가능합니다. 실거래 관련 설정을 검증 전 활성화하지 마세요.
- 기존 `.env`, Streamlit Secrets, 개인 `data/`, 사용자별 PostgreSQL 저장소는 보존합니다.

---

# ProjectAgain Agent v0.17.4 — 시각 디자인 시스템 정비

**v0.17.3 기능 위에 적용한 시각·상호작용 고도화 버전**이야. 딥그린·오프화이트 정체성, API 전용 데이터, 9개 도구, 추천·대화 보관·작업 계획, 계정별 사용량 제한, 거래 승인 정책은 유지해.

이번 변경에서 **일반 대화·조건 입력은 820px 읽기 폭**, **제안 확인은 1040px**, **추천·검색·실사는 1220px 비교 폭**을 사용하도록 했다. 본문 글자 크기와 한국어 행간을 키웠고, 추천 근거 및 위험 상태를 표기할 때 자료 미확인/판매자 고지/정적 검사/문제 발견을 혼동하지 않도록 한다. 실행 중에는 `st.status`로 도구 요청의 진행 상황을 보여주며, 응답 수신이 거래 완료로 해석되지 않도록 문구를 구분한다.

**디자인 기준:** [DESIGN.md](DESIGN.md)는 9개의 시스템 영역(정보 구조, 화면 폭, 토큰/타이포그래피, 컴포넌트, 상태·사실 신뢰, 인터랙션, 반응형·접근성, 검수·변경 규칙)으로 재정리됐다. 특정 수정 요청의 나열이 아니라 제품 전반의 디자인 결정 기준으로 사용한다.

**적용:** 기존 v0.17.3의 파일을 백업하고 이 버전의 전체 ZIP 또는 수정 파일만 포함한 패치를 병합한다. `.env`, `.venv`, `requirements.txt`, `data/`, Streamlit Secrets는 기존 값을 유지한다. 모드 선택용 Mock 코드나 테스트 DB를 복구하지 않는다. 로그인 통합은 아직 반영되지 않았으며 플랫폼 계약을 받은 뒤 별도 적용한다.

**검증:** `python -m scripts.run_tests`로 실행한다. Chromium 정적 시각 점검은 `python docs/build_visual_preview_v0174.py` 및 `python docs/check_visual_viewports_v0174.py` (선택적 Playwright/Chromium 필요). **정적 미리보기는 실제 Streamlit 렌더링·로그인·API 통합 테스트가 아니다.** [docs/VISUAL_SYSTEM_V0174.md](docs/VISUAL_SYSTEM_V0174.md) 참조.

---

# ProjectAgain Agent v0.17.3 — 상태에 따라 달라지는 프로젝트 작업 공간

**핵심 변경:** 채팅을 없애지 않고, 현재 작업의 **결과·검증 상태·다음 행동**을 우선 보여줍니다. 사용자가 진행 중인 일에 따라 메인 영역이 바뀌며, 이전 대화 및 도구 사용 기록은 펼쳐서 읽습니다.

- **첫 방문:** 간결한 소개와 서로 다른 4개의 시작 작업.
- **매물 조회:** 플랫폼이 반환한 제목·가격·기술 정보를 표로 보며 프로젝트를 직접 선택해 공개 정보 검토로 연결. 페이지가 있다면 계속 조회.
- **추천 조건 확인:** 사용자가 직접 확인한 목적·예산·개발 경험·위험 허용도 등을 요약하고 작업 공간에서 바로 수정. 부족한 조건은 AI와 대화로 보충.
- **추천 완료:** 상위 후보 비교표 → 각 후보의 적합 근거와 확인할 위험 → 후보 공개 정보 검토·비교·제안 준비. AI의 상대 점수는 보조로만 제시.
- **공개 자료 실사:** 검사 결과의 발견 사항과 다음에 확인할 점을 구조화. 정적 자료 점검을 실행·법률·수익 검증 완료로 표현하지 않음.
- **제안 확인:** 사용자가 직접 확인할 대상 프로젝트·금액·초안 상태·제출 행동을 가장 먼저 보여줌. 플랫폼에서 별도 승인·실행.
- **다단계 작업·복원:** 완료와 미완료를 구분하는 단계 요약을 유지하고, 저장본에 실제 매물 데이터가 없으면 과거 기록만 보여주며 최신 조회를 안내.
- **대화:** 최신 결과가 먼저 보이고 전체 이전 대화는 동일 페이지의 펼침 영역에서 조회. 새 질문에 도구 호출 없이 AI가 답했다면, 이전 결과가 새 답변을 가리지 않음.
- **데이터·권한:** `core/workspace_state.py`는 세션의 **실제 도구 이벤트만** 화면에 연결하고 새 프로젝트·위험·거래 완료 상태를 추정하지 않습니다. 추천·거래·인증 정책과 9개 도구는 그대로 유지합니다.

**배포:** 기존 v0.17.2에 변경 패치를 병합하거나 전체 ZIP을 사용하세요. `.env`, `.venv`, `requirements.txt`, `data/`는 유지해야 합니다. 제거된 구버전 Mock 파일은 다시 넣지 마세요. 현재 사용자 인증은 기존 토큰 방식이며, 통합 로그인 API 계약 전까지 임의 변경하지 않았습니다.

**검증:** `python -m scripts.run_tests`. 코드를 기반으로 한 화면 상태·안전·기존 기능 테스트이며, 실제 Streamlit Cloud/모바일 브라우저와 Replit 실서버·OpenAI 유료 호출 검증은 별도입니다.

---

# ProjectAgain Agent v0.17.2 — 대화 보관·결과 신뢰성·문맥별 행동·모바일 개선

## v0.17.2의 달라진 기능

- **대화 보관함:** 새 대화를 시작해도 기존 메시지와 추천·작업 문맥을 브라우저 세션에서 유지합니다. 왼쪽 '대화 보관함'에서 이전 대화로 전환하거나 브라우저 보관본을 삭제할 수 있습니다. 새 대화로 전환하면서 이전 승인 카드는 폐기됩니다.
- **계정별 선택 보관:** 본인 계정을 연결하고 명시적으로 동의한 경우, '대화 장기 보관'에서 **저장 버튼을 눌러** 대화의 텍스트와 안전한 도구 요약을 PostgreSQL/SQLite에 저장·조회·삭제할 수 있습니다. **자동 저장되지 않습니다.** 원본 API 응답·토큰·승인 카드·거래 실행 상태는 저장/복원하지 않습니다. 로컬 SQLite는 Streamlit Cloud 재배포 후 보존을 보장하지 않습니다.
- **정확한 성공 상태:** '도구 응답 성공'과 '공개 자료 정적 검사', '플랫폼 제안 초안 등록', '거래 실행·권리 이전'을 명확히 구분합니다.
- **상황에 맞는 바로가기:** 검색 전에는 탐색, 검색 후에는 후보 검토/비교, 구매 조건이 있으면 조건 재사용 등을 우선 제안합니다. 개인 정보·거래 관련 도구는 계정 연결 필요성을 안내합니다.
- **서로 다른 시작 행동:** 첫 화면의 '실사 준비하기'가 매물 목록 조회를 단순 반복하지 않고 인수 전 확인할 자료와 위험을 알려줍니다.
- **추천 조건 UI:** 현재 대화의 조건을 사이드바에서 요약·수정합니다. 변경 후 새로운 추천 요청에 적용됩니다.
- **제안 확인 패널:** 매물, 제안 금액, 초안 상태, 제출/취소를 분리하고 기술적 식별번호는 접습니다.
- **사용자 언어:** 내부 상태를 가능한 한 한국어로 표기하되 상세 도구 기록에서 기술 정보는 확인할 수 있게 합니다.
- **반응형 CSS:** 좁은 화면의 대화/비교/승인 배치를 보강했습니다. 320~1280px 정적 브라우저 검증을 수행했으며 실제 Streamlit Cloud 실화면은 별도 확인이 필요합니다.

**인증 관련:** 통합 로그인 API는 아직 준비 중이므로 현재 위임 토큰 방식이 유지됩니다. 코드가 임의로 거래를 승인하지 않습니다.

**개발 검증:** `python -m scripts.run_tests`. 선택적 정적 브라우저 레이아웃 점검은 `python -m scripts.verify_responsive_static` (로컬 Playwright/Chromium 환경 필요).

---

# v0.17.1에서 유지한 기존 기반 — API 전용 · 대화/추천/작업 경험 개선

**ProjectAgain 플랫폼을 위한 Streamlit AI 에이전트**입니다. 프로젝트 검색·추천·공개 정보 점검·협상 초안 준비를 지원하며, 실제 매물 데이터는 **플랫폼 HTTPS API 한 곳에서만** 읽습니다.

## v0.17.1에서 달라진 사용자 경험

- **작업 진행률(A):** 실제 완료한 단계만 진행률에 포함합니다. 부분 완료·승인 대기·실행 제한·생략 단계는 완료로 계산하지 않고, 다음 행동을 별도 안내합니다.
- **추천 비교(B):** 상위 후보의 매물명·가격·적합 근거·주요 위험을 비교표로 제시합니다. 후보별 상세 근거와 후속 공개 정보 검토는 펼쳐서 확인합니다. AI 점수는 상대적인 판단 보조 지표입니다.
- **업무/채팅 구조(C):** 작업 계획은 압축된 상태 요약과 선택적으로 여는 상세 내역으로 변경합니다. 540px 고정 채팅 스크롤을 없애 페이지를 스크롤해 대화 처음부터 볼 수 있게 했습니다. 도구 바로가기와 기존 승인 카드 기능은 유지합니다.
- **브랜딩/설계 원칙:** `DESIGN.md`를 특정 수정 요청 나열 대신 상태 신뢰성·비교 가능한 결과·채팅 연속성이라는 일관된 기준으로 통합했습니다.

이번 릴리스는 **인증 API가 도착하기 전의 UI/UX 개선**이며, 토큰 입력을 통합 로그인으로 교체하지 않았습니다. 인증 전환은 별도 개발입니다.

## v0.17 API 전용 구조

- 내부 **Mock 모드 및 로컬 가상 거래 서비스 제거**. 시연용 사용자/거래 상태와 샘플 매물 JSON을 실행에 사용하지 않습니다.
- 기존 `AGENT_MODE`는 **설정할 필요가 없으며 입력되어 있어도 무시**합니다. 실제 플랫폼 URL을 설정해야 앱의 조회 기능이 동작합니다.
- **`시연 매물 포함`은 유지**합니다. 이것은 로컬 Mock 모드가 아니라 **실제 ProjectAgain 플랫폼에 등록된 시연 매물**을 API 응답에 포함시키는 필터(`include_demo=true`)입니다. 기본 체크 상태이며 사용자가 해제할 수 있습니다.
- 이전 13개 도구 중 로컬 가상 거래 전용 4개(`prepare_counter_offer`, `prepare_accept_offer`, `prepare_publish_report`, `prepare_handover_check`)를 제거해 **실제 플랫폼 데이터에 근거한 9개 도구**를 제공해요. 사용자의 구매 제안 초안은 별도 확인·권한 요건을 충족한 경우에만 준비/제출합니다.
- **자동 테스트용 가짜 API 응답은 계속 사용**합니다. 이는 배포된 사용자가 고르는 Mock 모드가 아니라, 테스트가 실제 데이터를 변경하지 않도록 하는 독립적인 검사 방식입니다.

## 실행

프로젝트의 기존 `.env`, `.venv`, `requirements.txt`, `data/`와 개인 설정 파일은 보존하세요. ZIP의 내용을 `app.py`가 있는 `my-agent` 폴더에 병합하여 사용합니다. 단, 구버전에서 제거된 다음 파일은 더 이상 필요하지 않습니다.

- `services/demo_marketplace.py` — 제거 대상
- `fixtures/demo_contract.json` — 제거 대상
- `data/mock_marketplace.sqlite3` — 구버전 로컬 테스트 데이터. **사용자 데이터를 확인하고 백업한 후에만** 삭제하세요. 코드는 사용하지 않습니다.

로컬 설치 환경에 필요한 패키지가 없다면 다음을 실행합니다.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

프로젝트의 기존 requirements.txt를 자동 교체하지 않습니다. PostgreSQL을 사용한다면 `psycopg[binary]>=3.2,<4`가 포함되어야 합니다. 일반 실행에 별도의 FastAPI 서버는 필요 없습니다.

## 설정: `.env` 또는 Streamlit Cloud Secrets

```dotenv
# 실제 ProjectAgain 플랫폼 호스트. API 접미사 /api/v1은 제외
MARKETPLACE_API_URL=https://YOUR-REAL-PROJECTAGAIN-HOST
MARKETPLACE_AUTH_SCHEME=bearer
# 플랫폼이 제공하는 데모 매물을 포함하는 API 필터
MARKETPLACE_INCLUDE_DEMO=true

# 자연어 이해 및 AI 맞춤 추천
ENABLE_OPENAI_CHAT=true
OPENAI_API_KEY=YOUR_PRIVATE_KEY
OPENAI_MODEL=gpt-4.1-mini

# 현재 준비 중인 플랫폼 액션 초안 전송은 기본 비활성
ENABLE_LIVE_DRAFTS=false

# 공개 유료 AI 사용량·예산 통제: 서버 공유 PostgreSQL 필요
AI_USAGE_DATABASE_URL=postgresql://...
# 개인 동의 기반 작업/선호 영속 저장(동일 DB 재사용 가능)
AGENT_STATE_DATABASE_URL=postgresql://...
SHOW_DEVELOPER_TOOLS=false
```

- `MARKETPLACE_API_URL`은 실제 배포된 HTTPS 플랫폼 주소를 넣습니다. 공개 매물은 위임 토큰 없이 조회할 수 있습니다.
- 사용자 전용 매물·제안·구매 프로필 조회는 각 사용자의 **본인 위임 토큰**과 해당 권한이 있어야 합니다. **공용 플랫폼 사용자 토큰을 Secrets에 두지 마세요.**
- 공개 유료 AI는 **검증된 방문자 신원 + 공유 PostgreSQL의 호출량 제한**을 모두 통과해야 작동합니다. 둘 중 하나라도 없으면 유료 AI 요청을 차단합니다. Streamlit OIDC를 선택적으로 설정할 수도 있습니다.
- `AGENT_STATE_DATABASE_URL`은 사용자가 저장을 선택한 작업 기록에 사용합니다. Streamlit Cloud의 로컬 DB는 재배포 후 보존되지 않습니다.
- 모델 키와 DB 연결 URL은 절대 GitHub에 커밋하지 않습니다.
- `ENABLE_LIVE_DRAFTS`는 플랫폼 초안 계약과 멱등성 실검증 전까지 `false`를 유지해야 합니다. `true`여도 **사람이 별도로 확인한 초안 생성**만 허용하며 에이전트가 승인·실행·정산하지 않습니다.

## 제공 도구 (9개)

| 도구 | 역할 |
|---|---|
| `search_listings` | 플랫폼 공개 매물 검색(시연 매물 필터 포함) |
| `recommend_listings` | 구매 조건 기반 후보 추천·정성적 AI 적합성 보조 평가 |
| `inspect_listing` | 공개 메타데이터 근거 점검 |
| `inspect_attached_zip` | 인증된 판매자의 업로드 ZIP **로컬 정적 검사**(실행/플랫폼 업로드 없음) |
| `list_offers` | 인증된 거래 제안 내역 조회 |
| `prepare_offer` | 구매 제안 초안 준비; 제출은 별도 확인 및 권한 필요 |
| `get_handover` | 인수인계 상태 조회 |
| `get_buyer_preferences` | 계정별 구매 선호 조회 |
| `get_recent_jobs` | 본인 작업 내역 조회 |

## 테스트 및 배포 점검

```bash
python -m scripts.run_tests
```

자동 테스트는 외부 플랫폼을 변경하지 않는 가짜 HTTP 응답을 사용하며, 이 테스트의 성공이 실제 Replit API·OpenAI 호출·Supabase 연결·Streamlit Cloud UI 성공을 의미하지 않습니다. 배포 후에는 순서대로 **앱 시작 → 공개 매물 조회 → 시연 매물 포함 토글 → 사용자 토큰 인증 → AI 사용량 조회**를 확인하세요.

화면/상태 검증 상세: `docs/UI_AB_C_V0171.md` · 전체 변경 내역: `CHANGELOG.md` · 현재 설치 지침: `docs/RUNBOOK.md` · 구조: `docs/API_ONLY_V017.md` · 디자인 원칙: `DESIGN.md`.

과거 버전별 설계 문서는 당시 기능 설명을 담은 **기록 자료**이며, 현재 배포 지침을 대신하지 않습니다.

## v0.18.1 — ProjectAgain 통합 로그인 자동 갱신

플랫폼 v0.25의 OAuth Broker를 이용해 Access Token 만료 전에 필요할 때만 갱신하는 코드가 추가되었다. 기존 수동 위임 토큰 입력은 계속 제거되어 있고, 플랫폼 API 단일 데이터 출처·거래 승인 정책은 변하지 않았다.

**실제 운영 적용 전 필수 읽기:** [`docs/OAUTH_BROKER_AUTO_REFRESH_V0181.md`](docs/OAUTH_BROKER_AUTO_REFRESH_V0181.md). 처음 한 번 기존 Streamlit OIDC 로그인과 Broker 권한 동의가 필요하며, 두 단계를 마친 뒤에는 Broker에서 Access Token을 자동 회전한다. 플랫폼 Replit v0.25 마이그레이션/활성화와 Streamlit PostgreSQL, 신규 Secrets, `requirements-broker-v0181.txt`의 추가 의존성 설치가 선행되어야 한다. 지금까지는 로컬 격리 테스트만 완료했으며 실배포 로그인 왕복은 미검증이다.

## v0.19.3 — Platform v0.37 단일 로그인 어댑터

신규 로그인 코드가 포함되었지만 **기본적으로 꺼져 있고 운영 E2E는 미검증**이다. 기존 Streamlit Cloud `app.py`와 OIDC/Broker 로그인은 유지된다. 통합 로그인을 사용하려면 운영 플랫폼 v0.37 + DB 마이그레이션 `0014_unified_login`, 배포용 `OAUTH_BROKER_UNIFIED_LOGIN_ENABLED=true`를 먼저 확인한 다음 Streamlit Cloud Main file path를 `unified_entry.py`로 변경하고, 기존 Secrets는 유지한 채 `AGENT_UNIFIED_LOGIN_ENABLED=true`를 추가한다. 테스트 전에는 `false`로 둔다.

자세한 실행 순서, 신규 서버 측 쿠키, 자동 토큰 갱신, 검증, 롤백 방법: `docs/UNIFIED_LOGIN_V037_AGENT_V0193.md`.
