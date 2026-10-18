"""抓线上页面渲染后的 DOM，定位任务台输入框的真实选择器。"""
from playwright.sync_api import sync_playwright

URL = "https://cyhkbl-hongjian.ms.show"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chrome")
    page = b.new_page(viewport={"width": 1440, "height": 960})
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(8000)
    print("url:", page.url)
    print("title:", page.title())
    print("main id list:", page.evaluate("() => Array.from(document.querySelectorAll('main,section,aside')).map(e => e.id || e.className).join(' | ')"))
    print("body text (600):", (page.evaluate("() => document.body.innerText") or "")[:600].replace("\n", " / "))
    print("inputs:", page.evaluate("() => Array.from(document.querySelectorAll('textarea,input,[contenteditable]')).map(e => e.tagName + '#' + e.id).join(',')"))
    print("buttons (15):", page.evaluate("() => Array.from(document.querySelectorAll('button')).slice(0,15).map(e => (e.textContent||'').trim().slice(0,20)).join(' | ')"))
    print("frames:", [f.url[:60] for f in page.frames])
    b.close()
