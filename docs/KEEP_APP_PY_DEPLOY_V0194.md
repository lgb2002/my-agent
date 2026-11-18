# v0.19.4 — Streamlit Main file path 변경 없이 통합 로그인 시작하기

**중요:** 기존 `projectagain.streamlit.app` 앱을 삭제하지 마세요. `Main file path`는 **`app.py` 그대로** 유지합니다.

## 내부 파일 구조

```
app.py           # Streamlit 서버 진입점: st.App('chat_ui.py', ...)
chat_ui.py       # 기존 v0.19.3 app.py에 있었던 대화 UI 전체
unified_entry.py # 신규 파일 경로로 설정한 환경의 호환 진입점
core/unified_web.py
core/unified_login.py
```

`app.py`는 채팅 코드를 직접 실행하지 않습니다. Streamlit이 `st.App`을 발견해서 ASGI 서버를 생성하고 그 서버가 `chat_ui.py`를 렌더링합니다. 기존 OIDC/브로커 설정은 그대로 둡니다.

## 운영 절차

1. ZIP의 전체 파일을 기존 GitHub 저장소에 반영하고 push.
2. Streamlit Cloud `Settings`의 현재 Main file path가 `app.py`이면 **절대 바꾸지 않음**.
3. Secrets에 `AGENT_UNIFIED_LOGIN_ENABLED = false`가 들어 있는지 확인 후 Reboot; 기존 로그인 확인.
4. 플랫폼 운영 v0.37 및 `0014_unified_login` 적용, `OAUTH_BROKER_UNIFIED_LOGIN_ENABLED=true` 확인 후 Streamlit 쪽도 `AGENT_UNIFIED_LOGIN_ENABLED=true`로 전환.
5. 실제 로그인 시작→플랫폼 동의→Agent 복귀, refresh, 계정 전환과 다중 브라우저 세션 격리 확인.

**추가 Secret/DB migration/새 앱 생성은 Agent 쪽에 필요 없습니다.** 기존 주소와 DB 비밀번호, 암호화 키를 재생성하지 않습니다.

## 문제가 생긴 경우

- 기능만 실패: `AGENT_UNIFIED_LOGIN_ENABLED=false`로 재부팅해 OIDC/Broker 레거시 사용.
- 서버가 시작하지 않음: GitHub에서 배포 코드를 v0.19.3으로 되돌려 `app.py` 전통 실행으로 복구. 앱 삭제·재등록 불필요.
- `Streamlit st.App`는 공식적으로 실험적 기능입니다. Cloud 프록시 동작이 확인되지 않은 상태에서 자동 활성화하지 않으며, E2E 전에는 본격 운영 완료로 판단하지 않습니다.
