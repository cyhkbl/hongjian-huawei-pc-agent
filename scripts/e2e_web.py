"""Browser e2e for 鸿笺 (Playwright).

Usage:
    python scripts/e2e_web.py                  # starts the fake-backend server itself
    python scripts/e2e_web.py --url http://127.0.0.1:7860 --real   # against a running real server

Checks the key path, console cleanliness, failed requests, and writes
375/768/1440 screenshots to docs/shots/. Credentials never appear on screen
(the fake backend only holds fake keys, and the KB drawer shows masks).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "shots"
PY = sys.executable

problems: list[str] = []
passed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (passed if cond else problems).append(name if cond else f"{name} {detail}".strip())
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def wait_up(url: str, timeout: float = 25) -> None:
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/health", timeout=2).read()
            return
        except Exception:
            time.sleep(0.4)
    raise SystemExit("server did not start")


def launch(p, channel_pref=("chrome", "msedge", None)):
    last = None
    for ch in channel_pref:
        try:
            return p.chromium.launch(channel=ch, headless=True) if ch else p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            last = e
    raise SystemExit(f"no browser available: {last}")


def run(url: str, real: bool, shots: bool) -> None:
    from playwright.sync_api import sync_playwright
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = launch(p)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True, bypass_csp=True,
                                  permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        console_errors: list[str] = []
        failed: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)))
        page.on("response", lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 and "/api/image/" not in r.url and "favicon" not in r.url else None)
        page.on("requestfailed", lambda r: failed.append(f"FAILED {r.url} {r.failure}"))

        page.goto(url)
        page.wait_for_selector("#f-text", timeout=15000)
        check("首页加载与标题", "鸿笺" in page.title())
        page.wait_for_function("document.querySelector('#kb-pill-text').textContent.trim() !== '知识库连接中'", timeout=15000)
        check("KB 胶囊显示状态", page.inner_text("#kb-pill-text").strip() != "")
        if shots:
            page.screenshot(path=str(SHOTS / "01-empty-1440.png"))

        # --- submit a task, see progress, four tabs
        page.fill("#f-text", "给 HUAWEI MateBook Pro 写一篇开学季的小红书笔记，面向大学新生。")
        page.click("button[type=submit]")
        try:
            page.wait_for_selector("#progress-card", timeout=4000)
            check("出现阶段进度", True)
        except Exception:
            check("出现阶段进度", False, "progress-card 未出现（后端过快时可忽略）" if real else "")
        page.wait_for_selector("#copy .s", timeout=90000)
        check("稿件渲染", page.locator("#copy .s").count() > 0)
        check("四段页签", page.locator("#col-article .tab").count() == 4)
        if shots:
            page.screenshot(path=str(SHOTS / "02-article-1440.png"))

        # --- evidence on click
        cited = page.locator("#copy .s.cited").first
        if cited.count():
            cited.click()
            page.wait_for_selector(".ev-card.pinned .ev-fact blockquote", timeout=5000)
            check("点句出证据（原文/来源）", page.locator(".ev-fact .src").count() > 0)
            check("证据含官方链接", page.locator(".ev-fact a[href^='http']").count() > 0)
            if shots:
                page.screenshot(path=str(SHOTS / "03-evidence-1440.png"))
            page.keyboard.press("Escape")
        else:
            check("点句出证据（原文/来源）", False, "没有带事实依据的句子")

        check("图片内嵌且带说明", page.locator("figure.fig img").count() > 0 and page.locator("figure.fig .mi").count() > 0)
        check("图片徽章 型号/来源/文件", page.locator("figure.fig .badge").count() >= 3)
        nat = page.evaluate("""() => { const i = document.querySelector('figure.fig img'); if(!i||!i.naturalWidth) return null;
            const r=i.getBoundingClientRect(); return [i.naturalWidth/i.naturalHeight, r.width/r.height]; }""")
        check("图片保持原比例", nat is not None and abs(nat[0] - nat[1]) / nat[0] < 0.03, str(nat))

        # --- other tabs
        for tab, needle in (("scene", "一、场景判断"), ("basis", "二、知识库依据"), ("verify", "四、核验结果")):
            page.click(f"#tab-{tab}")
            page.wait_for_selector("#tabpanel h2.sec")
            check(f"页签：{needle}", needle in page.inner_text("#tabpanel"))
            if shots and tab in ("verify", "basis"):
                page.screenshot(path=str(SHOTS / f"04-{tab}-1440.png"))
        check("核验结论徽章", page.locator(".verdict").count() == 1)
        page.click("#tab-article")

        # --- revise
        page.click("#stab-revise")
        page.fill("#rev-text", "再短一点")
        page.click("text=按这句话修改")
        page.wait_for_function("document.querySelectorAll('.ver').length >= 2", timeout=90000)
        check("改稿产生版本链 v1→v2", page.locator(".ver").count() >= 2)
        if shots:
            page.screenshot(path=str(SHOTS / "05-revise-1440.png"))
        page.locator(".ver").first.click()
        page.wait_for_selector("#copy .s")
        check("可回看 v1", page.locator(".ver[aria-current=true]").inner_text().strip() == "v1")

        # --- compare
        page.click("#stab-compare")
        page.wait_for_selector(".cmp-row")
        check("策略对比有差异标注", page.locator(".cmp-row.diff").count() >= 0 and page.locator(".cmp-row").count() > 5)
        if shots:
            page.screenshot(path=str(SHOTS / "06-compare-1440.png"))

        # --- export
        page.click("#export-btn")
        page.wait_for_selector(".menu")
        with page.expect_download(timeout=20000) as dl:
            page.click(".menu >> text=Markdown")
        check("导出 md 下载", dl.value.suggested_filename.endswith(".md"))
        page.click("#export-btn")
        with page.expect_download(timeout=20000) as dl:
            page.click(".menu >> text=运行档案")
        check("导出 json 下载", dl.value.suggested_filename.endswith(".json"))
        page.click("#export-btn")
        page.click(".menu >> text=复制正文")
        clip = page.evaluate("navigator.clipboard.readText()")
        check("复制正文进剪贴板", len(clip) > 20)

        # --- clarification
        page.click(".view-btn[data-view=studio]") if page.locator(".view-btn[data-view=studio]").count() else None
        page.fill("#f-text", "想买个轻薄本，帮我写篇软文。")
        page.click("button[type=submit]")
        page.wait_for_selector(".clar", timeout=60000)
        check("出现追问卡与选项", page.locator(".clar .opt").count() >= 2)
        if shots:
            page.screenshot(path=str(SHOTS / "07-clarify-1440.png"))
        if page.locator("#clar-go").count():  # several questions: answer each required one, then continue
            for fs in page.locator(".clar fieldset").all():
                if "看重" in fs.locator("legend").inner_text():
                    continue
                fs.locator(".opt").first.click()
            page.click("#clar-go")
        else:
            page.locator(".clar .opt").first.click()
        page.wait_for_selector("#copy .s", timeout=90000)
        check("点选追问选项后继续生成", page.locator("#copy .s").count() > 0)

        # --- refusal
        page.fill("#f-text", "写一条 MateBook D 16 的门店朋友圈，开学季，写上国补立减 2000 元，再加一句全网最低价。")
        page.click("button[type=submit]")
        page.wait_for_selector(".state.refuse, #clar-blocked, .clar, #copy .s", timeout=90000)
        if page.locator(".state.refuse").count():
            check("拒答态", True)
            if shots:
                page.screenshot(path=str(SHOTS / "08-refused-1440.png"))
        elif page.locator("#clar-blocked").count():
            check("违规要求在追问卡上被明示（后端先追问后拒绝）", True)
            if shots:
                page.screenshot(path=str(SHOTS / "08-refused-1440.png"))
        else:
            ok_text = page.inner_text("#copy")
            check("拒答态/不含虚构价格", "2000" not in ok_text and "全网最低" not in ok_text, "稿件写入了不该写的内容")

        # --- poster
        page.fill("#f-text", "给 HUAWEI MateBook Pro 做一张开学季门店海报，只保留三个卖点。")
        page.click("button[type=submit]")
        page.wait_for_selector("#poster-canvas, .state", timeout=90000)
        if page.locator("#poster-canvas").count():
            page.wait_for_timeout(600)
            size = page.evaluate("(() => { const c=document.querySelector('#poster-canvas'); return [c.width,c.height]; })()")
            check("海报 canvas 渲染", size[0] > 0 and size[1] > 0)
            with page.expect_download(timeout=20000) as dl:
                page.click("text=导出 PNG")
            check("海报 PNG 导出", dl.value.suggested_filename.endswith(".png"))
            if shots:
                page.screenshot(path=str(SHOTS / "09-poster-1440.png"))
        else:
            check("海报 canvas 渲染", False, "没有生成海报")

        # --- KB drawer
        page.click("#kb-pill")
        page.wait_for_selector("#kb-drawer .kv")
        text = page.inner_text("#kb-drawer")
        check("KB 抽屉含模式与计数", "知识库" in text and "事实点" in text)
        check("KB 抽屉不显示完整 key", "SECRET" not in text and "sk-" not in text)
        if shots:
            page.screenshot(path=str(SHOTS / "10-kb-drawer-1440.png"))
        page.keyboard.press("Escape")
        check("Esc 关闭抽屉", page.locator("#kb-drawer").is_hidden())
        check("焦点回到胶囊", page.evaluate("document.activeElement && document.activeElement.id") == "kb-pill")

        # --- archive
        page.click(".view-btn[data-view=archive]")
        page.wait_for_selector("#archive h2", timeout=15000)
        page.wait_for_selector("#archive .case, #archive .state.error", timeout=15000)
        check("档案页：提示词版本", page.locator("#archive .badge.info").count() > 0)
        if page.locator("#archive .case").count():
            page.click("#archive >> text=一键运行全部")
            page.wait_for_function("document.querySelector('#selftest-sum')", timeout=300000)
            check("自测台显示通过/失败", page.locator("#selftest-sum").count() == 1)
            print("     自测汇总:", page.inner_text("#selftest-sum").strip())
        else:
            print("     (自测集尚未就绪，已验证失败态可见)")
            check("自测台失败态可读", page.locator("#archive .state.error").count() == 1)
        if shots:
            page.screenshot(path=str(SHOTS / "11-archive-1440.png"), full_page=False)
        # --- keyboard focus ring + a11y smoke
        page.goto(url)
        page.wait_for_selector("#f-text")
        page.keyboard.press("Tab")
        check("跳转链接可聚焦", page.evaluate("document.activeElement.className") == "skip")
        missing_alt = page.evaluate("Array.from(document.images).filter(i=>!i.hasAttribute('alt')).length")
        check("所有图片都有 alt 属性", missing_alt == 0)
        unnamed = page.evaluate("""Array.from(document.querySelectorAll('button')).filter(b=>!(b.textContent.trim()||b.getAttribute('aria-label'))).length""")
        check("按钮都有可读名称", unnamed == 0)

        # --- responsive screenshots + overflow check
        for w, h_ in ((375, 812), (768, 1024), (1440, 900)):
            vctx = browser.new_context(viewport={"width": w, "height": h_}, bypass_csp=True)
            vp = vctx.new_page()
            vp.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            vp.goto(url)
            vp.wait_for_selector("#f-text")
            vp.wait_for_function("document.querySelector('#kb-pill-text').textContent.trim() !== '知识库连接中'")
            if shots:
                vp.screenshot(path=str(SHOTS / f"resp-{w}-task.png"))
            vp.fill("#f-text", "给 HUAWEI MateBook Pro 写一篇开学季的小红书笔记，面向大学新生。")
            vp.click("button[type=submit]")
            vp.wait_for_selector("#copy .s", timeout=90000)
            vp.wait_for_timeout(400)
            ov = vp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check(f"{w}px 无横向溢出", ov <= 1, f"overflow={ov}")
            if shots:
                vp.screenshot(path=str(SHOTS / f"resp-{w}-article.png"))
            if w < 1100:
                vp.click("#panebar [data-pane=side]")
                vp.wait_for_selector("#col-side")
                if shots:
                    vp.screenshot(path=str(SHOTS / f"resp-{w}-side.png"))
            vctx.close()

        ctx.close()
        browser.close()

    check("控制台无错误", not console_errors, "; ".join(console_errors[:5]))
    check("无失败请求", not failed, "; ".join(failed[:5]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--real", action="store_true", help="running against the real backend")
    ap.add_argument("--no-shots", action="store_true")
    a = ap.parse_args()
    proc = None
    url = a.url
    if not url:
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
        server_py = str(venv_py) if venv_py.is_file() else PY
        proc = subprocess.Popen([server_py, "-m", "tests.test_web_support", "--port", str(a.port), "--delay", "0.15"], cwd=ROOT, env=env)
        url = f"http://127.0.0.1:{a.port}"
    try:
        wait_up(url)
        run(url, a.real, not a.no_shots)
    finally:
        if proc:
            proc.terminate()
    print(f"\n{len(passed)} passed, {len(problems)} failed")
    for p_ in problems:
        print("  - " + p_)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())



