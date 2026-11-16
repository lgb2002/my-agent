# v0.8 — ProjectAgain Live 연결 진단

- 앱 시작 시 Streamlit Cloud 최상위 TOML Secrets를 `core.config`가 읽기 전에 안전하게 반영하는 `core/runtime_secrets.py` 추가. 키 문자열 출력 없음.
- API 공개 조회를 시연 포함/제외로 별도 검사하고, 사용자 위임 인증을 `/api/v1/auth/me`로 구분 검증하는 `core/live_diagnostics.py` 추가.
- 사용자별 인증에 공용 `MARKETPLACE_API_KEY`를 재사용하지 않는 기존 정책 유지.
- `include_demo` 명시적 API 인자가 세션 기본값에 덮이지 않도록 수정.
- 매물 0건의 경우 시연 필터 상태에 따른 메시지 개선. 네트워크/JSON/HTTP 오류는 0건으로 처리하지 않음.
- OpenAI 비활성 이유(키 없음 vs 키 감지되지만 활성화 플래그 false)를 표시. 비용을 유발하는 자동 테스트는 실행하지 않음.
- 기존 12개 도구와 DEMO 승인 흐름, Live GET-only 차단 유지.
- 실제 Replit URL과 Cloud Secrets에 접근할 수 없으므로 실운영 통신은 미검증.
