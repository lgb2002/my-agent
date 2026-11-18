"""Visual static QA for v0.19.2.

This CSS/HTML fixture approximates the keyed Streamlit DOM; it does not verify
live Streamlit widget interactions, platform logins or Supabase persistence.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'assets/style.css').read_text(encoding='utf8')
HTML='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>''' + CSS + '''</style><style>
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--bg);color:var(--ink)}
.mock-app{height:100dvh;display:flex;overflow:hidden}
[data-testid="stSidebar"]{flex:0 0 284px;width:284px;min-width:0;height:100%;padding:14px 16px 11px;display:flex;flex-direction:column}
[data-testid="stSidebarContent"]{flex:1;min-height:0}
[data-testid="stSidebarContent"] > [data-testid="stVerticalBlock"]{height:100%;display:flex;flex-direction:column;gap:5px}
.st-key-sidebar_chat_panel_v0188{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.st-key-sidebar_chat_panel_v0188 > [data-testid="stVerticalBlock"]{display:flex;flex-direction:column;flex:1;min-height:0}
.st-key-sidebar_primary_actions_v0192 > [data-testid="stVerticalBlock"]{display:flex;flex-direction:column}
.st-key-sidebar_recent_v0189{flex:1;min-height:0;overflow-y:auto}
button{font:inherit;cursor:pointer}
.stButton button{width:100%;display:flex;align-items:center;justify-content:flex-start}
.st-key-chat_nav_row_v0187_mock [data-testid="stHorizontalBlock"]{display:flex;align-items:center;gap:2px;min-width:0}
.st-key-chat_nav_row_v0187_mock .message{flex:1;min-width:0}
.st-key-chat_nav_row_v0187_mock .more{flex:0 0 28px}
.st-key-chat_nav_row_v0187_mock .more button{justify-content:center}
.st-key-sidebar_account_panel_v0188{flex:0 0 auto}
.st-key-sidebar_account_panel_v0188 [data-testid="stPopover"] button{width:100%}
.st-key-compact_account_popover_v0191{position:absolute;left:298px;bottom:25px;background:#fff;padding:9px;border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 35px #163a2814;width:250px;z-index:2}
.st-key-compact_account_popover_v0191 .stButton button,.st-key-compact_account_popover_v0191 a{width:100%}
.st-key-compact_account_popover_v0191 [data-testid="stVerticalBlock"]{display:flex;flex-direction:column;gap:1px}
main{flex:1;min-width:0;padding:1rem 3.5rem}
.main-content{max-width:770px;margin:0 auto}
.workspace-bar{padding:10px 0 12px}
.welcome{margin-top:115px}
.mock-input{border:1px solid var(--line-strong);border-radius:10px;background:#fff;padding:17px;margin-top:24px;font-size:.93rem;color:#768379}
.note{font-size:.74rem;color:var(--muted);margin-top:16px}
@media(max-width:760px){
 [data-testid="stSidebar"]{width:308px;flex-basis:308px;max-width:100%;}
 main{display:none}
 .st-key-compact_account_popover_v0191{left:18px;bottom:65px;max-width:calc(100% - 36px)}
}
</style></head><body><div class="mock-app"><aside data-testid="stSidebar"><div data-testid="stSidebarContent"><div data-testid="stVerticalBlock">
<div class="brand"><span class="brand-symbol">◈</span> ProjectAgain</div>
<div class="st-key-sidebar_chat_panel_v0188"><div data-testid="stVerticalBlock">
<div class="st-key-sidebar_primary_actions_v0192"><div data-testid="stVerticalBlock">
<div class="stButton" data-testid="stButton"><button kind="tertiary" aria-label="새 대화"><span>✎</span>&nbsp; 새 대화</button></div>
<div class="stButton" data-testid="stButton"><button kind="tertiary" aria-label="대화 검색"><span>⌕</span>&nbsp; 대화 검색</button></div>
</div></div>
<div class="sidebar-chat-title">최근 대화</div>
<div class="st-key-sidebar_recent_v0189">
<div class="sidebar-chat-section">오늘</div>
<div class="st-key-chat_nav_row_v0187_mock"><div data-testid="stHorizontalBlock"><div class="message stButton"><button disabled>● 50만원 이하 프로젝트 추천</button></div><div class="more stButton"><button>⋯</button></div></div></div>
<div class="st-key-chat_nav_row_v0187_mock"><div data-testid="stHorizontalBlock"><div class="message stButton"><button>매물 인수 전 검토</button></div><div class="more stButton"><button>⋯</button></div></div></div>
<div class="sidebar-chat-section">지난 7일</div>
<div class="st-key-chat_nav_row_v0187_mock"><div data-testid="stHorizontalBlock"><div class="message stButton"><button>React 웹 프로젝트 비교</button></div><div class="more stButton"><button>⋯</button></div></div></div>
</div>
</div></div>
<div class="st-key-sidebar_account_panel_v0188"><div data-testid="stPopover"><button><span>◉</span> 내 계정 <span style="margin-left:auto;opacity:.5">⌃</span></button></div></div>
</div></div></aside><main><div class="main-content"><div class="workspace-bar"><div>프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div><div class="welcome"><div class="welcome-eyebrow"><span class="welcome-rule"></span>PROJECTAGAIN AI</div><div class="welcome-title">어떤 프로젝트를 찾고 계신가요?</div><p class="welcome-description">찾는 프로젝트나 예산을 편하게 말씀해 주세요.</p><div class="mock-input">예: 50만원 이하 Python 프로젝트를 추천해줘　↑</div></div></div></main>
<div class="st-key-compact_account_popover_v0191"><div data-testid="stVerticalBlock"><div class="account-popover-heading-v0192">ProjectAgain 계정</div>
<div class="stButton" data-testid="stButton"><button>⇄　다른 계정으로 로그인</button></div><div class="stButton" data-testid="stButton"><button>⚙　설정</button></div><div data-testid="stLinkButton"><a href="#">↗　ProjectAgain 웹사이트</a></div><div class="stButton" data-testid="stButton"><button>↪　로그아웃</button></div>
</div></div></div></body></html>'''


def main():
    from playwright.sync_api import sync_playwright
    out=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for width in (390,768,1280):
            page=browser.new_page(viewport={'width':width,'height':830},device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            if width==768:
                page.locator('.st-key-compact_account_popover_v0191').evaluate('(el)=>el.style.display="none"')
            measurement=page.evaluate('''() => {
              let q=s=>document.querySelector(s).getBoundingClientRect();
              const nav=q('.st-key-sidebar_primary_actions_v0192 button');
              const account=q('.st-key-sidebar_account_panel_v0188 button');
              const footer=q('.st-key-sidebar_account_panel_v0188');
              const header=q('.brand');
              return {viewport:innerWidth, document:document.documentElement.scrollWidth,
                navHeight:Math.round(nav.height), accountHeight:Math.round(account.height),
                footerTop:Math.round(footer.top), footerBottom:Math.round(footer.bottom),
                headerBottom:Math.round(header.bottom)};
            }''')
            assert measurement['document']<=width,measurement
            assert measurement['footerBottom']<=830,measurement
            assert measurement['footerTop']>measurement['headerBottom']+75,measurement
            assert measurement['navHeight'] == (44 if width<=760 else 36),measurement
            assert measurement['accountHeight'] == (44 if width<=760 else 39),measurement
            file=f'sidebar_static_{width}px_v0192.png'
            page.screenshot(path=str(ROOT/'docs'/file),full_page=True)
            out.append(measurement)
            page.close()
        browser.close()
    (ROOT/'docs'/'sidebar_static_qa_v0192.json').write_text(json.dumps({
        'scope':'static HTML/CSS fixture; not a real Streamlit or OAuth E2E',
        'tested':out},ensure_ascii=False,indent=2),encoding='utf8')
    print('QA',json.dumps(out,ensure_ascii=False))

if __name__=='__main__':
    main()
