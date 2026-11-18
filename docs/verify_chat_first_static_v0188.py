"""STATIC Chromium fixture. Verifies visual CSS, not Streamlit server behavior."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'assets/style.css').read_text(encoding='utf-8')
HTML=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg)}}.fixture{{display:flex;min-height:100vh}}
[data-testid="stSidebar"]{{width:286px;flex:0 0 286px;padding:22px 16px}}
main{{flex:1;min-width:0;padding:0 24px}}
[data-testid="stMainBlockContainer"]{{margin:0 auto;max-width:820px;padding:20px 0}}
.st-key-welcome_actions [data-testid="stHorizontalBlock"]{{display:grid;grid-template-columns:1fr 1fr;gap:13px;margin-bottom:13px}}
.st-key-welcome_actions button{{width:100%;font:inherit;cursor:pointer}}
.st-key-welcome_actions .suggestion-hint{{margin-bottom:0}}
.stButton>button{{cursor:pointer}}
.sidebar-chat-row{{display:flex;align-items:center;justify-content:space-between;border-radius:9px;padding:7px 10px;font-size:.84rem;min-height:39px}}
.sidebar-chat-row.active{{background:#E3ECE2;color:#285640;font-weight:750}}
.sidebar-chat-row .dots{{font-weight:900}}.sidebar-small{{font-size:.77rem;color:var(--muted);line-height:1.6}}
.sidebar-section{{border-top:1px solid var(--line);padding-top:15px;margin-top:20px}}
.sidebar-primary{{background:var(--accent);border-radius:9px;color:#fff;padding:12px;text-align:left;font-weight:690}}
.st-key-sidebar_account_panel_v0188{{border-top:1px solid var(--line);margin-top:20px;padding-top:15px}}
.fake-search{{width:100%;min-height:40px;background:#fff;border:1px solid var(--line-strong);border-radius:9px;padding:10px;font-size:.83rem;color:var(--muted)}}
.st-key-welcome_input_v0188{{margin-top:0}}
[data-testid="stChatInput"]{{padding:12px;color:var(--muted);font-size:.86rem;min-height:57px}}
@media(max-width:760px){{[data-testid="stSidebar"]{{display:none}}main{{padding:0 14px}}.st-key-welcome_actions [data-testid="stHorizontalBlock"]{{display:flex;flex-direction:column;gap:8px}}}}
</style></head><body><div class="fixture">
<aside data-testid="stSidebar"><div class="brand"><span class="brand-symbol">◈</span>ProjectAgain</div>
<div class="st-key-sidebar_chat_panel_v0188"><div class="sidebar-chat-title">대화</div><div class="sidebar-primary">＋ 새 대화</div>
<div class="fake-search" style="margin-top:12px">대화 제목 검색</div>
<div class="sidebar-chat-section">오늘</div><div class="sidebar-chat-row active">Python 프로젝트 추천 <span class="dots">⋯</span></div>
<div class="sidebar-chat-row">매물 인수 전 검토 <span class="dots">⋯</span></div>
<div class="sidebar-chat-section">지난 7일</div><div class="sidebar-chat-row">지난 작업 기록 확인 <span class="dots">⋯</span></div>
<div class="sidebar-small" style="margin-top:15px">대화는 계정에 자동 저장돼요.</div>
<div class="sidebar-section"><p class="sidebar-small">▸ 매물 표시 설정</p><p class="sidebar-small">▸ 저장한 조건 · 작업</p><p class="sidebar-small">▸ ZIP 검사 · 도구</p></div></div>
<div class="st-key-sidebar_account_panel_v0188"><div class="sidebar-heading">ProjectAgain 계정</div><p class="sidebar-small">● 계정 연결됨 · 자동 갱신</p><p class="sidebar-small">기능 안내</p></div>
</aside><main><div data-testid="stMainBlockContainer"><div class="pa-layout-mode pa-layout-mode--reading"></div>
<div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div>
<section class="welcome"><div class="welcome-eyebrow"><span class="welcome-rule"></span>PROJECTAGAIN / AI DESK</div>
<h1 class="welcome-title">어떤 프로젝트를 찾고 계신가요?</h1>
<p class="welcome-description">조건을 편하게 말씀해 주세요. 매물을 찾고, 비교하고, 인수 전 확인할 점까지 정리해 드릴게요.</p></section>
<div class="st-key-welcome_input_v0188"><div data-testid="stChatInput">예: 50만원 이하 Python 프로젝트를 추천해줘 <span style="float:right;color:var(--accent);font-size:1.1rem">↑</span></div></div>
<div class="st-key-welcome_actions"><div class="welcome-actions-heading"><span class="welcome-actions-title">바로 시작하기</span></div>
<div data-testid="stHorizontalBlock"><div class="st-key-welcome_tile_0"><div class="stButton"><button>매물 둘러보기</button></div><p class="suggestion-hint">등록된 프로젝트를 확인해요</p></div>
<div class="st-key-welcome_tile_1"><div class="stButton"><button>맞춤 추천</button></div><p class="suggestion-hint">내 조건에 맞는 후보를 찾아요</p></div></div>
<div data-testid="stHorizontalBlock"><div class="st-key-welcome_tile_2"><div class="stButton"><button>인수 전 검토</button></div><p class="suggestion-hint">위험과 필요한 자료를 살펴봐요</p></div>
<div class="st-key-welcome_tile_3"><div class="stButton"><button>이전 작업</button></div><p class="suggestion-hint">진행했던 작업을 확인해요</p></div></div></div>
<p class="footer-note">추천과 분석은 참고 자료입니다. 실거래 승인·실행과 자산 이전은 ProjectAgain 플랫폼에서만 처리합니다.</p>
</div></main></div></body></html>'''
if __name__=='__main__':
    from playwright.sync_api import sync_playwright
    recorded=[]
    with sync_playwright() as play:
        browser=play.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for width in (390,768,1280):
            page=browser.new_page(viewport={'width':width,'height':850},device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            result=page.evaluate('''() => ({width:innerWidth, doc:document.documentElement.scrollWidth,
                cards:document.querySelectorAll('[class*="st-key-welcome_tile_"]').length,
                input:!!document.querySelector('[data-testid="stChatInput"]')})''')
            if result['doc']>width or result['cards'] !=4 or not result['input']:
                raise AssertionError(result)
            page.screenshot(path=str(ROOT/'docs'/f'chat_first_static_{width}px_v0188.png'),full_page=True)
            recorded.append(result)
            page.close()
        browser.close()
    (ROOT/'docs'/'chat_first_static_qa_v0188.json').write_text(json.dumps({'static_only':True,'streamlit_cloud_verified':False,'results':recorded},indent=2),encoding='utf-8')
    print('Static viewports:',recorded)
