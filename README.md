# ProjectAgain Agent v0.8 — Live API 연결 진단 및 매물 조회 보강

Streamlit 단일 앱입니다. **기존 `app.py` 실행 방식과 기존 12개 도구를 유지**하며, Live는 여전히 **읽기 전용(GET)**입니다. Replit의 별도 에이전트 서버를 시작할 필요는 없습니다.

## 기존 프로젝트에 적용

1. 현재 프로젝트와 `.env`, `.venv`, `requirements.txt`, `data/`를 백업하세요.
2. 이 ZIP의 파일/폴더를 기존 프로젝트에 **병합**합니다. 기존 `.env`, `.venv`, `requirements.txt`, `data/`는 덮어쓰거나 삭제하지 마세요.
3. 새 패키지 설치는 요구하지 않습니다. Python 3.12와 기존 `streamlit`, `requests`, `python-dotenv`, `langchain`, `langchain-openai`를 그대로 사용합니다.
4. VS Code Git Bash에서 `source .venv/Scripts/activate` 후 `python -m streamlit run app.py`를 실행합니다.
5. Streamlit Cloud의 코드를 GitHub에 push하고 앱을 재시작해 적용하세요.

## Streamlit Cloud Secrets (TOML)

```toml
AGENT_MODE = "live"
MARKETPLACE_API_URL = "https://YOUR-REAL-PROJECTAGAIN-REPLIT-HOST"
MARKETPLACE_AUTH_SCHEME = "bearer"
MARKETPLACE_INCLUDE_DEMO = "true"
OPENAI_API_KEY = "YOUR_OPENAI_KEY"
OPENAI_MODEL = "gpt-4.1-mini"
ENABLE_OPENAI_CHAT = "false"
```

실제 OpenAI 도구 호출을 원하면 `ENABLE_OPENAI_CHAT = "true"`로 **명시적으로** 바꾸세요. 키가 있다고 자동 활성화하지 않습니다. 공개 앱에서는 모든 방문자가 OpenAI API 비용을 발생시킬 수 있으므로, 사용자 인증과 사용량 제한을 갖추기 전에는 비활성화한 상태에서 공개 매물 연동을 먼저 점검하는 편이 안전합니다.

- 주소는 **호스트**를 기준으로 입력합니다. 코드가 `/api/v1`을 붙이며, 옛 `.../api/v1` 주소도 한 번만 정규화합니다.
- `MARKETPLACE_INCLUDE_DEMO`는 사이드바 체크박스 초기값입니다. 사용자가 화면에서 켜고 끌 수 있습니다.
- `MARKETPLACE_API_KEY`는 **일반 방문자 요청에 사용하지 않습니다.** 공용 Secrets에 넣은 12시간 위임 토큰이 모든 방문자에게 같은 계정 권한으로 적용되는 것은 위험합니다. 대신 ProjectAgain에서 발급한 **사용자별 단기 위임 토큰을 사이드바 비밀번호 입력칸에 연결**합니다. 그 후 `GET /api/v1/auth/me`를 확인할 수 있습니다. 브라우저 입력과 서버 간 HTTP 요청에만 사용하고, 디버그·UI 응답에는 출력하지 않습니다.
- 토큰을 이미 Secrets에 저장했다면 운영상 제거 및 새 토큰 발급을 권장합니다. 만료된 토큰은 재발급해야 합니다.

## Live 연결을 검증하는 순서

1. 앱 상단에 `플랫폼 조회 · 읽기 전용`이 나타나는지 확인합니다. `샌드박스`면 `AGENT_MODE` 설정을 확인합니다.
2. 사이드바 **시연 매물 포함** 체크박스를 켭니다.
3. 사이드바 **API 연결 진단 → 연결 상태 검사**를 누릅니다. 이 동작은 **실제 HTTPS GET**을 보냅니다.
4. 결과에서 `일반 공개 매물`, `시연 매물 포함`, `사용자별 토큰 인증`을 각각 확인합니다. 각 줄에 HTTP 상태와 건수 또는 안전한 오류 원인이 표시됩니다.
5. 공개 조회가 200이고 시연 포함 건수가 양수라면 채팅에서 `현재 등록된 매물 목록 보여줘`를 입력합니다.
6. 개인별 인증을 확인할 때만 자신의 위임 토큰을 사이드바에 넣고 진단을 다시 실행합니다. 공개 조회 200은 인증 성공의 증거가 아닙니다.
7. OpenAI는 사이드바 **OpenAI 실행 상태**에서 키 감지와 활성화 플래그를 구별하여 확인합니다. '설정상 활성화'는 유료 모델 호출 성공을 뜻하지 않습니다.

매물 조회가 0건이어도 `HTTP 200 / items=[]`인 경우와 `HTTP 401, 403, 500, 네트워크 연결 실패, JSON 계약 오류`는 구분합니다. **오류를 매물 0건으로 바꾸지 않습니다.**

## 검증 한계

이 프로젝트 ZIP에는 실제 Replit 운영 주소와 사용자 Streamlit Secrets의 내용이 들어 있지 않습니다. 따라서 이번 수정 작업에서 **Replit 실제 도메인으로 HTTPS 조회나 실제 위임 토큰 인증, 유료 OpenAI 모델 호출을 성공했다고 주장하지 않습니다.** 배포한 사용자가 위 진단을 실행하면 운영 서버에서의 실측 결과를 볼 수 있습니다.

자동 테스트: `python -m scripts.run_tests`. 모의 HTTP 기반 공개/시연 필터·인증·JSON 파싱·오류·기존 작업 승인·도구 호출 회귀 테스트를 포함합니다.
