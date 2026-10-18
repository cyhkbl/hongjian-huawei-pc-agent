"""writer-dev 测试用的 FakeKB：虚构最小数据，实现 base.KnowledgeBase Protocol。
所有产品数据都是自造占位（型号 Demo-H / Demo-W），不是 KB 原文。"""
from __future__ import annotations

import io
from typing import Optional

from app.models import (
    Fact, ImageAsset, KBStatus, PriceRecord, ProductModel, SearchHit, TraceEntry,
)

SRC = "演示型号｜02-屏幕与显示卡"
PATH = "P1-演示/演示型号/02-屏幕与显示卡.md"


def _f(mid, n, kind, cat, text, tags, cons=None):
    return Fact(id=f"{mid}:c{n:02d}", model_id=mid, kind=kind, category=cat, text=text,
                constraints=cons or [], tags=tags, source_title=SRC, source_path=PATH,
                source_urls=["https://example.invalid/demo"], verified_date="2026-10-17")


def _facts_for(mid: str, os_harmony: bool) -> list[Fact]:
    x = []
    n = 0

    def add(kind, cat, text, tags, cons=None):
        nonlocal n
        n += 1
        x.append(_f(mid, n, kind, cat, text, tags, cons))

    add("card", "identity", "官方完整名称为 Demo 示例本" + ("（鸿蒙版）" if os_harmony else "（Windows 版）"), [])
    add("spec", "identity", "操作系统：" + ("HarmonyOS 6" if os_harmony else "Windows 11 家庭中文版"), [])
    add("selling", "display", "屏幕采用 14.2 英寸 3:2 OLED 触控屏，分辨率 3120 × 2080", ["display", "creative"],
        ["亮度与色域为典型值"])
    add("card", "display", "典型亮度 600 nits，峰值亮度 1000 nits", ["display"], ["峰值亮度不等于日常亮度"])
    add("selling", "portable", "机身厚度 14.5 mm，重量约 1.3 kg", ["portable", "travel"], ["含电池，随配置变化"])
    add("card", "portable", "电池额定容量 70 Wh，支持 USB-C 充电", ["battery"], ["续航受亮度与负载影响"])
    add("spec", "connect", "接口：1 个 HDMI、2 个 USB-A、1 个 USB-C", ["ports"])
    add("selling", "connect", "支持 Wi-Fi 7 与蓝牙 6.0", ["collab"])
    add("card", "ecosystem", "同一华为账号下的设备可使用碰一碰传送文件", ["collab", "office"], ["需登录同一华为账号"])
    add("selling", "performance", "内存提供 24 GB 与 32 GB 两档，存储为 512 GB 或 1 TB", ["performance"], ["以实际销售配置为准"])
    add("selling", "performance", "搭载 AI 小艺，可协助整理文档", ["ai", "office"], ["部分 AI 能力需联网"])
    add("card", "audience", "适合长文档与表格为主的移动办公", ["office", "study"])
    add("fit", "audience", "学生查资料、写论文时窗口较多，3:2 屏幕有纵向空间优势", ["study"])
    add("spec", "performance", "键盘提供圆键盘与方键盘两种版本", ["keyboard"])
    add("unfit", "limit", "明确依赖 Windows 专用软件而未验证时，不宜直接下结论" if os_harmony
        else "依赖特定行业软件、驱动而未验证时，不宜直接下结论", [])
    add("boundary", "limit", "性能表述必须绑定具体配置与测试条件", [])
    return x


MODELS = [
    ProductModel(model_id="demo-h", name="HUAWEI Demo 示例本（鸿蒙版）", short_name="Demo 示例本 鸿蒙版",
                 series="Demo", os_family="harmonyos", os_label="HarmonyOS 6", aliases=["Demo 鸿蒙"],
                 snapshot_date="2026-10-17", has_public_price=True),
    ProductModel(model_id="demo-w", name="HUAWEI Demo 示例本（Windows 版）", short_name="Demo 示例本 Windows 版",
                 series="Demo", os_family="windows", os_label="Windows 11", aliases=["Demo Win"],
                 snapshot_date="2026-10-17", has_public_price=False),
]


