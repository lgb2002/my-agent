"""Optional real-Chromium STATIC layout check (not a Streamlit E2E test).

Prerequisites: playwright and a working local Chromium executable.
The browser is given HTML via set_content, avoiding file:// restrictions.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent
HTML=(ROOT/'visual_static_preview_v0174.html').read_text(encoding='utf-8')
CHROMIUM=os.getenv('CHROMIUM_PATH','/usr/bin/chromium')
widths=(320,360,390,768,980,1280,1600)
records=[]
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True, executable_path=CHROMIUM,args=['--no-sandbox'])
    try:
        for width in widths:
            page=browser.new_page(viewport={'width':width,'height':920},device_scale_factor=1)
            page.set_content(HTML,wait_until='load')
            measurement=page.evaluate('''() => ({
                viewport:innerWidth,
                document_width:document.documentElement.scrollWidth,
                content_width:Math.round(document.querySelector('[data-testid="stMainBlockContainer"]').getBoundingClientRect().width),
                table_viewport_width:document.querySelector('[data-testid="stTable"]').clientWidth,
                table_scroll_width:document.querySelector('[data-testid="stTable"]').scrollWidth,
                first_button_height:Math.round(document.querySelector('.fixture-controls button').getBoundingClientRect().height)
            })''')
            assert measurement['document_width'] <= width, ('page overflow',width,measurement)
            assert measurement['first_button_height']>=44, ('button size',width,measurement)
            if width<=390:
                assert measurement['table_scroll_width']>measurement['table_viewport_width'],('table must scroll',width,measurement)
            page.screenshot(path=str(ROOT/f'visual_static_{width}px_v0174.png'),full_page=True)
            records.append(measurement)
            page.close()
    finally:
        browser.close()
report={'test':'static CSS viewport rendering, NOT deployed Streamlit UI',
        'chromium_executable':CHROMIUM,'widths_checked':list(widths),'results':records,
        'real_streamlit_cloud_checked':False,'mobile_touch_checked':False}
(ROOT/'visual_qa_v0174.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Static viewports OK:', len(records))
