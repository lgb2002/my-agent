# v0.16 · AI suitability + authenticated quotas

- 기존 v0.13~v0.15 AI 근거 기반 정성 점수 보정을 유지하면서 후보별 기본점수, AI 가감, 인용 근거를 결과 화면에서 구분.
- ProjectAgain `/auth/me`로 검증한 개별 위임 토큰 또는 Streamlit OIDC 사용자 신원으로만 유료 AI 허용.
- 서버 측 공용 PostgreSQL에서 원자적 사용자/전체 요청 횟수 및 USD 추정 비용 예약·정산.
- 인증·저장소 부재, 일일/분당 한도 초과, 미등록 모델 단가에서는 유료 API 호출 실패-차단.
- LangChain 일반 호출·구조화 출력·도구 호출·정성 평가·보조 설명의 실제 OpenAI 요청을 단일 계량 계층에서 집계.
- 미인증 사용자는 기존 명령형 공개 조회를 계속 사용 가능. 사용자 승인 및 Live 거래 변경 방침 변경 없음.
- 배포 OIDC/OAuth 설정과 PostgreSQL 준비는 운영자가 직접 해야 하며 본 실행 환경에서 실제 유료 호출은 미검증.
