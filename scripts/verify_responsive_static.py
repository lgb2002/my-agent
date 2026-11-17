"""Optional visual CSS smoke test. NOT a running Streamlit/browser end-to-end test.

Requires local Playwright and Chromium. Run this separately from unittest.
It approximates the rendered native containers to check elementary overflow.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'assets/style.css').read_text(encoding='utf-8')
HTML='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
*{box-sizing:border-box;}body{margin:0;}.layout{display:flex;min-height:100vh;}
aside{flex:0 0 240px;background:#F4F6F2;padding:15px;overflow:hidden;}
main{flex:1;min-width:0;}[data-testid="stMainBlockContainer"]{width:100%;margin:auto;}
[data-testid="stHorizontalBlock"]{display:flex;gap:8px;min-width:0;}
[data-testid="column"]{flex:1;min-width:0;}button{width:100%;padding:10px;}
[data-testid="stChatMessage"]{min-width:0;}table{border-collapse:collapse;min-width:580px;}
th,td{border:1px solid #ddd;padding:8px;text-align:left;}
[data-testid="stChatInput"]{margin:20px 0;padding:15px;}
@media(max-width:700px){aside{display:none;}}
</style><style>''' + CSS + '''</style></head><body><div class="layout">
<aside data-testid="stSidebar"><div class="brand">◈ ProjectAgain</div>시연 매물 포함<hr>＋ 새 대화<br>대화 보관함<br>추천 조건 확인</aside>
<main data-testid="stMain"><div data-testid="stMainBlockContainer"><div class="workspace-bar"><b>프로젝트 에이전트</b><span class="workspace-meta">플랫폼 조회 · 읽기 전용</span></div>
<div class="conversation-actions-label">대화 중에도 바로 요청할 수 있어요</div>
<div class="st-key-conversation_shortcuts_v11"><div data-testid="stHorizontalBlock"><div data-testid="column"><button>조건으로 다시 추천</button></div><div data-testid="column"><button>첫 번째 후보 공개 정보 검토</button></div></div></div>
<div data-testid="stChatMessage"><div data-testid="stMarkdownContainer"><p>50만원 이하로 운영하기 쉬운 프로젝트 3개 추천해줘. 위험이 낮은 쪽이 좋겠어.</p></div></div>
<div data-testid="stChatMessage"><div data-testid="stMarkdownContainer"><p>추천 후보 3건 · 자료 확인이 필요한 부분을 분리해서 보여줘.</p></div>
<div data-testid="stTable"><table><tr><th>후보</th><th>가격</th><th>맞는 이유</th><th>확인할 점</th></tr><tr><td>프로젝트 A</td><td>350,000원</td><td>Python 기술 조건 일치</td><td>운영비 미확인</td></tr><tr><td>프로젝트 B</td><td>420,000원</td><td>운영 부담 낮음</td><td>인수 권리 미확인</td></tr><tr><td>프로젝트 C</td><td>280,000원</td><td>예산 여유</td><td>기술 검증 필요</td></tr></table></div>
</div><div class="approval-panel"><div class="approval-kicker">확인 필요</div><div class="approval-title">구매 제안 초안</div><p class="approval-desc">제안 금액 350,000원 · 플랫폼 승인 전</p></div>
<div data-testid="stHorizontalBlock"><div data-testid="column"><button>플랫폼에 초안 제출</button></div><div data-testid="column"><button>취소</button></div></div>
<div data-testid="stChatInput">메시지 입력...</div></div></main></div></body></html>'''


def main():
    output=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        for w,h in [(320,850),(360,800),(390,844),(768,900),(1280,900)]:
            page=browser.new_page(viewport={'width':w,'height':h}, device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            page.wait_for_timeout(100)
            measures=page.evaluate('''() => ({scrollWidth: document.documentElement.scrollWidth,
                viewportWidth:innerWidth, tableScrollWidth:document.querySelector('[data-testid="stTable"]').scrollWidth,
                tableClientWidth:document.querySelector('[data-testid="stTable"]').clientWidth})''')
            filename=ROOT/'docs'/f'responsive_static_{w}px.png'
            page.screenshot(path=str(filename),full_page=True)
            output.append((w,measures))
            if measures['scrollWidth'] > w+1:
                raise AssertionError(f'Horizontal page overflow at {w}: {measures}')
            page.close()
        browser.close()
    for w,values in output:
        print(w,values)

if __name__=='__main__':main()
