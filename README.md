# Digital Asset Agent — 대화형 거래 지원 에이전트

디지털 프로젝트 매물을 **대화로 검색·추천·정적 검사하고, 협상 초안을 준비·승인**하는 Streamlit 기반 에이전트입니다. 사용자의 요청에 따라 허용된 도구를 호출하고 결과와 작업 기록을 대화 안에 표시합니다.

## 주요 기능

- 공개 매물 검색, 예산·기술 수준·운영비·위험 허용도 기반 추천
- 매물 메타데이터 검증과 판매자 ZIP 정적 검사(임의 코드 실행 없음)
- 구매 제안·역제안 준비, 사용자 승인 및 샌드박스 거래 처리
- 거래 후 인수인계 체크리스트와 작업 이력 조회
- OpenAI가 활성화되면 LangChain 도구 호출; 비활성화되면 제한된 규칙형 입력 처리

## 프로젝트 환경

- Python 3.12 / Streamlit 1.67.0 / LangChain / langchain-openai / python-dotenv / requests
- 단일 Streamlit 앱(`app.py`): 별도 로컬 API 서버 불필요
- `AGENT_MODE=mock`: 내장 샌드박스 매물 및 SQLite 사용
- `AGENT_MODE=live`: 외부 Replit 거래 플랫폼 HTTPS API 조회 전용. 현재 실제 플랫폼 인증 및 쓰기 기능은 미연동

## 실행

1. 압축 파일의 폴더 구조를 그대로 프로젝트 루트(`my-agent/`)에 복사합니다. **기존 `.env`, `.venv`, `requirements.txt`, `data/`는 덮어쓰지 않습니다.** 기존 `agent/core.py`를 포함한 내부 모듈 파일을 모두 배치해야 합니다.
2. `python -m pip show streamlit python-dotenv langchain langchain-openai requests`로 설치 상태를 확인하고 누락된 패키지만 설치합니다.
3. `.env.example`을 참고해 기존 `.env`를 수정합니다. API 키는 Git에 커밋하지 않습니다.
4. 실행합니다.

```bash
python -m streamlit run app.py
```

브라우저 주소는 보통 `http://localhost:8501`입니다.

## 환경변수

```dotenv
AGENT_MODE=mock
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ENABLE_OPENAI_CHAT=true
MARKETPLACE_API_URL=
MARKETPLACE_API_KEY=
MARKETPLACE_AUTH_SCHEME=bearer
```

- 유효한 OpenAI 키와 `ENABLE_OPENAI_CHAT=true`가 함께 설정되면 모델이 도구를 선택합니다. API 호출 비용이 발생할 수 있습니다.
- `AGENT_MODE=mock`은 실제 거래가 아닌 **샌드박스 데이터**를 사용합니다. 자금·계약·권리 이전은 수행하지 않습니다.
- `AGENT_MODE=live`는 현재 **조회만 허용**하며, 플랫폼의 실제 인증 규격을 별도로 확인해야 합니다. 공통 OpenAPI는 Bearer JWT를 기준으로 정의되어 있습니다.

## 대화 예시

| 입력 | 처리 |
|---|---|
| 현재 등록된 매물 보여줘 | 매물 검색 |
| 100만원 이하 Python 프로젝트 추천해줘 | 조건별 추천 |
| 첫 번째 매물 실사해줘 | 매물 메타데이터 검사 |
| 첫 번째 매물에 50만원 제안 준비해줘 | 제안 초안 준비 및 승인 요청 |
| 1번 매물 제안 내역 보여줘 | 협상 내역 조회 |
| 업로드한 ZIP을 검사해줘 | 판매자 ZIP 정적 검사 |
| 최근 작업 기록 보여줘 | 본인 작업 내역 조회 |

협상 관련 작업은 **대화 요청 → 사용자 초안 생성 → 원문·해시 확인 후 내용 승인 → 별도 전송 확인** 절차를 따릅니다. 모델은 사용자 대신 승인 버튼을 누를 수 없습니다.

## 폴더 구조

```text
my-agent/
├── app.py                   # Streamlit 채팅 화면
├── assets/style.css         # 디자인 스타일
├── .streamlit/config.toml   # 테마
├── agent/                   # 대화 오케스트레이션 · 도구 · 업무 엔진
├── core/                    # 설정 · SQLite · 정적 검사 · 정책 · HTTP 클라이언트
├── services/                # 샌드박스 거래 서비스 · 플랫폼 API 어댑터
├── fixtures/                # 가상 매물 및 정적 검사 자료
├── contracts/               # 플랫폼 OpenAPI 계약
├── specs/                   # 제품 요구사항과 품질 검증 기준
├── tests/                   # 회귀 및 문구 검증
├── scripts/                 # 실행 환경 확인 · 테스트
├── docs/                    # 구현·검증·운영 문서
├── .env.example             # 환경변수 예시
└── .gitignore               # API 키 및 로컬 데이터 제외
```

현재 `requirements.txt`는 사용 중인 가상환경에서 관리합니다. 참고 패키지 목록 `requirements.reference.txt`는 기존 파일을 자동 변경하지 않습니다.

## 검증

```bash
python -m unittest discover -s tests -v
python -m scripts.verify_environment
```

현재 회귀 테스트는 Python 3.13 Linux 환경에서 실행되었습니다. Windows Python 3.12 + Streamlit 1.67.0 UI와 실제 OpenAI·Replit API 연결은 별도 환경 검증이 필요합니다.

**범위 제한:** 샌드박스 계정은 실제 로그인/접근 제어를 대체하지 않습니다. 공개 배포하지 마세요. 비공개 코드·API 키·개인정보를 채팅에 입력하지 마세요. 정적 실사 결과는 보안·법적 권리·운영 성과를 보증하지 않습니다.
