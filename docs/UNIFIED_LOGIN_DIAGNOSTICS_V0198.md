# ProjectAgain Agent v0.19.8 — 통합 로그인 시작 HTTP 500 진단

## 문제

Agent v0.19.7에서 `/~/+/pa-agent/auth/start`가 `Internal server error`를 반환하지만 Streamlit Cloud 앱 로그에 traceback이 나타나지 않음. v0.19.7 핸들러는 `BrokerError`만 HTTP 503으로 변환하고, 예상 밖 오류는 ASGI로 전파되어 본문에 단서 없는 500이 됨. 원인은 아직 확정되지 않음.

## 진단 절차

1. 기존 Streamlit Cloud `Main file path=app.py`를 유지하고, v0.19.8 전체 파일을 GitHub에 반영 후 앱 재시작. Secrets는 변경하지 않음.
2. 브라우저 새 탭에서 `https://projectagain.streamlit.app/~/+/pa-agent/auth/health`를 확인. 정상 응답은 `PA-AUTH-ROUTE-OK` (200).
3. 기존 Agent 화면에서 `ProjectAgain으로 시작하기`를 눌러 결과 확인.
4. 만약 `통합 로그인 시작 오류` + `PA-START-...`가 나오면 **코드 부분만** 공유. 실제 Token/쿠키/redirect URI 쿼리스트링/Secret은 공유하지 말 것.
5. health 라우트조차 `Internal server error`이고 오류 코드가 없으면 ASGI 핸들러 진입 전 Cloud 프록시/앱 기동 문제 가능성: 이 패치로 이유를 판별할 수 없으므로 Streamlit Cloud 상태와 앱 설정 확인 필요.

## 단계별 진단 코드

- `PA-START-CONFIG-*`: `st.secrets` 최상위 설정 접근 또는 플래그 확인
- `PA-START-SERVICES-*`: 환경설정 및 암호화/DB/클라이언트 초기화
- `PA-START-CAPABILITIES-*`: 플랫폼 `/broker/unified/capabilities` 응답 또는 복귀 URL 일치
- `PA-START-DATABASE-*`: DB pending 브라우저 세션 저장
- `PA-START-INTENT-*`: 서버 간 통합 로그인 intent 생성
- `PA-START-OTHER-*`: 그 밖의 시작 단계 오류
- `*-unexpected`: 예상하지 못한 Python 예외, 내용은 노출하지 않음

`unified_callback_not_ready`, `storage_unavailable` 등 고정 오류는 비밀 정보가 아님. 진단 코드가 떴다면 프록시가 아닌 Python 핸들러까지 요청이 도달했음을 의미함.

## 안전 보장

기존 데이터와 Secrets를 수정하지 않음. 에러 코드 문자열에 사용자/토큰/세션/접속 문자열이 들어갈 수 없도록 고정 어휘만 사용함. 일회용 티켓은 URL 전체를 공유하지 않음. 기능 플래그를 `false`로 설정하면 기존 OIDC + Broker 2단계 방식 사용 가능.