def _png(color=(120, 120, 120), size=(40, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _img(mid, n, caption, tags, color=""):
    return ImageAsset(id=f"{mid}_img{n}.png", model_id=mid, caption=caption, tags=tags, color=color, width=1200, height=800,
                      source_url=f"https://example.invalid/{mid}/{n}.png", page_url="https://example.invalid/page",
                      kb_path=f"images/{mid}_img{n}.png", usage_note="")


IMAGES = (
    [_img("demo-h", 1, "外观正面", ["appearance"], "原野绿"), _img("demo-h", 2, "屏幕特写", ["display"], "原野绿"),
     _img("demo-h", 3, "接口细节", ["ports", "detail"], "原野绿"), _img("demo-h", 4, "办公场景", ["scene"], "原野绿"),
     _img("demo-h", 5, "另一颜色外观", ["appearance"], "烟云灰"), _img("demo-h", 6, "协同场景", ["collab", "scene"], ""),
     _img("demo-h", 7, "键盘细节", ["detail"], ""), _img("demo-h", 8, "侧面", ["appearance"], "原野绿")]
    + [_img("demo-w", 1, "外观", ["appearance"]), _img("demo-w", 2, "屏幕", ["display"]),
       _img("demo-w", 3, "接口", ["ports"])]
)

PRICES = [
    PriceRecord(record_id="P-h-1", model_id="demo-h", product_name="HUAWEI Demo 示例本（鸿蒙版）",
                spec="16GB/512GB/烟云灰", price_type="官方商城页面价", amount=7999.0,
                conditions="赠品；至高12期0分期利息", stock="页面显示现货", verified_at="2026-10-17T14:51:00-05:00",
                url="https://example.invalid/shop/h", status="已核验"),
    PriceRecord(record_id="P-h-2", model_id="demo-h", product_name="HUAWEI Demo 示例本（鸿蒙版）",
                spec="24GB/1TB/仲夏紫", price_type="官方商城页面价", amount=10499.0,
                conditions="", stock="页面显示现货", verified_at="2026-10-17T14:51:00-05:00",
                url="https://example.invalid/shop/h", status="已核验"),
    PriceRecord(record_id="P-h-3", model_id="demo-h", product_name="HUAWEI Demo 示例本（鸿蒙版）",
                spec="预估", price_type="预估到手价", amount=7000.0, conditions="含券", verified_at="2026-10-17T14:51:00-05:00",
                url="https://example.invalid/shop/h", status="已核验"),
    PriceRecord(record_id="P-w-1", model_id="demo-w", product_name="HUAWEI Demo 示例本（Windows 版）",
                spec="", price_type="当前商城状态", amount=None, conditions="", stock="商城已下架",
                verified_at="2026-10-17T14:51:00-05:00", url="https://example.invalid/shop/w", status="商城已下架"),
]


class FakeKB:
    def __init__(self):
        self._facts = {m.model_id: _facts_for(m.model_id, m.os_family == "harmonyos") for m in MODELS}
        self._trace: list[TraceEntry] = []
        self.search_calls: list[str] = []

    def status(self) -> KBStatus:
        return KBStatus(mode="local_mirror", kb_name="fake", connected=True)

    def models(self): return list(MODELS)

    def get_model(self, model_id): return next((m for m in MODELS if m.model_id == model_id), None)

    def find_models(self, text): return [(m, 0.9, m.aliases[0]) for m in MODELS if any(a in text for a in m.aliases)]

    def facts(self, model_id, kinds=None, categories=None, tags=None):
        out = list(self._facts.get(model_id, []))
        if kinds: out = [f for f in out if f.kind in kinds]
        if categories: out = [f for f in out if f.category in categories]
        if tags: out = [f for f in out if set(tags) & set(f.tags)]
        return out

    def get_fact(self, fact_id):
        for fs in self._facts.values():
            for f in fs:
                if f.id == fact_id: return f
        return None

    def images(self, model_id, tags=None):
        out = [i for i in IMAGES if i.model_id == model_id]
        if tags: out = [i for i in out if set(tags) & set(i.tags)]
        return out

    def get_image(self, image_id): return next((i for i in IMAGES if i.id == image_id), None)

    def image_bytes(self, image_id): return _png(), "image/png"

    def prices(self, model_id): return [p for p in PRICES if p.model_id == model_id]

    def search(self, query, model_id=None, limit=8):
        self.search_calls.append(query)
        self._trace.append(TraceEntry(step="local_index", request={"query": query, "model_id": model_id},
                                      msg="ok", count=3, ms=1, origin="local_mirror"))
        return [SearchHit(title=SRC, path=PATH, snippet="…", model_id=model_id)]

    def drain_trace(self):
        t, self._trace = self._trace, []
        return t
