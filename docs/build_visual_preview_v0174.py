"""Static CSS viewport fixture; illustrative data only, not a Streamlit runtime screenshot."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
css = (ROOT/'assets/style.css').read_text(encoding='utf-8')
html = '''<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProjectAgain · CSS viewport verification (static)</title>
<style>'''+css+'''</style>
<style>
*{box-sizing:border-box} body{margin:0;background:var(--bg)}
.fixture-shell{display:flex;min-height:100vh}
.fixture-sidebar{width:240px;flex:0 0 240px;border-right:1px solid var(--line);background:#F1F5F0;padding:28px 18px}
.fixture-sidebar .brand{margin-top:0}
.fixture-sidebar section{padding:15px 0;border-top:1px solid var(--line)}
.fixture-sidebar p{color:var(--muted);font-size:.85rem;line-height:1.55}
.fixture-sidebar button{height:44px;border-radius:9px;background:var(--accent);color:#fff;border:0;width:100%;font:inherit;font-size:.9rem;font-weight:700}
.fixture-main{min-width:0;flex:1}
[data-testid="stMainBlockContainer"]{margin:0 auto;padding-inline:28px}
.fixture-head{display:flex;align-items:baseline;gap:12px;justify-content:space-between;margin:17px 0 8px}
.fixture-note{font-size:.85rem;color:var(--muted);line-height:1.5}
.fixture-compare-scroll{max-width:100%;overflow-x:auto}
.fixture-controls{display:flex;gap:10px}
.fixture-controls .stButton{flex:1;min-width:0}
.fixture-controls .stButton button{width:100%;padding:10px}
.fixture-sample-chat{margin:23px auto 0;max-width:850px}
.fixture-sample-chat p{font-size:1rem;line-height:1.7}
.fixture-sample-chat details{border:1px solid var(--line);border-radius:10px;background:#fff;padding:15px}
.fixture-right{text-align:right}
[data-testid="stTable"] table{border-collapse:collapse;width:100%}
[data-testid="stTable"] th,[data-testid="stTable"] td{text-align:left;border-bottom:1px solid var(--line)}
@media(max-width:760px){.fixture-sidebar{display:none}[data-testid="stMainBlockContainer"]{padding-inline:14px}.fixture-controls{flex-direction:column}}
</style></head>
<body><div class="fixture-shell"><aside class="fixture-sidebar" aria-label="정적 예시 사이드바"><div class="brand"><span class="brand-symbol">◈</span>ProjectAgain</div>
<section><div class="sidebar-heading">매물 보기</div><p>☑ 시연 매물 포함</p><p>공개 매물 조회 가능</p></section><section><button>＋ 새 대화</button></section>
<section><p>대화 보관함 ▾</p><p>추천 조건 확인·수정 ▾</p><p>사용 가능한 도구 ▾</p></section></aside>
<main class="fixture-main"><div data-testid="stMainBlockContainer">
<div class="pa-layout-mode pa-layout-mode--wide" aria-hidden="true"></div>
<div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div>
<div class="st-key-primary_workbench_v0173"><div class="workbench-eyebrow">추천 결과</div><h1 class="workbench-title">후보를 비교하고 선택하기</h1>
<p style="margin-bottom:8px;font-size:.98rem;font-weight:700">이 결과에 적용된 조건</p>
<div class="criteria-strip"><span class="criteria-pill">목적 · 운영 수익</span><span class="criteria-pill">예산 · 500,000원 이하</span><span class="criteria-pill">개발 경험 · 중급</span><span class="criteria-pill">위험 허용 · 낮음</span><span class="criteria-pill">기술 · Python</span></div>
<div class="result-section-heading"><span>추천 후보 비교</span><span class="result-section-count">3개 표시 / 조건 부합 3개</span></div>
<p class="fixture-note">플랫폼 공개 매물 기준 · 추천 순위는 상대적 적합성이에요.</p>
<div data-testid="stTable" class="fixture-compare-scroll"><table><thead><tr><th>후보</th><th>가격</th><th>맞는 이유</th><th>확인할 점</th></tr></thead><tbody>
<tr><td>1. 프로젝트 A</td><td>350,000원</td><td>Python 기술과 일치</td><td>운영비 미확인</td></tr>
<tr><td>2. 프로젝트 B</td><td>420,000원</td><td>운영 자료 일부 공개</td><td>권리 범위 확인 필요</td></tr>
<tr><td>3. 프로젝트 C</td><td>280,000원</td><td>구매 예산에 여유 있음</td><td>구동 기록 미확인</td></tr>
</tbody></table></div>
<div class="fixture-head"><strong>1순위 · 프로젝트 A</strong><span class="fixture-note">자료를 기반으로 추가 확인</span></div>
<p class="fixture-note">적합한 이유 · Python 기술 조건과 일치하며 가격이 예산에 부합해요.</p>
<h3 style="font-size:1rem;margin:19px 0 5px">위험 항목별 공개 근거</h3>
<div class="evidence-list" role="list"><div role="listitem" class="evidence-row evidence-row--unknown"><span class="evidence-row__title">월 운영비</span><span class="evidence-tag evidence-tag--unknown">미확인</span><span class="evidence-row__detail">서버 및 유료 API 사용 비용을 확인할 자료가 부족해요.</span></div>
<div role="listitem" class="evidence-row evidence-row--caution"><span class="evidence-row__title">권리 범위</span><span class="evidence-tag evidence-tag--caution">주의</span><span class="evidence-row__detail">소스·디자인·외부 라이브러리 이용 권한을 별도 확인해야 해요.</span></div>
<div role="listitem" class="evidence-row evidence-row--reported"><span class="evidence-row__title">구동 검토</span><span class="evidence-tag evidence-tag--reported">정적 검사 표시</span><span class="evidence-row__detail">공개된 메타데이터의 정적 검사 표기이며 실제 실행 검증과는 달라요.</span></div></div>
</div>
<div class="next-actions-heading">이어 할 수 있는 일</div>
<div class="st-key-workspace_action_row_v0173 fixture-controls"><div class="stButton"><button>1순위 공개 정보 검토</button></div><div class="stButton"><button>후보 차이 설명</button></div><div class="stButton"><button>조건 바꿔 다시 추천</button></div></div>
<div class="fixture-sample-chat"><div class="conversation-history-separator"></div><p class="fixture-note">이전 대화 및 도구 실행 기록 · 7개 메시지</p><details><summary>이전 대화 전체 보기</summary><p>도구 결과는 확인 당시 상태이고 최신 데이터와 다를 수 있어요.</p></details></div>
<p class="footer-note">추천과 분석은 참고 자료입니다. 실제 거래 승인·실행과 자산 이전은 ProjectAgain 플랫폼에서만 처리합니다.</p>
</div></main></div></body></html>'''
output=ROOT/'docs'/'visual_static_preview_v0174.html'
output.write_text(html,encoding='utf8')
print(output)
