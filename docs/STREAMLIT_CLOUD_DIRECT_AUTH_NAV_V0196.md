# ProjectAgain Agent v0.19.6 — Streamlit Cloud 통합 인증 이동 경로

## 실제로 확인된 증상

- `projectagain.streamlit.app/pa-agent/auth/start` 새 탭에서 흰 로딩 스피너가 계속 표시됨.
- Chrome Network/Document에서 `start(200)` → `frame(304)` → `start(303)` → `authorize(303)` → `projectagain.kr/login(200)` 기록이 확인됨.
- **최상위 브라우저 주소창은 여전히** Streamlit `/pa-agent/auth/start`에 남아 있었음. 플랫폼에서 HTTP 200을 응답한 것만으로 최상위 브라우저가 이동한 것은 아님.

## 최소 변경

Streamlit Community Cloud의 바깥 앱 페이지와 내부 앱 서버 라우팅을 구분한다. `st.App`는 계속 `app.py`로 구동하고 ASGI 라우트 `/pa-agent/auth/start`는 그대로 유지한다.

- **v0.19.5** 시작 링크: `https://projectagain.streamlit.app/pa-agent/auth/start` (바깥 페이지 경유)
- **v0.19.6** 시작 링크: `https://projectagain.streamlit.app/~/+/pa-agent/auth/start` (앱 서버 직접 진입)
- 로그아웃/계정 전환은 동일하게 `https://projectagain.streamlit.app/~/+/pa-agent/auth/logout`을 사용.

`/~/+/`는 Streamlit Community Cloud의 전달 접두 경로이므로 해당 경로를 거치더라도 내부 `st.App`에서 등록한 실제 ASGI 라우트 이름은 바꾸지 않는다. 이 경로는 호스팅 구현에 의존하므로 추후 Cloud 변경에 민감할 수 있다.

**보안 유지**: 로그인 서버는 서버 전용 Broker Basic 인증으로 intent 발급, Secure/HttpOnly/SameSite=Lax 브라우저 쿠키, 서버측 암호화 pending state, 1회용 티켓, 서명·nonce·state/proof 검증 유지. `projectagain.kr`에서 반환하는 URL은 기존 `https://projectagain.streamlit.app/` 그대로. 과거의 `st.login()` 레거시도 그대로 이용 가능.

## 운영 적용

1. 전체 프로젝트 ZIP을 기존 GitHub 저장소에 병합 후 커밋·푸시.
2. Streamlit Cloud는 **앱 삭제 없이 `app.py` 유지**, 현재 Secrets, Replit v0.37 Production 값과 Supabase 주소 변경 없음.
3. `AGENT_UNIFIED_LOGIN_ENABLED=true`로 로그인 시작 버튼 테스트. Chrome `F12 → Network → Doc`에서 `start` 첫 요청이 `303`이어야 정상 진입 신호임.
4. **주소창이** `projectagain.kr`로 바뀌어 정상 로그인·권한 동의가 표시되는지, 돌아왔을 때 Streamlit의 사용자·Broker 연결이 확립되는지 확인.
5. 같은 계정 새로고침, 두 브라우저 다른 계정 교차 차단, Access Token 갱신, 로그아웃·전환·기존 대화 복원을 확인.

## 문제 발생 시

- `start`가 여전히 200 로딩 페이지면 Community Cloud가 직접 경로를 제공하지 않는 환경일 가능성이 있으므로 새 코드를 무리하게 우회하지 말 것. 서버 진입 경로를 다시 확인하고 복귀 시 쿠키 결속을 검증해야 함.
- `start`가 404/403이면 프록시 또는 origin 검사가 거부된 것. 플랫폼 Secrets나 DB 키를 임의 변경하지 말 것.
- `start`가 303이고 플랫폼 로그인으로 이동했으나 복귀 후 인증 실패면 브라우저 쿠키/콜백 결속을 별도로 진단.
- 안정적인 서비스가 먼저라면 Streamlit Secrets **최상위에** `AGENT_UNIFIED_LOGIN_ENABLED=false`를 넣고 앱을 재부팅해 기존 2단계 OIDC/Broker 방식으로 사용.

**검증 한계**: 신규 URL 및 원래 ASGI 라우트 테스트는 로컬에서 수행했지만 실제 Streamlit Community Cloud·v0.37 운영 API·브라우저 쿠키·임시 상태 연결은 배포 후 E2E가 필요함.
