# ProjectAgain Agent v0.9 — 대화형 맞춤 추천

ProjectAgain에서 디지털 프로젝트를 탐색·추천·검토하는 **단일 Streamlit 앱**입니다. 기존 v0.8의 채팅 UI, 도구 호출, API 연결 진단, Mock/Live 선택, 승인 정책을 유지하면서 **맞춤 추천에 필요한 정보를 대화로 수집하는 기능**을 개선했습니다.

## 이번 버전의 핵심 변화

- `맞춤 추천해줘`라고 말하면 에이전트가 구매 목적·예산·개발 수준·위험 허용도를 차례로 확인합니다. 같은 문장에 이미 답이 있으면 다시 묻지 않습니다.
- 사용자가 명시하지 않은 예산·개발 수준·위험 성향을 임의로 추정해 추천하지 않습니다. `모름`을 선택했을 때의 기본 가정은 응답에 표시합니다.
- Python 등의 필수 기술, 원하는 프로젝트 유형, 예산과 월 운영비 조건을 필터로 처리하고 **상위 3건과 추천 근거·주의사항**을 보여줍니다.
- 현재 방문자가 **본인 위임 토큰**을 연결한 경우 `내 프로필로 추천해줘`로 플랫폼에 저장된 구매 조건을 조회해 사용할 수 있습니다(`buyer_profile:read` 필요).
- 모델 사용 여부에 관계없이 같은 조건 수집 규칙이 적용됩니다. 등록된 다른 도구와 실제 거래 변경 차단 정책은 그대로입니다.

자세한 사양과 적용 범위: [`docs/RECOMMENDATION_V09.md`](docs/RECOMMENDATION_V09.md)

## 설치 및 실행

기존 VS Code 프로젝트를 백업하고 ZIP의 내용물을 기존 `my-agent/` 폴더에 **파일 단위로 병합**하세요. 기존 `.env`, `.venv`, `requirements.txt`와 `data/`는 덮어쓰지 마세요. 추가 설치 패키지는 없습니다.

Python 3.12, Streamlit 1.67.0 및 기존 `python-dotenv`, `requests`, `langchain`, `langchain-openai` 환경을 유지합니다.

```bash
source .venv/Scripts/activate
python -m streamlit run app.py
```

실제 Replit 연결 설정은 기존 `.env` 또는 Streamlit Cloud Secrets를 그대로 사용하세요.

```dotenv
AGENT_MODE=live
MARKETPLACE_API_URL=https://YOUR-PROJECTAGAIN-HOST
MARKETPLACE_AUTH_SCHEME=bearer
MARKETPLACE_INCLUDE_DEMO=true
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ENABLE_OPENAI_CHAT=false
```

- `AGENT_MODE=mock`: 로컬 가상 매물과 시연 도구 사용.
- `AGENT_MODE=live`: Replit 플랫폼 공개 API를 통해 매물 조회·추천, 사용자별 단기 위임 토큰으로 권한 있는 정보만 열람. **원격 변경은 차단**.
- Streamlit Cloud에 등록한 **공용 `MARKETPLACE_API_KEY`는 방문자 인증에 사용하지 않습니다**. 개인 정보 조회 시 사용자별 위임 토큰을 사이드바에 입력해야 합니다.
- `ENABLE_OPENAI_CHAT=true`는 실제 OpenAI 비용을 발생시킬 수 있으므로 공개 앱 사용량 보호 정책 없이 활성화하지 마세요.

## 확인할 추천 대화

```text
사용자: 100만원 이하 Python 프로젝트 추천해줘
에이전트: 어떤 목적으로 프로젝트를 인수하고 싶으세요?
사용자: 개발 학습이 목적이야
에이전트: 개발 경험은 어느 정도인가요?
사용자: 초보야
에이전트: 어느 정도 위험까지 받아들일 수 있나요?
사용자: 보수적으로
에이전트: 조건에 맞는 후보 중 상위 프로젝트와 근거를 제시
```

또는 `70만원 이하 Python 웹서비스 추천해줘. 개발 학습이 목적이고 초급, 저위험`처럼 한 번에 입력할 수도 있습니다.

## 테스트 및 제한

```bash
python -m scripts.run_tests
```

기존 업무 로직·보안·API 계약에 대한 회귀 테스트 및 추천 문답/정책 테스트를 실행할 수 있습니다. 테스트 결과는 `docs/test_results.json`에 저장됩니다.

**이번 테스트는 Python 프로세스 내부 로직과 모의 호출을 검증합니다. 실제 Streamlit 브라우저 렌더링, Windows Python 3.12, 배포된 Replit HTTPS, 실제 OpenAI API 호출은 별도 확인이 필요합니다.**

기존 화면의 시각적 디자인이나 승인 UI는 이번에 변경하지 않았습니다. `DESIGN.md`는 기존 v0.7 첫 화면 디자인 기준을 유지합니다.
