# ProjectAgain Agent v0.19.2 — 사이드바 디자인 전용 개선

## 범위

- 소스: `app.py`의 사이드바 **표시 및 메뉴 위젯만** 변경, `assets/style.css`의 사이드바 대상 스타일 추가.
- `새 대화`는 아이콘+텍스트 36px/44px의 경계선 없는 메뉴 행, 기존 `_request_new_conversation` 콜백 유지.
- `대화 검색` 클릭 시에만 실제 `st.text_input` 표시. 검색 기능은 기존 `search_conversations`와 계정별 `visible_conversations` 사용; 입력창을 숨길 경우 전체 목록 표시.
- 날짜 그룹(`오늘/지난 7일/이전`)과 목록 간격 정돈, 선택 행에만 배경 강조. 기존 `⋯` 삭제 확인 그대로.
- 하단의 큰 테두리 버튼 대신 `내 계정` 팝오버(아이콘 포함)와 작은 항목: 다른 계정으로 로그인/설정/ProjectAgain 웹사이트/로그아웃. 비로그인 계정은 회원가입 링크.
- 기존 Streamlit 네이티브 키보드 초점과 버튼 의미, 거래 승인·AI 도구·DB 기능·인증 정책 보존.

## 플랫폼 인증과 범위 구분

- 한 번의 로그인+권한 동의를 요구하는 사양은 [`PLATFORM_UNIFIED_LOGIN_HANDOFF_V0192.md`](PLATFORM_UNIFIED_LOGIN_HANDOFF_V0192.md)에 따로 작성.
- v0.19.2 코드에서는 **OIDC `st.login()`과 Broker 연결 단계가 여전히 별개임**. 플랫폼/Agent 합의 및 구현 전까지 새로운 단일 로그인 동작으로 안내하지 않음.

## 검증

- `python -m unittest discover -s tests -q`: 304개 테스트 통과, 실패·오류 0 (로컬 Python 환경).
- `python docs/verify_sidebar_static_v0192.py`: 390/768/1280px 정적 Chromium fixture에서 가로 넘침 0, 하단 계정 영역 분리, 버튼 높이 목표 확인.
- 샘플 이미지는 `sidebar_static_*_v0192.png`; **실제 Streamlit HTML/스타일/클라우드 인증 UI 검증이 아님**.
- 배포 후 확인할 사항: 검색 열기/닫기, 새로운 대화, 대화 선택 및 삭제, 계정 전환·설정/로그아웃, 모바일 사이드바 닫기/스크롤.

## 배포

GitHub의 `my-agent` 원본 v0.19.1 파일 전체를 보존한 v0.19.2 ZIP으로 업데이트. 기존 `data/`, `.env`, `.venv`, Streamlit Secrets, Supabase DB는 덮어쓰지 말 것. 신규 패키지·Secrets·스키마·Replit 배포 변경 없음.
