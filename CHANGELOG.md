# 변경 내역

## v0.4 — Chat-first Tool Agent (2026-11-12)

- UI: 화면별 다중 메뉴를 없애고 **채팅을 메인**으로 재설계. 전용 CSS·Streamlit 테마, 시작 질문, 사이드바 상태/업로드/최근 작업, 도구 호출 이력/JSON 확인을 추가.
- AI: `ChatOpenAI.bind_tools()`로 도구 정의를 모델에 제공하고, 모델 응답의 실제 tool call을 allowlist 실행기로 라우팅. 최대 4턴/6호출로 제한. 실패 시 무한 재시도하지 않음.
- 오프라인: API 키 없이 제한된 한국어 명령형 도구 시연 가능. LLM 기능으로 오인되지 않도록 UI에서 명시.
- 도구: 검색, 조건 추천, 매물 메타 실사, 판매자 ZIP 정적 검사, 제안 조회, 제안 준비, 역제안 준비, 수락 검토, 검사 보고서 제출 준비, 인계 점검 준비/조회, 작업 이력 조회.
- 승인 정책: 모델은 읽기/검사 및 **제안 준비**까지만. 사용자가 버튼으로 초안 생성/승인/전송하는 3단계 흐름, 원본 해시 및 정책 검증 유지.
- 안전: 모델에는 API 키나 업로드 ZIP 원본 전달 금지, 비밀 키처럼 보이는 채팅 입력 차단, 다른 사용자 초안 조회 불가, LIVE 쓰기 전부 차단.
- 기존 FastAPI/Mock 플랫폼 서버 없음. 단일 `python -m streamlit run app.py` 유지.
- 사용자의 최근 pip freeze 결과를 덮어쓰지 않도록 `requirements.txt` 대신 참고용 `requirements.reference.txt` 제공. 별도 `requirements-agent.txt` 제거.
- 실 UI/실 모델 연결은 로컬 Windows 환경에서 추가 검증 필요.
