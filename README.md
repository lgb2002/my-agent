# ProjectAgain Agent v0.10 — 간결한 채팅 작업 공간

디지털 프로젝트 검색·맞춤 추천·실사·거래 초안 준비를 대화로 진행하는 단일 Streamlit 앱입니다. v0.9의 추천 문답, 12개 도구, Mock/Live API 연결, 사용자별 위임 토큰 및 기존 승인 정책을 유지합니다.

## 사용 화면 변경

- **시연 매물 포함**은 처음 열었을 때 체크되어 있습니다. 필요하면 해제할 수 있으며, Live API의 `include_demo` 값에 적용됩니다. 사용자 조작이 초기 환경변수보다 우선합니다.
- 필터를 켜거나 꺼도 **현재 대화는 유지**됩니다. 다만 이전 목록의 '1번 매물'이 새 필터와 혼동되지 않도록 저장한 목록 순번만 초기화됩니다.
- 긴 대화에서 기록이 삭제되지 않도록 **기존 80개 메시지 제한을 제거**했습니다. 대화는 독립 스크롤 영역에서 앞부분까지 확인할 수 있도록 변경했습니다.
- **내 계정 연결**은 필요할 때만 열어 12시간 위임 토큰을 입력하도록 하였습니다. 공개 매물 조회에는 인증이 필요하지 않습니다.
- 일반 화면에서 기술적 진단·최근 작업 위젯·원시 모델 상태·대화 다운로드 등은 노출하지 않습니다. 업무 도구(`get_recent_jobs` 포함) 자체는 그대로 동작합니다. 운영 진단은 `SHOW_DEVELOPER_TOOLS=true`로 설정했을 때만 사이드바에 표시됩니다. **공개 Streamlit 앱에서는 이 설정을 활성화하지 마세요.**
- 브라우저에 보이는 상태 표시는 핵심적인 읽기 전용/샌드박스 정보만 남깁니다.

## 설치 및 적용

1. 기존 `my-agent` 폴더를 백업합니다.
2. ZIP 안의 파일을 **기존 폴더에 병합**합니다. 폴더 자체를 삭제하거나 교체하지 마세요.
3. 기존 `.env`, `.venv`, `requirements.txt`, `data/`를 유지합니다. 별도 패키지 설치가 필요하지 않습니다.
4. VS Code에서 `python -m streamlit run app.py`로 실행합니다.
5. Streamlit Cloud는 변경된 파일을 GitHub에 반영하고 앱을 재시작해 확인합니다.

Git Bash 사용 시:

```bash
source .venv/Scripts/activate
python -m streamlit run app.py
```

로컬 설정 예시:

```dotenv
AGENT_MODE=live
MARKETPLACE_API_URL=https://YOUR-PROJECTAGAIN-HOST
MARKETPLACE_AUTH_SCHEME=bearer
MARKETPLACE_INCLUDE_DEMO=true
ENABLE_OPENAI_CHAT=true
OPENAI_API_KEY=your-secret-key
SHOW_DEVELOPER_TOOLS=false
```

실제 OpenAI 키와 위임 토큰은 GitHub에 올리지 마세요. 사용자별 위임 토큰은 공용 Secrets에서 공유하지 않습니다. Live 모드는 **여전히 조회 전용**이며 실제 계약·결제·전송 기능을 실행하지 않습니다.

## 스크롤과 기록에 관해

v0.9 코드에서는 메시지 목록을 `[-80:]`으로 잘라 보관했으며, `include_demo` 옵션을 세션 식별자에 포함해 토글할 때 서로 다른 대화를 표시할 수 있었습니다. v0.10은 해당 두 동작을 수정했습니다.

**이미 v0.9에서 잘려 삭제된 메시지는 자동 복구되지 않습니다.** 또한 Streamlit의 `st.session_state`는 브라우저 연결/서버 재시작 이후의 영속 저장을 보장하지 않습니다. 정식 장기 보관 기능이 필요하면 별도 인증 및 데이터 저장 설계가 필요합니다.

## 실제 배포에서 확인할 사항

1. 첫 접속 시 '시연 매물 포함'이 체크되어 있는지, 해제 후 매물 목록이 달라지는지 확인합니다.
2. 긴 대화에서 **채팅 영역 내부**를 위로 스크롤했을 때 첫 메시지까지 보이는지 확인합니다. 모바일에서도 테스트합니다.
3. 체크박스를 바꿔도 대화가 사라지지 않으며, 이전 매물 순번은 새 목록으로 다시 조회해야 하는지 확인합니다.
4. 사이드바에서 계정 연결을 제외한 진단 UI가 사라졌는지 확인합니다.
5. 매물 검색·맞춤 추천·승인 차단 및 사용자별 읽기 권한이 이전처럼 동작하는지 확인합니다.

내부 회귀 테스트 실행:

```bash
python -m scripts.run_tests
```

**검증 범위:** Python 3.13 환경의 내부 기능/모의 HTTP 테스트. Streamlit 1.67.0 실제 렌더링, Windows Python 3.12, 실 Replit 및 OpenAI 통신은 이번 환경에서 미검증입니다.
