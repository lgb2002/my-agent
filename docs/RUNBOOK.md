# v0.5 실행 및 기본 점검

1. 기존 `.venv`, `.env`, `requirements.txt`를 유지하고 프로젝트 파일을 복사합니다. ZIP에는 참고용 `requirements.reference.txt`만 포함합니다.
2. `.env`: `AGENT_MODE=mock`, `OPENAI_API_KEY=<본인 키>`, `ENABLE_OPENAI_CHAT=true` (키 없이도 제한형 도구 모드 가능).
3. `python -m streamlit run app.py` 실행 (다른 서버 없음).
4. 챗: “매물 목록 보여줘” → “첫 번째 매물 실사해줘” → “첫 번째 매물에 50만원 제안 준비해줘”.
5. 구매 제안은 초안 생성 → 승인 → 샌드박스 전송을 각각 사용자 버튼으로만 수행. 판매자 역할로 전환해 “1번 매물 제안 내역 보여줘”로 확인.
6. 판매자가 자신의 ZIP을 정적 검사하려면 사이드바 파일 업로드 후 “첫 번째 매물에 업로드한 ZIP 검사해줘”라고 대화.
7. `python -m unittest discover -s tests -v`로 테스트 실행.

**제한:** 실제 Replit 거래 플랫폼은 별도 API 키 발급/인증 구현이 필요합니다. 실제 결제/계약/거래 변경은 지원하지 않습니다.
