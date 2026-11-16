# v0.6 운영 및 확인 절차

1. `my-agent/`의 기존 `.env`, `.venv`, `requirements.txt`, `data/`는 유지하고 ZIP의 파일·폴더만 병합합니다.
2. `.env`: `AGENT_MODE=mock`에서 기본 기능부터 확인합니다. `ENABLE_OPENAI_CHAT=true`와 유효한 API 키가 있을 때만 LangChain 도구 선택이 활성화됩니다.
3. `python -m streamlit run app.py` 하나로 실행합니다.
4. 채팅에서 `매물 목록 보여줘` → `첫 번째 매물 실사해줘` → `첫 번째 매물에 50만원 제안 준비해줘` 순서로 사용합니다.
5. Mock 제안은 초안 생성 → 내용 승인 → 전송을 각각 별도 버튼으로 수행합니다. 실제 자금 이전은 하지 않습니다.
6. 사용자별 플랫폼 연동을 검증할 때는 `AGENT_MODE=live`, `MARKETPLACE_API_URL=https://호스트`로 설정하고, 공개 조회부터 확인한 후 사용자 본인의 위임 토큰을 사이드바에 연결합니다. 토큰은 공용 Secrets에 저장하지 않습니다.
7. `python -m scripts.run_tests`로 로컬 기능과 모의 HTTP 계약 테스트를 실행합니다.

**제한:** v0.6 live 모드는 원격 GET만 허용합니다. 승인 파일 목록, 구매자 실사 보고서, 거래 변경·승인, 영구 데이터베이스, 사용량 제한 등은 아직 연동 전입니다.
