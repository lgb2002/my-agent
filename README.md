# ProjectAgain Agent v0.17 — ProjectAgain API 전용

**ProjectAgain 플랫폼을 위한 Streamlit AI 에이전트**입니다. 프로젝트 검색·추천·공개 정보 점검·협상 초안 준비를 지원하며, 실제 매물 데이터는 **플랫폼 HTTPS API 한 곳에서만** 읽습니다.

## 무엇이 달라졌나

- 내부 **Mock 모드 및 로컬 가상 거래 서비스 제거**. 시연용 사용자/거래 상태와 샘플 매물 JSON을 실행에 사용하지 않습니다.
- 기존 `AGENT_MODE`는 **설정할 필요가 없으며 입력되어 있어도 무시**합니다. 실제 플랫폼 URL을 설정해야 앱의 조회 기능이 동작합니다.
- **`시연 매물 포함`은 유지**합니다. 이것은 로컬 Mock 모드가 아니라 **실제 ProjectAgain 플랫폼에 등록된 시연 매물**을 API 응답에 포함시키는 필터(`include_demo=true`)입니다. 기본 체크 상태이며 사용자가 해제할 수 있습니다.
- 이전 13개 도구 중 로컬 가상 거래 전용 4개(`prepare_counter_offer`, `prepare_accept_offer`, `prepare_publish_report`, `prepare_handover_check`)를 제거해 **실제 플랫폼 데이터에 근거한 9개 도구**를 제공해요. 사용자의 구매 제안 초안은 별도 확인·권한 요건을 충족한 경우에만 준비/제출합니다.
- **자동 테스트용 가짜 API 응답은 계속 사용**합니다. 이는 배포된 사용자가 고르는 Mock 모드가 아니라, 테스트가 실제 데이터를 변경하지 않도록 하는 독립적인 검사 방식입니다.

## 실행

프로젝트의 기존 `.env`, `.venv`, `requirements.txt`, `data/`와 개인 설정 파일은 보존하세요. ZIP의 내용을 `app.py`가 있는 `my-agent` 폴더에 병합하여 사용합니다. 단, 구버전에서 제거된 다음 파일은 더 이상 필요하지 않습니다.

- `services/demo_marketplace.py` — 제거 대상
- `fixtures/demo_contract.json` — 제거 대상
- `data/mock_marketplace.sqlite3` — 구버전 로컬 테스트 데이터. **사용자 데이터를 확인하고 백업한 후에만** 삭제하세요. 코드는 사용하지 않습니다.

로컬 설치 환경에 필요한 패키지가 없다면 다음을 실행합니다.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

프로젝트의 기존 requirements.txt를 자동 교체하지 않습니다. PostgreSQL을 사용한다면 `psycopg[binary]>=3.2,<4`가 포함되어야 합니다. 일반 실행에 별도의 FastAPI 서버는 필요 없습니다.

## 설정: `.env` 또는 Streamlit Cloud Secrets

```dotenv
# 실제 ProjectAgain 플랫폼 호스트. API 접미사 /api/v1은 제외
MARKETPLACE_API_URL=https://YOUR-REAL-PROJECTAGAIN-HOST
MARKETPLACE_AUTH_SCHEME=bearer
# 플랫폼이 제공하는 데모 매물을 포함하는 API 필터
MARKETPLACE_INCLUDE_DEMO=true

# 자연어 이해 및 AI 맞춤 추천
ENABLE_OPENAI_CHAT=true
OPENAI_API_KEY=YOUR_PRIVATE_KEY
OPENAI_MODEL=gpt-4.1-mini

# 현재 준비 중인 플랫폼 액션 초안 전송은 기본 비활성
ENABLE_LIVE_DRAFTS=false

# 공개 유료 AI 사용량·예산 통제: 서버 공유 PostgreSQL 필요
AI_USAGE_DATABASE_URL=postgresql://...
# 개인 동의 기반 작업/선호 영속 저장(동일 DB 재사용 가능)
AGENT_STATE_DATABASE_URL=postgresql://...
SHOW_DEVELOPER_TOOLS=false
```

- `MARKETPLACE_API_URL`은 실제 배포된 HTTPS 플랫폼 주소를 넣습니다. 공개 매물은 위임 토큰 없이 조회할 수 있습니다.
- 사용자 전용 매물·제안·구매 프로필 조회는 각 사용자의 **본인 위임 토큰**과 해당 권한이 있어야 합니다. **공용 플랫폼 사용자 토큰을 Secrets에 두지 마세요.**
- 공개 유료 AI는 **검증된 방문자 신원 + 공유 PostgreSQL의 호출량 제한**을 모두 통과해야 작동합니다. 둘 중 하나라도 없으면 유료 AI 요청을 차단합니다. Streamlit OIDC를 선택적으로 설정할 수도 있습니다.
- `AGENT_STATE_DATABASE_URL`은 사용자가 저장을 선택한 작업 기록에 사용합니다. Streamlit Cloud의 로컬 DB는 재배포 후 보존되지 않습니다.
- 모델 키와 DB 연결 URL은 절대 GitHub에 커밋하지 않습니다.
- `ENABLE_LIVE_DRAFTS`는 플랫폼 초안 계약과 멱등성 실검증 전까지 `false`를 유지해야 합니다. `true`여도 **사람이 별도로 확인한 초안 생성**만 허용하며 에이전트가 승인·실행·정산하지 않습니다.

## 제공 도구 (9개)

| 도구 | 역할 |
|---|---|
| `search_listings` | 플랫폼 공개 매물 검색(시연 매물 필터 포함) |
| `recommend_listings` | 구매 조건 기반 후보 추천·정성적 AI 적합성 보조 평가 |
| `inspect_listing` | 공개 메타데이터 근거 점검 |
| `inspect_attached_zip` | 인증된 판매자의 업로드 ZIP **로컬 정적 검사**(실행/플랫폼 업로드 없음) |
| `list_offers` | 인증된 거래 제안 내역 조회 |
| `prepare_offer` | 구매 제안 초안 준비; 제출은 별도 확인 및 권한 필요 |
| `get_handover` | 인수인계 상태 조회 |
| `get_buyer_preferences` | 계정별 구매 선호 조회 |
| `get_recent_jobs` | 본인 작업 내역 조회 |

## 테스트 및 배포 점검

```bash
python -m scripts.run_tests
```

자동 테스트는 외부 플랫폼을 변경하지 않는 가짜 HTTP 응답을 사용하며, 이 테스트의 성공이 실제 Replit API·OpenAI 호출·Supabase 연결·Streamlit Cloud UI 성공을 의미하지 않습니다. 배포 후에는 순서대로 **앱 시작 → 공개 매물 조회 → 시연 매물 포함 토글 → 사용자 토큰 인증 → AI 사용량 조회**를 확인하세요.

전체 변경 내역: `CHANGELOG.md` · 현재 설치 지침: `docs/RUNBOOK.md` · 구조: `docs/API_ONLY_V017.md` · 디자인 원칙: `DESIGN.md`.

과거 버전별 설계 문서는 당시 기능 설명을 담은 **기록 자료**이며, 현재 배포 지침을 대신하지 않습니다.
