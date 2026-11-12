# 국비 AI 에이전트 v0.4 — 대화 중심 · Tool Calling

이 프로젝트의 **메인은 채팅**입니다. 사용자가 자연어로 요청하면 `ChatOpenAI.bind_tools()`를 통해 등록된 도구를 선택하고, 동일 Python 프로세스에서 실제 추천·실사·협상 준비 작업을 실행합니다. **별도 FastAPI 서버나 Mock 거래 플랫폼 서버를 실행하지 않습니다.**

## 1. VS Code에서 실행

1. 기존 `my-agent` 폴더를 백업합니다. 새 ZIP의 `app.py`, `agent/`, `core/`, `services/`, `assets/`, `.streamlit/`, `fixtures/` 등을 폴더 구조 그대로 복사합니다.
2. **현재 사용 중인 `.venv`, `.env`, `requirements.txt`는 그대로 보존하세요.** ZIP에는 일부러 `requirements.txt` 대신 `requirements.reference.txt`만 넣어, 사용자가 `pip freeze > requirements.txt`로 갱신한 현재 버전 목록을 덮어쓰지 않게 했습니다.
3. 사용 중인 가상환경에서 다음을 한 번만 확인합니다.

```powershell
python --version
python -m pip show streamlit python-dotenv langchain langchain-openai requests
python -m pip check
```

누락된 것이 있으면 **누락된 패키지만** 설치하세요. 새 요구 패키지는 없고, 기존에 합의한 `streamlit`, `python-dotenv`, `langchain`, `langchain-openai`, `requests`를 사용합니다.

```powershell
python -m pip install python-dotenv langchain langchain-openai
```

실행 명령은 **한 줄**입니다.

```powershell
python -m streamlit run app.py
```

브라우저는 일반적으로 `http://localhost:8501`입니다.

## 2. `.env` 설정

기존 `.env`는 유지하고 필요한 설정만 확인하세요. 없다면 `.env.example`을 `.env`로 복사합니다. 절대 Git에 올리지 마세요.

```dotenv
AGENT_MODE=mock
OPENAI_API_KEY=여기에_본인_OpenAI_API_키
OPENAI_MODEL=gpt-4.1-mini
ENABLE_OPENAI_CHAT=true

MARKETPLACE_API_URL=
MARKETPLACE_API_KEY=
MARKETPLACE_AUTH_SCHEME=bearer
```

- `ENABLE_OPENAI_CHAT=true`와 유효한 OpenAI 키가 모두 있으면 **진짜 LLM 도구 선택**을 수행합니다. 대화 내용과 필요한 공개 매물 데이터 일부가 OpenAI API에 전송될 수 있고 비용이 발생합니다.
- 키가 없거나 기능이 꺼져 있으면 **제한된 규칙형 도구 체험 모드**로 동작합니다. 이 모드는 자유 대화를 온전히 이해하는 AI가 아니고 사전에 정해진 한국어 명령 일부를 인식합니다.
- `AGENT_MODE=mock`: 로컬 허구 매물과 로컬 SQLite를 사용해 체험합니다. 본인 PC 외부에서 거래를 하지 않습니다.
- `AGENT_MODE=live`: 준비된 Replit 플랫폼 HTTPS API로 **조회(GET)만** 합니다. 인증 형식은 별도 구현/검증이 필요합니다. 협상 전송·계약·결제·실제 자산 이전은 차단합니다.
- 원본 공통 OpenAPI는 **Bearer JWT**를 사용합니다. API Key 발급·권한 범위·만료 정책은 아직 Replit 플랫폼과 연동되지 않았습니다.

## 3. 채팅에서 가능한 업무

