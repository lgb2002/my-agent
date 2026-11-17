# ProjectAgain Agent v0.16 업데이트

v0.15 프로젝트를 기반으로 만든 **전체 교체용 ZIP**. 실행 방식은 기존과 같이 `python -m streamlit run app.py` 하나다.

## 중요: 이전 배포와 달라지는 점

- OpenAI 키만 등록한 **공개 무인증 AI 대화는 더 이상 허용하지 않는다.** 공개 매물 조회는 계속 가능하다.
- 유료 AI를 사용하려면 자기 ProjectAgain 위임 토큰(앱 사이드바 입력, 플랫폼 `/auth/me` 인증) 또는 Streamlit OIDC 로그인으로 신원을 확인한다.
- **Streamlit Cloud 공개 배포라면 PostgreSQL 연결 설정이 필수**다. 상태 기억용 `AGENT_STATE_DATABASE_URL`을 재사용하거나 별도 `AI_USAGE_DATABASE_URL`을 사용한다. 이 DB가 없으면 유료 AI 호출은 의도적으로 차단된다.
- `python -m pip install "psycopg[binary]"`가 필요하다. OIDC 로그인 방식을 선택할 경우에만 `python -m pip install "streamlit[auth]"`도 필요하다.
- 기본 4회/분, 30회/사용자/UTC일, 300회/전체/UTC일; 추정비용 사용자 $0.20/일, 전체 $2.00/일. Secrets에서 조절할 수 있다.
- v0.15의 OpenAI 정성 평가 로직은 기존에 실구현되어 있었다. 이번 버전은 **근거와 최종 점수 변화를 화면에 더 명확히 표현**하고 유료 평가 호출도 동일한 사용량 보호에 포함한다.

설정 예시와 인증/데이터베이스 준비 방법, 정확한 한계: [`docs/AI_FIT_AND_PUBLIC_QUOTAS_V016.md`](docs/AI_FIT_AND_PUBLIC_QUOTAS_V016.md).

## 적용

1. 기존 `.env`, `.venv`, `requirements.txt`, `data/` 백업/보존 후 새 ZIP의 파일만 병합한다.
2. Streamlit Cloud Secrets에 AI quota 설정 및 PostgreSQL URL 등록. `AI_LOCAL_SQLITE=true`는 공개 배포에서 금지.
3. `requirements.txt`에 `psycopg[binary]` 추가하고 GitHub 반영. OIDC 설정을 사용할 때만 `streamlit[auth]`를 추가한다.
4. 배포 후 본인 토큰/OIDC로 로그인하여 AI 호출 및 일일 카운터 증가를 확인한다.
5. 무인증 매물 조회, 인증 없는 AI 차단, 한도 초과, 다른 사용자 카운터 분리 검증.

### 인증 옵션을 구성하지 않았다면

기존 플랫폼을 연결한 사용자별 토큰이 없고 OIDC도 설정하지 않았다면 **유료 AI는 동작하지 않는다**. 이것은 공개 키 비용 보호를 위한 의도된 변경이다. 개발 중 로컬 Mock 테스트에는 `AI_LOCAL_SQLITE=true`를 사용할 수 있지만 신원 없이 OpenAI 호출은 여전히 차단된다.

## 범위와 유의사항

현재 실행 환경에서는 모의 OpenAI/로컬 SQLite 테스트만 수행했다. 실제 Streamlit 1.67 UI, 외부 PostgreSQL, 실제 OAuth/OIDC, 실제 유료 OpenAI 호출은 미검증이다. 모델 단가와 비용 제한은 안전을 위한 **추정치**이며 제공자 청구서에 대한 정확한 한도를 보장하지 않는다. OpenAI 계정/프로젝트 측 별도 사용량 정책도 설정해야 한다.
