"""Static Chromium fixture for the compact v0.18.9 shell.

Checks CSS/responsive geometry, NOT live Streamlit widget semantics, identity,
logout, DB sync, or modal behavior on Streamlit Cloud.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'assets/style.css').read_text(encoding='utf8')
HTML='''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><style>''' + CSS + '''</style><style>
*{box-sizing:border-box;} body{margin:0;color:var(--ink);background:var(--bg);}
.fixture{min-height:100vh;display:flex;align-items:stretch;}
[data-testid="stSidebar"]{width:271px;flex:0 0 271px;padding:27px 16px 13px;min-height:100vh;}
[data-testid="stSidebar"] button{font-family:inherit;cursor:pointer;width:100%;}
[data-testid="stSidebar"] .st-key-sidebar_chat_panel_v0188{display:flex;flex-direction:column;}
[data-testid="stSidebar"] .st-key-sidebar_shortcuts_v0189 [data-testid="stHorizontalBlock"]{display:flex;gap:5px;}
[data-testid="stSidebar"] .st-key-sidebar_shortcuts_v0189 [data-testid="column"]{width:50%;min-width:0;}
[data-testid="stSidebar"] .st-key-sidebar_account_panel_v0188{border-top:1px solid var(--line);}
[data-testid="stSidebar"] .st-key-sidebar_account_panel_v0188 .stButton button{text-align:left;}
.st-key-sidebar_recent_v0189{padding-top:4px;}
.st-key-chat_nav_row_v0187_1,.st-key-chat_nav_row_v0187_2,.st-key-chat_nav_row_v0187_3{display:flex;justify-content:space-between;align-items:center;}
.st-key-chat_nav_row_v0187_1{background:#E3ECE2;}
.st-key-chat_nav_row_v0187_1 button,.st-key-chat_nav_row_v0187_2 button,.st-key-chat_nav_row_v0187_3 button{background:transparent!important;border:0!important;}
.st-key-chat_nav_row_v0187_1 .ellipsis,.st-key-chat_nav_row_v0187_2 .ellipsis,.st-key-chat_nav_row_v0187_3 .ellipsis{width:30px;}
main{flex:1;min-width:0;padding:0 24px 40px;}
[data-testid="stMainBlockContainer"]{margin:0 auto;max-width:820px;padding:25px 0 80px;}
.st-key-welcome_actions [data-testid="stHorizontalBlock"]{display:flex;gap:8px;}
.st-key-welcome_actions [data-testid="column"]{width:25%;min-width:0;}
.st-key-welcome_actions button{cursor:pointer;width:100%;font-family:inherit;}
[data-testid="stChatInput"]{padding:15px 16px;min-height:54px;font-size:.91rem;color:#67786B;}
.fake-search{background:#fff;border:1px solid var(--line-strong);border-radius:8px;padding:10px;font-size:.82rem;color:var(--muted);}
.sidebar-chat-section{margin-top:14px;}
.footer-note{margin-top:65px;}
@media(max-width:760px){[data-testid="stSidebar"]{display:none;}main{padding:0 16px 40px;}
.st-key-welcome_actions [data-testid="stHorizontalBlock"]{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));}
.st-key-welcome_actions [data-testid="column"]{width:100%;}}
</style></head><body><div class="fixture"><aside data-testid="stSidebar">
<div class="brand"><span class="brand-symbol">◈</span><span>ProjectAgain</span></div>
<div class="st-key-sidebar_chat_panel_v0188">
<div class="stButton"><button kind="primary">＋ 새 대화</button></div>
<div class="st-key-sidebar_shortcuts_v0189"><div class="sidebar-quick-label">바로가기</div>
<div data-testid="stHorizontalBlock"><div data-testid="column"><div class="stButton"><button>⌕ 매물 탐색</button></div></div>
<div data-testid="column"><div class="stButton"><button>✧ 맞춤 추천</button></div></div></div></div>
<div class="sidebar-chat-title">최근 대화</div>
<div class="fake-search" style="margin-bottom:7px">대화 제목 검색</div>
<div class="st-key-sidebar_recent_v0189"><div class="sidebar-chat-section">오늘</div>
<div class="st-key-chat_nav_row_v0187_1"><div class="stButton"><button>● 50만원 이하 프로젝트 찾기</button></div><div class="ellipsis">⋯</div></div>
<div class="st-key-chat_nav_row_v0187_2"><div class="stButton"><button>매물 인수 전 검토</button></div><div class="ellipsis">⋯</div></div>
<div class="sidebar-chat-section">지난 7일</div><div class="st-key-chat_nav_row_v0187_3"><div class="stButton"><button>저장된 작업 다시 확인</button></div><div class="ellipsis">⋯</div></div>
</div></div>
<div class="st-key-sidebar_account_panel_v0188"><div class="sidebar-user-identity"><span class="status-dot"></span>ProjectAgain 계정 연결됨</div>
<div class="stButton"><button>⚙ 설정</button></div></div></aside><main>
<div data-testid="stMainBlockContainer"><div class="pa-layout-mode pa-layout-mode--reading"></div>
<div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div>
<section class="welcome"><div class="welcome-eyebrow"><span class="welcome-rule"></span>PROJECTAGAIN AI</div>
<h1 class="welcome-title">어떤 프로젝트를 찾고 계신가요?</h1>
<p class="welcome-description">찾는 프로젝트나 예산을 편하게 말씀해 주세요.</p></section>
<div class="st-key-welcome_input_v0188"><div data-testid="stChatInput">예: 50만원 이하 Python 프로젝트를 추천해줘 <span style="float:right;color:var(--accent)">↑</span></div></div>
<div class="st-key-welcome_actions"><div class="welcome-actions-heading"><span class="welcome-actions-title">빠른 시작</span></div>
<div data-testid="stHorizontalBlock">
<div data-testid="column"><div class="st-key-welcome_tile_0"><div class="stButton"><button>매물 탐색</button></div></div></div>
<div data-testid="column"><div class="st-key-welcome_tile_1"><div class="stButton"><button>맞춤 추천</button></div></div></div>
<div data-testid="column"><div class="st-key-welcome_tile_2"><div class="stButton"><button>인수 전 검토</button></div></div></div>
<div data-testid="column"><div class="st-key-welcome_tile_3"><div class="stButton"><button>이전 작업</button></div></div></div>
</div></div>
<p class="footer-note">추천과 분석은 참고 자료입니다. 실제 거래 승인과 자산 이전은 ProjectAgain 플랫폼에서만 처리합니다.</p>
</div></main></div></body></html>'''


def main():
    from playwright.sync_api import sync_playwright
    results=[]
    with sync_playwright() as play:
        browser=play.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for w in (390,768,1280):
            page=browser.new_page(viewport={'width':w,'height':850},device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            measurements=page.evaluate('''() => ({width:innerWidth,doc:document.documentElement.scrollWidth,
                quick_count:document.querySelectorAll('[class*="st-key-welcome_tile_"]').length,
                quick_height:Math.ceil(document.querySelector('.st-key-welcome_tile_0 button').getBoundingClientRect().height),
                has_input:!!document.querySelector('[data-testid="stChatInput"]')})''')
            if measurements['doc']>w or measurements['quick_count']!=4 or not measurements['has_input']:
                raise AssertionError(measurements)
            page.screenshot(path=str(ROOT/'docs'/f'compact_shell_static_{w}px_v0189.png'),full_page=True)
            results.append(measurements)
            page.close()
        browser.close()
    (ROOT/'docs'/'compact_shell_static_qa_v0189.json').write_text(
        json.dumps({'scope':'static html/css fixture (not live Streamlit)','live_verified':False,
                    'viewports':results},ensure_ascii=False,indent=2),encoding='utf8')
    print('Static viewports:',results)


if __name__=='__main__': main()