| 대화 요청 예 | 호출되는 도구 | 실행 정책 |
|---|---|---|
| “매물 목록 보여줘” | `search_listings` | 플랫폼/DEMO 조회 |
| “100만원 이하 Python 프로젝트 추천해줘” | `recommend_listings` | 조건 검사·작업 저장 |
| “첫 번째 매물 실사해줘” | `inspect_listing` | 메타데이터 검증(동적 실행 미검증) |
| “업로드한 ZIP 정적 검사해줘” | `inspect_attached_zip` | 판매자가 사이드바에 ZIP 첨부 후 실행, 코드 실행 금지 |
| “1번 매물 제안 내역 보여줘” | `list_offers` | 계정 권한 내 조회 |
| “1번 매물에 50만원 제안 준비해줘” | `prepare_offer` | **제안 초안 준비만**, 승인 카드 표시 |
| “제안 UUID에 78만원 역제안 준비해줘” | `prepare_counter_offer` | 판매자만 준비, 승인 카드 표시 |
| “판매자 역제안 UUID 수락 검토해줘” | `prepare_accept_offer` | 사용자 확인 후 DEMO 수락 |
| “검사 작업 UUID 보고서 제출 준비해줘” | `prepare_publish_report` | 확인 후 DEMO 검토 대기로 제출 |
| “거래 UUID 인수인계 항목 보여줘” | `get_handover` | 조회 |
| “인수인계 항목 등록해줘” | `prepare_handover_check` | DEMO 판매자, 확인 후 기록 |
| “최근 작업 기록 보여줘” | `get_recent_jobs` | 본인 기록 조회 |

**협상 승인 3단계:** ① 채팅으로 조건 생성(아직 아무것도 쓰지 않음) → ② 사용자가 **초안 생성** 버튼 → ③ 원문과 SHA-256을 보고 **내용 승인** → ④ 체크박스 확인 후 **DEMO 전송**. AI는 승인·전송 함수를 직접 호출할 수 없습니다.

## 4. 프로젝트 구성

```text
my-agent/
├── app.py                   # 채팅 중심 Streamlit UI, 유일한 실행 진입점
├── assets/style.css         # 새 디자인 시스템
├── .streamlit/config.toml   # 색상/테마
├── agent/chat.py            # LangChain tool-calling 오케스트레이터, 로컬 체험 파서
├── agent/tools.py           # 허용된 도구 목록 + 실행기 + 명시적 버튼 확인
├── agent/core.py            # 기존 추천·실사·승인 엔진
├── core/                    # 설정·DB·정적 검사·규칙·HTTP 클라이언트
├── services/                # 내부 DEMO 서비스 및 Replit 읽기 어댑터
├── fixtures/                # 허구 시연용 매물/ZIP
├── contracts/               # 원본 공통 OpenAPI
├── specs_snapshot/          # 원본 명세 및 평가 기준
├── tests/                   # 자동 회귀 테스트
├── scripts/                 # 환경 검증
├── docs/                    # 상세 구현 현황
├── requirements.reference.txt # 이전 환경 목록 참고용(기존 freeze 파일 덮어쓰기 방지)
├── .env.example             # 키 없는 템플릿
└── .gitignore               # .env / SQLite / .venv 제외
```

`.env`나 실제 API 키, 실행 중 생성된 SQLite DB는 프로젝트 ZIP에 포함되어 있지 않습니다. 기존 `data/`를 유지하면 로컬 DEMO 상태도 유지됩니다.

## 5. 검증

```powershell
python -m unittest discover -s tests -v
python -m scripts.verify_environment
```

자동 테스트는 Python 3.13 Linux 환경에서 실행했습니다. **Windows Python 3.12 + Streamlit 1.67.0에서 실제 브라우저를 직접 실행한 것은 아직 아니며**, 실제 OpenAI API 호출 또한 키가 없어 모의 모델로 도구 실행 흐름을 테스트했습니다. 따라서 로컬 앱과 OpenAI를 연결한 후 화면·모델 연결을 별도로 확인해야 합니다.

### 한계와 주의

- 완성된 범용 자율 에이전트가 아닙니다. 모델이 호출할 수 있는 것은 `agent/tools.py`의 **허용된 12개 도구**뿐입니다.
- 모델 사용 시 플랫폼에서 조회한 공개 내용 일부가 OpenAI에 전송될 수 있습니다. 비공개 소스, 개인정보, 키 입력을 피하세요.
- 소스 ZIP 검사는 정적 파일 분석만 수행하며, 보안·법적 권리·동적 실행 성공을 보증하지 않습니다.
- DEMO 계정은 로그인 인증을 제공하지 않으므로 다른 사용자에게 공개 배포하지 마세요.
- 본격적인 Replit 플랫폼 연결은 API 키 인증 계약과 실제 URL, 서버 권한이 구현된 이후 진행해야 합니다.
