"""Optional CSS smoke test. This is NOT a running Streamlit UI test."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs'

HTML='''<!doctype html><html lang="ko"><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>html{box-sizing:border-box}*,*:before,*:after{box-sizing:inherit}body{margin:0;padding:0;background:#FAFAF8;color:#202D26;font-family:Arial,sans-serif}
.shell{max-width:1050px;margin:auto;padding:20px 22px 90px}table{width:100%;border-collapse:collapse}th,td{padding:14px 9px;border-bottom:1px solid #DEE5DE;text-align:left;vertical-align:top}td{font-size:13px;line-height:1.55}
.stButton button{width:100%;background:#fff;border:1px solid #DEE5DE;border-radius:8px;padding:13px;color:#295447}
[data-testid="stHorizontalBlock"]{display:flex;gap:12px}[data-testid="column"]{flex:1;min-width:0} </style>
<style>__PROJECT_CSS__</style><main class="shell"><div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div>
<div class="st-key-primary_workbench_v0173"><div class="workbench-eyebrow">추천 결과</div><h1 class="workbench-title">후보를 비교하고 선택하기</h1><b>현재 확인된 추천 조건</b>
<div class="criteria-strip"><span class="criteria-pill">목적 · 운영 수익</span><span class="criteria-pill">예산 · 500,000원 이하</span><span class="criteria-pill">개발 경험 · 중급</span><span class="criteria-pill">위험 허용 · 낮음</span><span class="criteria-pill">기술 · Python</span></div><p><b>추천 후보 비교</b></p><p>조건에 맞는 후보 3건 · 플랫폼 공개 매물 기준</p><div data-testid="stTable"><table><tr><th>후보</th><th>가격</th><th>맞는 이유</th><th>확인할 점</th></tr>
<tr><td>1. 프로젝트 A</td><td>350,000원</td><td>기술 수준과 일치</td><td>운영비 자료 미확인</td></tr><tr><td>2. 프로젝트 B</td><td>420,000원</td><td>공개된 운영 자료 확인</td><td>권리 범위 확인 필요</td></tr><tr><td>3. 프로젝트 C</td><td>280,000원</td><td>예산 여유가 있음</td><td>검사 기록 미확인</td></tr></table></div>
<p><b>1순위 · 프로젝트 A</b></p><p>Python 기술 조건과 일치하지만 운영비·권리 자료는 추가 확인이 필요합니다.</p></div>
<div class="next-actions-heading">이어 할 수 있는 일</div><div class="st-key-workspace_action_row_v0173"><div data-testid="stHorizontalBlock"><div data-testid="column" class="stButton"><button>1순위 공개 정보 검토</button></div><div data-testid="column" class="stButton"><button>후보 차이 설명</button></div><div data-testid="column" class="stButton"><button>조건 바꿔 다시 추천</button></div></div></div><div class="conversation-history-separator"></div><p>이전 대화 및 도구 실행 기록 · 7개 메시지</p>
<div style="padding:12px;border:1px solid #DEE5DE;border-radius:8px;color:#596C61">이전 대화 전체 보기 ▾</div><p class="footer-note">추천과 분석은 참고 자료입니다. 실제 승인 및 자산 이전은 플랫폼에서만 처리합니다.</p></main></html>'''


def main():
    css=(ROOT/'assets'/'style.css').read_text(encoding='utf-8')
    document=OUTPUT/'workbench_static_preview_v0173.html'
    document.write_text(HTML.replace('__PROJECT_CSS__',css),encoding='utf-8')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for width in [320,360,390,768,1280]:
            page=browser.new_page(viewport={'width':width,'height':900},device_scale_factor=1)
            page.set_content(document.read_text(encoding="utf-8"))
            result=page.evaluate('''() => ({scrollWidth:document.documentElement.scrollWidth,
                clientWidth:document.documentElement.clientWidth,
                headerWidth:document.querySelector('.workbench-title').getBoundingClientRect().width})''')
            if result['scrollWidth'] > result['clientWidth']+1:
                raise AssertionError(f'{width}px horizontal overflow: {result}')
            if width in (390,1280):
                page.screenshot(path=str(OUTPUT/f'workbench_static_{width}px_v0173.png'),full_page=True)
            print(width, 'px OK')
            page.close()
        browser.close()
    print('Static CSS only; actual Streamlit browser not launched.')


if __name__=='__main__':main()
