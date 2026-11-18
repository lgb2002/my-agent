"""Chromium STATIC visual fixture for v0.18.7. NOT a running Streamlit UI."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'assets/style.css').read_text(encoding='utf-8')
HTML=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg)}}.fixture{{display:flex;min-height:100vh}}
[data-testid="stSidebar"]{{width:286px;flex:0 0 286px;padding:22px 16px}}
main{{flex:1;min-width:0;padding:0 30px}}[data-testid="stMainBlockContainer"]{{margin:0 auto}}
.st-key-welcome_actions [data-testid="stHorizontalBlock"]{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}
.st-key-welcome_actions button{{width:100%;font:inherit;cursor:pointer}}
.stButton>button{{cursor:pointer}}.st-key-chat_nav_row_v0187_a,.st-key-chat_nav_row_v0187_b,.st-key-chat_nav_row_v0187_c{{margin:3px 0}}
.sidebar-chat-row{{display:flex;align-items:center;justify-content:space-between;border-radius:9px;padding:4px 10px;font-size:.86rem;min-height:39px}}
.sidebar-chat-row.active{{background:#E3ECE2;color:#285640;font-weight:750}}
.sidebar-chat-row .dots{{font-weight:900}}.sidebar-small{{font-size:.78rem;color:var(--muted);line-height:1.6}}
.sidebar-section{{border-top:1px solid var(--line);padding-top:15px;margin-top:20px}}.sidebar-primary{{background:var(--accent);border-radius:9px;color:#fff;padding:13px;text-align:left;font-weight:690}}
@media(max-width:760px){{[data-testid="stSidebar"]{{display:none}}main{{padding:0 16px}}.st-key-welcome_actions [data-testid="stHorizontalBlock"]{{display:flex;flex-direction:column;gap:6px}}}}
</style></head><body><div class="fixture">
<aside data-testid="stSidebar"><div class="brand"><span class="brand-symbol">◈</span>ProjectAgain</div>
<div class="sidebar-heading">매물 보기</div><p class="sidebar-small">☑ 시연 매물 포함</p>
<div class="sidebar-heading">ProjectAgain 계정</div><p class="sidebar-small">● 계정 연결됨 · 인증 정보 자동 갱신</p>
<div class="sidebar-chat-save">대화 저장</div><p class="sidebar-small">◉ Supabase에 자동 저장</p>
<div class="sidebar-chat-title">대화</div><div class="sidebar-primary">＋ 새 대화</div>
<div class="sidebar-chat-section">최근 대화</div>
<div class="sidebar-chat-row active">●  Python 프로젝트 추천 <span class="dots">⋯</span></div>
<div class="sidebar-chat-row">매물 인수 전 검토 <span class="dots">⋯</span></div>
<div class="sidebar-chat-row">지난 작업 기록 확인 <span class="dots">⋯</span></div>
<div class="sidebar-section"><p class="sidebar-small">▸ 저장한 조건 · 작업</p><p class="sidebar-small">▸ ZIP 검사 · 도구</p><p class="sidebar-small">사용 가능한 도구 · 9개</p></div>
</aside><main><div data-testid="stMainBlockContainer"><div class="pa-layout-mode pa-layout-mode--reading"></div>
<div class="workspace-bar"><div class="workspace-name">프로젝트 작업 공간</div><div class="workspace-meta"><span class="status-dot"></span>ProjectAgain API 연결</div></div>
<section class="welcome" aria-labelledby="title"><div class="welcome-eyebrow"><span class="welcome-rule"></span>PROJECTAGAIN / AI DESK</div>
<h1 class="welcome-title" id="title">어떤 프로젝트를<br>찾고 계신가요?</h1><p class="welcome-description">원하는 조건을 알려주세요. 매물 탐색부터 비교·검토까지 함께 정리해 드려요.</p></section>
<div class="st-key-welcome_actions"><div class="welcome-actions-heading"><span class="welcome-actions-title">바로 시작하기</span><span class="welcome-actions-count">4가지 시작 방법</span></div>
<div data-testid="stHorizontalBlock"><div class="st-key-welcome_tile_0"><div class="suggestion-index">01</div><div class="stButton"><button>매물 둘러보기</button></div><p class="suggestion-hint">등록된 프로젝트부터 살펴보기</p></div>
<div class="st-key-welcome_tile_1"><div class="suggestion-index">02</div><div class="stButton"><button>맞춤 추천 받기</button></div><p class="suggestion-hint">필요한 조건을 물어보고 적합한 후보 선별</p></div></div>
<div data-testid="stHorizontalBlock"><div class="st-key-welcome_tile_2"><div class="suggestion-index">03</div><div class="stButton"><button>실사 준비하기</button></div><p class="suggestion-hint">인수 전 검토 항목과 필요한 자료 먼저 확인</p></div>
<div class="st-key-welcome_tile_3"><div class="suggestion-index">04</div><div class="stButton"><button>작업 내역 확인</button></div><p class="suggestion-hint">이전에 진행한 작업 다시 보기</p></div></div></div>
<p class="footer-note">추천과 분석은 참고 자료입니다. 실거래 승인·실행과 자산 이전은 ProjectAgain 플랫폼에서만 처리합니다.</p>
</div></main></div></body></html>'''
if __name__=='__main__':
    from playwright.sync_api import sync_playwright
    records=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for width in (390,768,1280):
            page=browser.new_page(viewport={'width':width,'height':900},device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            vals=page.evaluate('''() => ({width: innerWidth, doc:document.documentElement.scrollWidth,
                tile_count:document.querySelectorAll('[class*="st-key-welcome_tile_"]').length,
                button_height: Math.round(document.querySelector('.st-key-welcome_tile_0 button').getBoundingClientRect().height)})''')
            if vals['doc']>width or vals['tile_count']!=4 or vals['button_height']<40:
                raise AssertionError(vals)
            page.screenshot(path=str(ROOT/'docs'/f'nav_static_{width}px_v0187.png'),full_page=True)
            records.append(vals)
            page.close()
        browser.close()
    (ROOT/'docs'/'nav_static_qa_v0187.json').write_text(json.dumps({'static_only':True,'streamlit_cloud_verified':False,'results':records},indent=2),encoding='utf8')
    print('Static navigation viewports OK:',records)
