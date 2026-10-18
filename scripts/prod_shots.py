"""对线上创空间截图。应用被魔搭用 iframe 嵌在 studios 页面里，
所以要用 frame_locator 进入我们的页面。"""
import os
import sys

from playwright.sync_api import sync_playwright

ENTRY = "https://www.modelscope.cn/studios/cyhkbl/hongjian"
APP = "https://cyhkbl-hongjian.ms.show"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "shots")
os.makedirs(OUT, exist_ok=True)

errors: list[str] = []
failed: list[str] = []


def launch(p):
    for ch in ("chrome", "msedge"):
        try:
            return p.chromium.launch(headless=True, channel=ch)
        except Exception as e:  # noqa: BLE001
            print(f"launch {ch} failed: {e}")
    return None


def app_frame(page):
    """返回承载我们应用的 frame（先直接开应用地址，拿不到再退回 iframe）。"""
    for f in page.frames:
        if APP.split("//")[1] in f.url:
            return f
    return page.main_frame


def in_app(page):
    f = app_frame(page)
    return f


def main() -> int:
    with sync_playwright() as p:
        browser = launch(p)
        if browser is None:
            print("没有可用浏览器")
            return 1
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed.append(r.url))

        page.goto(ENTRY, wait_until="networkidle")
        page.wait_for_timeout(6000)
        f = in_app(page)
        if f is page.main_frame or APP.split("//")[1] not in (f.url if f else ""):
            # iframe 还没挂上，等它出现
            try:
                page.wait_for_selector(f"iframe[src*='{APP.split('//')[1]}']", timeout=40000)
            except Exception as e:  # noqa: BLE001
                print("iframe 未出现:", e)
            page.wait_for_timeout(4000)
            f = in_app(page)
        print("frame url:", (f.url if f else "?")[:90])
        has = f.evaluate("() => !!document.querySelector('#col-task')") if f else False
        print("col-task in frame:", has)

        page.screenshot(path=os.path.join(OUT, "prod-01-home.png"), full_page=True)
        print("01 home ok")

        # 任务输入
        sel = "#task-input, #task-text, #prompt-input, textarea"
        f.wait_for_selector(sel, timeout=30000)
        box = f.locator(sel).first
        box.click()
        box.fill("给 MateBook Pro 写一篇开学季小红书，面向大学新生")
        f.locator("button:has-text('生成')").first.click()
        page.wait_for_timeout(15000)
        page.screenshot(path=os.path.join(OUT, "prod-02-article.png"), full_page=True)
        print("02 article ok")

        imgs = f.locator("#col-article img").all()
        rows = []
        for im in imgs[:8]:
            try:
                nat = im.evaluate("e => ({w: e.naturalWidth, h: e.naturalHeight})")
            except Exception:  # noqa: BLE001
                nat = {"w": 0, "h": 0}
            rows.append(((im.get_attribute("src") or "").rsplit("/", 1)[-1][:34], nat["w"], nat["h"]))
        print("article images:", rows)

        # 点正文一句 → 证据
        try:
            f.locator("#col-article p, #col-article li").first.click(timeout=10000)
            page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(OUT, "prod-03-evidence.png"), full_page=True)
            print("03 evidence ok")
        except Exception as e:  # noqa: BLE001
            print("evidence:", e)

        # 知识库抽屉
        try:
            f.locator("#kb-pill").click(timeout=10000)
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(OUT, "prod-04-kb-drawer.png"))
            print("04 kb drawer ok")
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception as e:  # noqa: BLE001
            print("kb drawer:", e)

        # 追问卡
        box.click()
        box.fill("想买轻薄本")
        f.locator("button:has-text('生成')").first.click()
        page.wait_for_timeout(12000)
        page.screenshot(path=os.path.join(OUT, "prod-05-clarify.png"), full_page=True)
        print("05 clarify ok")

        # 海报
        box.click()
        box.fill("给 MateBook Pro S 写门店海报，新品首发")
        f.locator("button:has-text('生成')").first.click()
        page.wait_for_timeout(14000)
        page.screenshot(path=os.path.join(OUT, "prod-06-poster.png"), full_page=True)
        print("06 poster ok")

        # 档案与自测台
        try:
            f.locator("button[data-view='archive']").click(timeout=10000)
            page.wait_for_timeout(3000)
            page.screenshot(path=os.path.join(OUT, "prod-07-archive.png"), full_page=True)
            print("07 archive ok")
        except Exception as e:  # noqa: BLE001
            print("archive:", e)

        # 窄屏
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(OUT, "prod-08-mobile.png"), full_page=True)
        print("08 mobile ok")

        browser.close()

    print("console errors:", len(errors), errors[:6])
    print("failed requests:", len(failed), failed[:6])
    return 0


if __name__ == "__main__":
    sys.exit(main())
