# ProjectAgain v0.4 ↔ Agent v0.6 연동 현황

기준: 플랫폼 측 `ProjectAgain v0.4 ↔ Digital Asset Agent v0.5 연동 검토 및 플랫폼 측 회신` (2026-11-12). 플랫폼의 실제 소스/`contracts/implemented-openapi-v04.json`은 이 ZIP에 포함되지 않았습니다. 이 문서는 플랫폼 측 검토 결과와 Agent v0.6 수정 내용을 구분합니다.

| 영역 | v0.6에서 반영한 내용 | 남은 확인 |
|---|---|---|
| HTTP URL | `MARKETPLACE_API_URL`은 호스트 원점으로 정규화하고 `/api/v1` 자동 추가 | 실제 공개 HTTPS 도메인 확인 |
| 인증 | 사용자별 **불투명 Bearer 위임 토큰**. 공개 매물은 무인증. 공유 서버 토큰 불사용 | 플랫폼 계정에서 실제 토큰 발급·만료·철회 확인 |
| 조회 | `GET /api/v1/listings` (`limit`, 숫자 오프셋 `cursor`, 선택적 `include_demo`) / `{uuid}` 상세 호출 | 실제 응답 필드·상태값·필터 서버 지원 확인 |
| 매물 식별 | 대화 중 순번을 정확한 `listing_id`에 고정하고 상세 API로 재확인 | 실제 신규 등록 및 페이지 변경 중 수동 검증 |
| 추천 | 최대 10페이지, 100건씩 조회 후 정적 규칙 평가; `None` 필드 일부 방어 | 서버 대량 결과, 성능/비용, 실제 가격·상태 표준 |
| 구매 조건 | `GET /api/v1/buyer-preferences/me` 도구 추가 | `buyer_profile:read` 발급 및 401/403 케이스 |
| 제안 조회 | `GET /api/v1/offers`, `/{uuid}`. `proposed_by` 누락 시 안전 처리 | `offer:read` 권한과 당사자 필터 |
| 변경 처리 | `AGENT_MODE=live`에서 원격 POST/PUT/PATCH/DELETE 차단 | 웹 승인+CSRF 및 멱등성 계약 완료 후 별도 확장 |
| ZIP 실사 | 로컬 DEMO 판매자 직접 업로드만 수행 | 승인된 자산 목록 조회 API, 4 MB vs 10 MB 정책 |
| 운영 | Streamlit 단일 프로세스, 토큰/대화 세션 구분 | 공개 서비스용 정식 로그인·속도/비용 제한·영구 저장소 |

## 플랫폼 팀에 남기는 항목

1. `frontend/src/Operations.tsx`의 `GET /my/listings` 응답은 최상위 배열이라는 보고가 있으므로 배열/`items` 불일치 수정
2. 판매자 승인 파일만 나열하는 `GET /api/v1/agent/listings/{listing_id}/inspection-assets` 등 API 제공
3. 구매자 비공개 실사 보고서 작성·공개 범위 정책 정리
4. 에이전트 작업 승인/실행의 `Idempotency-Key` 및 브라우저 CSRF 승인 경계 유지
5. `contracts/implemented-openapi-v04.json`을 최신 구현 스냅샷으로 제공하고 불투명 Bearer 위임 토큰 스키마 문서화
6. 실제 Replit 도메인, `/health`, `/openapi.json`, PostgreSQL·Storage·프론트 배포 상태 확인

## 수용 절차

- A: `curl https://HOST/health` 및 최신 OpenAPI 확인
- B: 토큰 없이 `GET /api/v1/listings?limit=15&cursor=0`, 시연 토글에 따른 `include_demo=true`/`false` 검증
- C: 검색 결과의 1번 UUID 고정 → 새 매물 추가 → 정확한 UUID 상세 재조회
- D: 사용자별 위임 토큰으로 `GET /api/v1/auth/me`, `GET /api/v1/agent/context`, `GET /api/v1/buyer-preferences/me` 실통신 및 401·403 비교
- E: 두 사용자 간 결과/토큰 격리, 만료·철회·권한 축소 확인
- F: live에서 변경 API 호출이 로컬에서 차단되는지 확인

**현재 판정:** 구조적으로 조회 연동을 검증할 준비가 되었음. **실제 플랫폼과의 통신 성공, 거래 변경 연동 완료를 의미하지 않음.**
