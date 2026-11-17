# ProjectAgain Agent v0.17 운영 절차 — API 전용

## 배포 전 준비

1. `MARKETPLACE_API_URL`에 **실제 플랫폼 HTTPS 호스트**를 입력한다. `/api/v1`은 포함하지 않는다.
2. `MARKETPLACE_INCLUDE_DEMO=true`를 유지하면 실제 플랫폼의 시연 매물을 포함한다. UI에서 해제할 수 있다.
3. `ENABLE_OPENAI_CHAT=true`, 개별 `OPENAI_API_KEY`, 공유 PostgreSQL `AI_USAGE_DATABASE_URL`을 설정한다. 유료 AI에는 검증된 사용자 신원이 필요하다.
4. 선택적 장기 기억을 사용한다면 `AGENT_STATE_DATABASE_URL`을 설정한다. 두 URL은 같은 PostgreSQL을 사용해도 된다.
5. 기존 `requirements.txt`에 `psycopg[binary]>=3.2,<4`가 포함되었는지 확인하고 GitHub에 반영한다. 비밀값은 GitHub에 올리지 않는다.
6. `ENABLE_LIVE_DRAFTS=false`를 기본값으로 유지한다. 실제 플랫폼 쓰기 초안 계약이 실검증된 뒤에만 별도 승인 절차로 활성화한다.

## 기존 프로젝트에서 업데이트

1. 새 전체 프로젝트 ZIP을 백업된 `my-agent/` 폴더에 병합한다. 개인 `.env`, `.venv`, `requirements.txt`, `data/`는 보존한다.
2. 제거된 `services/demo_marketplace.py`, `fixtures/demo_contract.json`을 프로젝트에서도 정리한다. 기존 `data/mock_marketplace.sqlite3`는 데이터 성격을 확인한 후 백업하고 정리한다. 이 DB는 더 이상 참조하지 않는다.
3. 이전 Secrets의 `AGENT_MODE` 값은 필요 없다. 있더라도 무시되므로 제거를 권장한다.
4. `python -m scripts.run_tests`로 로컬 코드 검사를 하고 GitHub에 커밋·푸시한다.
5. Streamlit Cloud에서 다시 배포한 후 실제 플랫폼에서 공개 매물이 보이는지 확인한다.

## 앱 확인

- 첫 화면에서 매물 검색을 실행한다. 로그에 시연 JSON 읽기 예외가 없어야 한다.
- `시연 매물 포함`을 켜고 끄며 API 결과가 달라지는지 확인한다. 등록된 시연 매물이 없다면 결과가 같을 수 있다.
- 사용자 위임 토큰 연결 이후 계정별 조회가 동작하는지 확인한다.
- AI 대화가 인증 및 공용 DB 사용량 통제를 통과하는지 확인한다.
- 매물 ZIP 검사는 판매자 본인 인증이 필요하며, 코드 실행이나 플랫폼 업로드는 하지 않는다.
- 실제 제안 승인·실행은 에이전트에서 허용하지 않는다.

## 장애 분류

- **부팅 단계 `FileNotFoundError` (demo_contract.json):** 구버전 실행 코드가 남았거나 GitHub에 정리 내용이 반영되지 않았음. v0.17 실행 코드를 배포했는지 확인한다.
- **매물 API 오류:** 실제 플랫폼 주소·HTTPS·매물 엔드포인트 및 Replit 응답 확인.
- **AI 요청 차단:** 인증된 사용자 신원, OpenAI 키, PostgreSQL, 호출량 한도 검사.
- **기억/사용량 저장 오류:** PostgreSQL 연결 문자열, `psycopg` 설치, DB 권한 확인.

## 검증 범위

자동 테스트는 가짜 응답에 근거한 계약 테스트다. 실제 서버를 대상으로 한 전체 통합 테스트, Streamlit 화면 검증, 유료 OpenAI 호출 및 외부 DB 장애 복구는 별도 운영 검증이 필요하다.
