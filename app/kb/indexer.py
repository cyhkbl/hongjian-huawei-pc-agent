"""KB parser: VFS -> ProductModel / Fact / ImageAsset / PriceRecord.

Layout detection is by *content*, not by hard-coded paths:

* a "product dir" holds ``产品事实.md`` / ``卖点与限制.md`` (local zip layout) or only ``article.md``
* a "card dir" holds numbered ``NN-xxx卡.md`` files with a ``## 已确认事实`` section
* any dir (or sub-dir) holding ``图片索引.csv`` contributes images
* ``全部图片联合检索表.csv`` is used to cross-check images
* ``官方价格快照.csv`` provides price records

Whatever is not found is skipped and counted in ``KBIndex.notes``.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.kb.aliases import MODEL_META, MODEL_ORDER, resolve_any, resolve_model, resolve_path
from app.kb.textutil import (
    bullets, clean_inline, cut_noise, doc_date, find_urls, first_h1, infer_category, infer_tags,
    split_sections, unique,
)
from app.kb.vfs import VFS, VEntry, join_path
from app.models import Fact, ImageAsset, PriceRecord, ProductModel

DEFAULT_SNAPSHOT = "2026-10-17"
EXPANDED_MARKER = "<!-- v6-expanded"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
CARD_FILE = re.compile(r"^(\d{1,2})[-_].*\.md$")


@dataclass
class Doc:
    title: str
    path: str
    model_id: str = ""
    text: str = ""


@dataclass
class KBIndex:
    models: list[ProductModel] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    prices: list[PriceRecord] = field(default_factory=list)
    docs: list[Doc] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # skipped / missing parts (human sentences)
    audit: list[str] = field(default_factory=list)      # consistency problems (for scripts/kb_audit.py)
    snapshot_date: str = DEFAULT_SNAPSHOT


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _safe(fn: Callable, *a, default=None):
    try:
        return fn(*a)
    except (FileNotFoundError, OSError, ValueError):
        return default


def read_csv(text: str) -> list[dict]:
    text = text.lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def _norm_key(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def _name_from_h1(h1: str) -> str:
    h1 = re.split(r"\s*[｜|]\s*", h1)[0]
    return re.sub(r"\s*[-–—]\s*(产品事实|卖点与限制)\s*$", "", h1).strip()


class Walk:
    """Discovery result of a bounded directory walk."""

    def __init__(self) -> None:
        self.product_dirs: list[tuple[str, list[str]]] = []   # (path, file names)
        self.card_dirs: list[tuple[str, list[str]]] = []
        self.csv_image: list[str] = []                         # paths of 图片索引.csv
        self.union_csv: Optional[str] = None
        self.price_csv: Optional[str] = None
        self.dirs_seen = 0


def walk_kb(vfs: VFS, roots: list[str], max_depth: int = 5) -> Walk:
    w = Walk()

    def visit(path: str, depth: int) -> None:
        try:
            entries = vfs.list_dir(path)
        except (FileNotFoundError, OSError):
            return
        w.dirs_seen += 1
        files = [e.name for e in entries if not e.is_dir]
        names = set(files)
        if names & {"产品事实.md", "卖点与限制.md", "article.md"}:
            w.product_dirs.append((path, files))
        if any(CARD_FILE.match(f) and "卡" in f for f in files):
            w.card_dirs.append((path, files))
        if "图片索引.csv" in names:
            w.csv_image.append(join_path(path, "图片索引.csv"))
        if "全部图片联合检索表.csv" in names and not w.union_csv:
            w.union_csv = join_path(path, "全部图片联合检索表.csv")
        if "官方价格快照.csv" in names and not w.price_csv:
            w.price_csv = join_path(path, "官方价格快照.csv")
        if depth >= max_depth:
            return
        for e in entries:
            if e.is_dir and e.name.lower() not in {"images", "image", "img", ".git"}:
                visit(join_path(path, e.name), depth + 1)

    for r in roots:
        visit(r, 0)
    return w


# --------------------------------------------------------------------------
# spec parser (产品事实.md)
# --------------------------------------------------------------------------
SPEC_KEYS = {
    "长度", "宽度", "深度", "高度", "厚度", "重量", "尺寸", "类型", "屏占比", "屏幕比例", "分辨率", "刷新率",
    "亮度", "峰值亮度", "典型亮度", "色域", "色准", "色深", "对比度", "可视角度", "触摸屏", "WLAN", "蓝牙",
    "星闪", "NFC", "材料", "容量", "CPU", "GPU", "扬声器", "麦克风",
}
PREFIX_KEYS = {"尺寸", "类型", "材料", "容量"}
JOIN_SECTIONS = {"处理器", "存储", "内存", "显卡", "操作系统", "特色应用", "包装清单"}
SPEC_CATEGORY = {
    "屏幕": "display", "尺寸与重量": "portable", "电池": "portable", "接口": "connect", "无线连接": "connect",
    "处理器": "performance", "存储": "performance", "内存": "performance", "显卡": "performance",
    "操作系统": "identity", "特色应用": "ecosystem",
}
SPEC_TAGS = {
    "屏幕": ["display"], "尺寸与重量": ["portable"], "电池": ["battery"], "接口": ["ports"],
    "无线连接": ["collab"], "处理器": ["performance"], "存储": ["storage"], "内存": ["performance"],
    "显卡": ["performance"], "键盘和触控板": ["keyboard"], "摄像头": ["camera"], "音频": ["audio"],
    "特色应用": ["ai", "collab"],
}
_ZW = re.compile(r"[\u2060\u200b\u200c\u200d\ufeff]")


def parse_spec(text: str) -> tuple[list[dict], list[str]]:
    """-> (items, source_urls). item = {section,label,text,constraints}"""
    text = _ZW.sub("", cut_noise(text))
    urls: list[str] = []
    m = re.search(r"^##\s*来源\s*$(.*?)(?=^##\s)", text, re.M | re.S)
    if m:
        urls = find_urls(m.group(1))
    if not urls:
        urls = find_urls(text.split("官方规格摘录")[0])
    part = text.split("官方规格摘录", 1)[1] if "官方规格摘录" in text else text
    items: list[dict] = []
    for section, body in split_sections(part, 2):
        if not section or section in ("来源", "官方规格摘录"):
            continue
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        sec_items: list[dict] = []
        cur: Optional[dict] = None
        prefix: Optional[str] = None
        for ln in lines:
            if ln.startswith(("*", "＊")):
                note = ln.lstrip("*＊ ").strip()
                if not note:
                    continue
                if note.startswith("实际尺寸") and sec_items:
                    for it in sec_items:
                        it["constraints"].append(note)
                elif sec_items:
                    sec_items[-1]["constraints"].append(note)
                continue
            if ln in SPEC_KEYS:
                cur = {"section": section, "key": ln, "values": [], "constraints": []}
                sec_items.append(cur)
                prefix = None
                continue
            if ln.endswith(("：", ":")) and len(ln) <= 8 and "×" not in ln:
                prefix = ln
                continue
            val = re.sub(r"\s*[*＊]+$", "", ln)
            if prefix:
                val = prefix + val
                prefix = None
            if cur is None:
                if section in JOIN_SECTIONS and sec_items:
                    sec_items[-1]["values"].append(val)
                else:
                    sec_items.append({"section": section, "key": "", "values": [val], "constraints": []})
            else:
                cur["values"].append(val)
        for it in sec_items:
            if not it["values"]:
                continue
            key = it["key"]
            if not key:
                label = section
            elif section == "屏幕" and key in PREFIX_KEYS:
                label = "屏幕" + key
            elif section == "电池" and key in PREFIX_KEYS:
                label = "电池" + key
            elif section == "尺寸与重量" and key in ("长度", "宽度", "深度", "高度", "厚度"):
                label = "机身" + key
            elif key in ("扬声器", "麦克风") and it["values"][0].startswith(key):
                label = section
            else:
                label = key
            value = "；".join(it["values"])
            items.append({"section": section, "label": label, "text": f"{label}：{value}",
                          "constraints": unique(it["constraints"])})
    return items, urls


# --------------------------------------------------------------------------
# cards / selling / article
# --------------------------------------------------------------------------
CARD_TYPE_TAGS = [("屏幕", "display"), ("显示", "display"), ("性能", "performance"), ("存储", "storage"),
                  ("便携", "portable"), ("续航", "battery"), ("接口", "ports"), ("协同", "collab"),
                  ("兼容", "collab")]


def _card_tags(card_name: str, text: str, extra: tuple[str, ...] = ()) -> list[str]:
    tags = list(extra)
    for kw, tg in CARD_TYPE_TAGS:
        if kw in card_name:
            tags.append(tg)
    tags += infer_tags(text)
    return unique(tags)[:8]


def _role(heading: str) -> str:
    h = heading
    if "已确认事实" in h:
        return "confirmed"
    if "限定条件" in h:
        return "constraints"
    if "不适用" in h or "不适合" in h:
        return "unfit"
    if "适用任务" in h or "适合进入" in h:
        return "fit"
    if "待核验" in h or "必须追问" in h:
        return "verify"
    if "来源" in h:
        return "sources"
    if "检索结论" in h:
        return "summary"
    return ""


def parse_card(text: str, model_id: str, path: str, snapshot: str, abbr: str) -> tuple[list[Fact], str]:
    """-> (facts, card display name)"""
    head = text.split(EXPANDED_MARKER, 1)[0]
    h1 = first_h1(head)
    card_name = h1.split("｜", 1)[1].strip() if "｜" in h1 else (h1 or path.rsplit("/", 1)[-1])
    date = doc_date(head) or snapshot
    secs: dict[str, str] = {}
    for h, b in split_sections(head, 2):
        r = _role(h)
        if r:
            secs[r] = b
    urls = find_urls(secs.get("sources", ""))
    cons = bullets(secs.get("constraints", ""))
    facts: list[Fact] = []
    n = 0

    def add(kind: str, category: str, text_: str, constraints: list[str], tags: list[str]) -> None:
        nonlocal n
        n += 1
        facts.append(Fact(
            id=f"{model_id}:{abbr}:{n:02d}", model_id=model_id, kind=kind, category=category, text=text_,
            constraints=constraints, tags=tags, source_title=h1 or card_name, source_path=path,
            source_urls=urls, verified_date=date))

    for b in bullets(secs.get("confirmed", "")):
        add("card", infer_category(card_name, b, "card"), b, list(cons), _card_tags(card_name, b))
    for b in bullets(secs.get("fit", "")):
        add("fit", "audience", b, [], _card_tags(card_name, b))
    for b in bullets(secs.get("unfit", "")):
        add("unfit", "limit", b, [], _card_tags(card_name, b))
    for b in bullets(secs.get("verify", "")):
        add("boundary", "limit", "待核验：" + b, [], _card_tags(card_name, b))
    return facts, card_name


def parse_selling(text: str, model_id: str, path: str, snapshot: str, urls: list[str],
                  seen_norm: set[str]) -> list[Fact]:
    h1 = first_h1(text)
    date = doc_date(text) or snapshot
    facts: list[Fact] = []
    n = 0

    def add(kind: str, category: str, text_: str, cons: list[str], tags: list[str]) -> None:
        nonlocal n
        n += 1
        facts.append(Fact(id=f"{model_id}:sell:{n:02d}", model_id=model_id, kind=kind, category=category,
                          text=text_, constraints=cons, tags=tags, source_title=h1, source_path=path,
                          source_urls=urls, verified_date=date))

    for h, body in split_sections(text, 2):
        if "一句话定位" in h:
            line = clean_inline(body.split("\n\n")[0])
            if line:
                add("selling", "audience", line, [], _card_tags("", line))
    angle_secs = [(h, b) for h2, b2 in split_sections(text, 2) for h, b in split_sections(b2, 3) if h]
    for h, body in angle_secs:
        name = re.sub(r"^\d+[.、)]\s*", "", h)
        parts = re.split(r"\*\*(可用结论|支撑事实|表达边界)\*\*", body)
        blocks: dict[str, str] = {}
        for i in range(1, len(parts) - 1, 2):
            blocks[parts[i]] = parts[i + 1]
        concl = clean_inline(blocks.get("可用结论", "").strip())
        bounds = bullets(blocks.get("表达边界", ""))
        cat = infer_category(name, concl, "selling")
        if concl:
            add("selling", cat, concl, list(bounds), _card_tags(name, concl))
        for b in bullets(blocks.get("支撑事实", "")):
            k = _norm_key(b)
            if k in seen_norm:
                continue
            seen_norm.add(k)
            add("selling", infer_category(name, b, "selling"), b, list(bounds), _card_tags(name, b))
        for b in bounds:
            add("boundary", "limit", b, [], _card_tags(name, b))
    return facts


_BOUNDARY_H = re.compile(r"限制|限定|边界|注意|不适用|不建议|待核验|必须|须知|免责")
_FIT_H = re.compile(r"适用|适合|人群")
_SPEC_H = re.compile(r"规格|参数")
_SKIP_H = re.compile(r"来源|链接|URL|索引|目录|更新")


def parse_article(text: str, model_id: str, official: str, path: str, snapshot: str,
                  urls: list[str], max_facts: int = 150) -> list[Fact]:
    """Generic parser: split by headings; bullets / table rows / sentences become cited facts."""
    text = _ZW.sub("", cut_noise(text))
    date = doc_date(text) or snapshot
    facts: list[Fact] = []
    heading = ""
    chunks: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if m:
            heading = m.group(2).strip()
            chunks.append((heading, []))
        else:
            chunks[-1][1].append(line)
    n = 0
    seen: set[str] = set()
    all_urls = urls or find_urls(text)[:3]
    for heading, lines in chunks:
        if _SKIP_H.search(heading):
            continue
        kind = "boundary" if _BOUNDARY_H.search(heading) else "fit" if _FIT_H.search(heading) else "card"
        sentences: list[str] = []
        para: list[str] = []

        def flush() -> None:
            if para:
                blob = clean_inline(" ".join(para))
                for s in re.split(r"(?<=[。；;！？!?])", blob):
                    s = s.strip()
                    if s:
                        sentences.append(s)
                para.clear()

        for ln in lines:
            s = ln.strip()
            if not s or s.startswith((">", "<!--", "---", "```")):
                flush()
                continue
            if s.startswith("|"):
                flush()
                cells = [c.strip() for c in s.strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    continue
                cells = [clean_inline(c) for c in cells if c]
                if len(cells) >= 2 and cells[0] not in ("项目", "参数", "规格", "名称"):
                    sentences.append(f"{cells[0]}：{'；'.join(cells[1:])}")
                continue
            mb = re.match(r"^\s*(?:[-*+•]|\d+[.、)])\s+(.*\S)", ln)
            if mb:
                flush()
                sentences.append(clean_inline(mb.group(1)))
            else:
                para.append(s)
        flush()
        for s in sentences:
            s = s.strip()
            if len(s) < 6 or len(s) > 220 or s.startswith("http"):
                continue
            k = _norm_key(s)
            if k in seen:
                continue
            seen.add(k)
            n += 1
            if n > max_facts:
                return facts
            k_kind = kind
            if kind == "card" and _SPEC_H.search(heading) and "：" in s:
                k_kind = "spec"
            facts.append(Fact(
                id=f"{model_id}:art:{n:02d}", model_id=model_id, kind=k_kind,
                category="limit" if k_kind == "boundary" else "audience" if k_kind == "fit"
                else infer_category(heading, s, k_kind),
                text=s, constraints=[], tags=_card_tags(heading, s),
                source_title=f"{official}｜{heading}" if heading else official, source_path=path,
                source_urls=all_urls, verified_date=date))
    return facts


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------
IMG_TAG_RULES: list[tuple[str, re.Pattern]] = [
    ("appearance", re.compile(r"外观|主视觉|机身|侧面|正面|开合|A面|俯视|造型|设计|轻薄|KV|展示", re.I)),
    ("display", re.compile(r"屏幕|OLED|显示|护眼|柔光|触控|全面屏|色域|防窥")),
    ("ports", re.compile(r"接口")),
    ("performance", re.compile(r"性能|处理器|散热|核心卖点")),
    ("collab", re.compile(r"协同|超级终端|手机|平板|多设备|互联|AI|智慧|空间")),
    ("scene", re.compile(r"场景|创作|办公|影音|续航|漫步|人物|创拍|街上|学习|会议|快充")),
    ("color", re.compile(r"配色|颜色|原野绿|樱粉金|柔光金|仲夏紫|深空灰|流光金|天际白|幻影黑")),
    ("detail", re.compile(r"细节|特写|键盘|铰链")),
]
COLOR_WORDS = ["原野绿", "樱粉金", "柔光金", "仲夏紫", "深空灰", "流光金", "天际白", "幻影黑", "星河蓝",
               "云锦白", "墨玉青", "皓月银", "曜石黑", "冰霜银", "翡冷翠", "雅黑", "皓月白", "香槟金"]


def image_tags(caption: str, filename: str) -> list[str]:
    sem = filename.split("_")[2] if filename.count("_") >= 3 else ""
    blob = f"{caption} {sem}"
    return [t for t, p in IMG_TAG_RULES if p.search(blob)]


def image_color(caption: str) -> str:
    for c in COLOR_WORDS:
        if c in caption:
            return c
    return ""


def _fallback_caption(filename: str, short: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    parts = stem.split("_")
    sem = parts[2] if len(parts) >= 4 else (parts[1] if len(parts) >= 3 else stem)
    return f"{short} {sem}".strip()


def _first(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k, "")
        if v:
            return v
    return ""


def _int(s: str) -> int:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# prices
# --------------------------------------------------------------------------
def _amount(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else None


def parse_prices(text: str) -> list[PriceRecord]:
    out: list[PriceRecord] = []
    for i, r in enumerate(read_csv(text), 1):
        name = _first(r, "规范产品名称", "原始产品名称", "产品名称")
        if not name:
            continue
        mid = resolve_any(name, _first(r, "原始产品名称"))
        out.append(PriceRecord(
            record_id=_first(r, "记录ID") or f"PRICE-{i:04d}", model_id=mid, product_name=name,
            category=_first(r, "分类"), spec=_first(r, "精确款式"),
            price_type=_first(r, "价格类型") or "未标注",
            amount=_amount(r.get("页面金额（元）", "")), ref_amount=_amount(r.get("参考或划线金额（元）", "")),
            conditions=_first(r, "条件摘要"), stock=_first(r, "库存状态"), verified_at=_first(r, "核验时间"),
            url=_first(r, "官方URL"), status=_first(r, "核验状态")))
    return out


def citable_price(p: PriceRecord) -> bool:
    """A price record that may be quoted as a current mall price (not just an official 起价)."""
    return p.amount is not None and "参考起价" not in p.price_type


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------
def _find_roots(vfs: VFS) -> list[str]:
    try:
        top = vfs.list_dir("")
    except (FileNotFoundError, OSError):
        return [""]
    roots = [e.name for e in top if e.is_dir and "产品参数" in e.name]
    return roots or [""]


def build_index(vfs: VFS) -> KBIndex:
    idx = KBIndex()
    w = walk_kb(vfs, _find_roots(vfs))
    idx.notes.append(f"扫描了 {w.dirs_seen} 个目录")

    # ---- product dirs -> model info + facts -------------------------------
    info: dict[str, dict] = {}
    snaps: list[str] = []

    def slot(mid: str) -> dict:
        return info.setdefault(mid, dict(name="", os_label="", urls=[], dir="", cards=[], spec=0, sell=0, art=0,
                                         images=0, price=0))

    unmatched_dirs = 0
    pending_products: list[tuple[str, str, list[str]]] = []
    for path, files in w.product_dirs:
        dirname = path.rsplit("/", 1)[-1]
        title = ""
        for f in ("产品事实.md", "卖点与限制.md", "article.md"):
            if f in files:
                t = _safe(vfs.read_text, join_path(path, f), default="")
                title = _name_from_h1(first_h1(t)) if t else ""
                if title:
                    break
        mid = resolve_any(title, dirname)
        if not mid:
            unmatched_dirs += 1
            continue
        s = slot(mid)
        if s["dir"]:
            idx.notes.append(f"型号目录重复，已忽略「{dirname}」")
            continue
        s["dir"] = path
        s["name"] = title or s["name"]
        pending_products.append((mid, path, files))
    if unmatched_dirs:
        idx.notes.append(f"{unmatched_dirs} 个目录不属于 10 个重点型号，已跳过")

    # ---- cards -------------------------------------------------------------
    card_facts: dict[str, list[Fact]] = {}
    for path, files in w.card_dirs:
        cards = sorted((f for f in files if CARD_FILE.match(f) and "卡" in f),
                       key=lambda f: int(CARD_FILE.match(f).group(1)))
        mid: Optional[str] = None
        for f in cards:
            t = _safe(vfs.read_text, join_path(path, f), default="")
            if not t:
                continue
            h1 = first_h1(t)
            mid = mid or resolve_any(h1.split("｜")[0], path.rsplit("/", 1)[-1])
            if not mid:
                break
            if "已确认事实" not in t:
                continue
            m = CARD_FILE.match(f)
            abbr = f"card{int(m.group(1)):02d}"
            fp = join_path(path, f)
            facts, cname = parse_card(t, mid, fp, DEFAULT_SNAPSHOT, abbr)
            d = doc_date(t)
            if d:
                snaps.append(d)
            card_facts.setdefault(mid, []).extend(facts)
            s = slot(mid)
            s["cards"].append(f)
            if not s["name"]:
                s["name"] = _name_from_h1(h1)
            s["urls"] = unique(s["urls"] + [u for u in find_urls(t.split("## 来源入口")[-1]) if "huawei.com" in u])
            idx.docs.append(Doc(title=h1 or cname, path=fp, model_id=mid,
                                text=t.split(EXPANDED_MARKER, 1)[0][:1500]))
    # ---- product docs ------------------------------------------------------
    for mid, path, files in pending_products:
        s = slot(mid)
        spec_urls: list[str] = []
        csv_urls: list[str] = []
        if "来源清单.csv" in files:
            for r in read_csv(_safe(vfs.read_text, join_path(path, "来源清单.csv"), default="")):
                u = _first(r, "URL", "url", "链接")
                if u:
                    csv_urls.append(u)
        if "产品事实.md" in files:
            fp = join_path(path, "产品事实.md")
            t = _safe(vfs.read_text, fp, default="")
            if t:
                h1 = first_h1(t)
                d = doc_date(t) or DEFAULT_SNAPSHOT
                snaps.append(d)
                items, spec_urls = parse_spec(t)
                for i, it in enumerate(items, 1):
                    txt = it["text"]
                    tags = unique(SPEC_TAGS.get(it["section"], []) + infer_tags(txt))[:8]
                    cat = SPEC_CATEGORY.get(it["section"]) or infer_category("", txt, "spec")
                    if it["section"] == "接口":
                        cat = "connect"
                    idx.facts.append(Fact(
                        id=f"{mid}:spec:{i:02d}", model_id=mid, kind="spec", category=cat, text=txt,
                        constraints=it["constraints"], tags=tags, source_title=h1 or fp, source_path=fp,
                        source_urls=spec_urls, verified_date=d))
                s["spec"] = len(items)
                if items:
                    for it in items:
                        if it["section"] == "操作系统":
                            s["os_label"] = it["text"].split("：", 1)[-1].split("；")[0]
                            break
                s["name"] = _name_from_h1(h1) or s["name"]
                idx.docs.append(Doc(title=h1, path=fp, model_id=mid, text=t[:1500]))
        elif "article.md" not in files:
            idx.notes.append(f"{s['name'] or path.rsplit('/', 1)[-1]}：未找到规格文档（产品事实.md）")
        urls_for_sell = spec_urls or csv_urls
        seen_norm = {_norm_key(f.text) for f in card_facts.get(mid, [])}
        if "卖点与限制.md" in files:
            fp = join_path(path, "卖点与限制.md")
            t = _safe(vfs.read_text, fp, default="")
            if t:
                sf = parse_selling(t, mid, fp, DEFAULT_SNAPSHOT, urls_for_sell, seen_norm)
                idx.facts.extend(sf)
                s["sell"] = len(sf)
                idx.docs.append(Doc(title=first_h1(t), path=fp, model_id=mid, text=t[:1500]))
        if "article.md" in files:
            fp = join_path(path, "article.md")
            t = _safe(vfs.read_text, fp, default="")
            if t:
                h1 = first_h1(t)
                official = _name_from_h1(h1) or s["name"] or path.rsplit("/", 1)[-1]
                s["name"] = s["name"] or official
                af = parse_article(t, mid, official, fp, DEFAULT_SNAPSHOT, urls_for_sell)
                idx.facts.extend(af)
                s["art"] = len(af)
                snaps.append(doc_date(t) or DEFAULT_SNAPSHOT)
                if not s["os_label"]:
                    mo = re.search(r"HarmonyOS\s*\d+(?:\.\d+)?|Windows\s*\d+[^，。；\n]{0,12}", t)
                    s["os_label"] = mo.group(0).strip() if mo else ""
                idx.docs.append(Doc(title=h1 or official, path=fp, model_id=mid, text=t[:1500]))
        if not (s["spec"] or s["sell"] or s["art"]) and not card_facts.get(mid):
            idx.notes.append(f"{s['name']}：目录下没有可解析的事实内容")
        s["urls"] = unique([u for u in csv_urls + spec_urls + s["urls"] if "huawei.com" in u])
        if not s["cards"] and not s["art"]:
            idx.notes.append(f"{s['name']}：未找到型号检索卡")
    for mid, fl in card_facts.items():
        idx.facts.extend(fl)

    # snapshot date: the most common doc date
    if snaps:
        idx.snapshot_date = max(set(snaps), key=lambda d: (snaps.count(d), d))

    # ---- models -----------------------------------------------------------
    for mid in MODEL_ORDER:
        s = info.get(mid)
        if not s or not (s["spec"] or s["sell"] or s["art"] or s["cards"]):
            continue
        meta = MODEL_META[mid]
        os_label = s["os_label"] or ("HarmonyOS" if meta["os"] == "harmonyos" else "Windows 11")
        idx.models.append(ProductModel(
            model_id=mid, name=s["name"] or meta["short"], short_name=meta["short"], series=meta["series"],
            os_family=meta["os"], os_label=os_label, aliases=list(meta["aliases"]),
            confusable_with=list(meta["confusable"]), official_urls=s["urls"],
            snapshot_date=idx.snapshot_date))
    known = {m.model_id for m in idx.models}
    for f in idx.facts:
        f.verified_date = f.verified_date or idx.snapshot_date
    idx.facts.sort(key=lambda f: MODEL_ORDER.index(f.model_id) if f.model_id in MODEL_ORDER else 99)
    missing = [m for m in MODEL_ORDER if m not in known]
    if missing:
        idx.notes.append("未在知识库中找到型号：" + "、".join(MODEL_META[m]["short"] for m in missing))

    # ---- images -----------------------------------------------------------
    shorts = {m.model_id: m.short_name for m in idx.models}
    union: list[dict] = []
    if w.union_csv:
        union = read_csv(_safe(vfs.read_text, w.union_csv, default=""))
    union_by_name: dict[str, dict] = {r.get("文件名", ""): r for r in union if r.get("文件名")}
    seen_ids: set[str] = set()
    skipped_images: list[str] = []
    for csv_path in w.csv_image:
        cdir = csv_path.rsplit("/", 1)[0] if "/" in csv_path else ""
        mid = resolve_path(cdir)
        if not mid:
            # directory named differently: use the model of the owning product dir
            for m2, p2, _f in pending_products:
                if cdir == p2 or cdir.startswith(p2 + "/"):
                    mid = m2
                    break
        if not mid or mid not in known:
            if mid is None:
                idx.notes.append(f"图片索引「{cdir.rsplit('/', 1)[-1]}」无法归属到重点型号，已跳过")
            continue
        is_mall_dir = "商城" in cdir
        for r in read_csv(_safe(vfs.read_text, csv_path, default="")):
            fn = r.get("文件名", "")
            if not fn:
                continue
            kb_path = ""
            for cand in (join_path(cdir, "images", fn), join_path(cdir, fn)):
                if _safe(vfs.exists, cand, default=False):
                    kb_path = cand
                    break
            if not kb_path:
                skipped_images.append(f"{shorts.get(mid, mid)}/{fn}：索引有记录但没有可读文件")
                continue
            ur = union_by_name.get(fn, {})
            caption = _first(r, "官网图片说明", "画面说明") or ur.get("画面说明", "") \
                or _fallback_caption(fn, shorts.get(mid, mid))
            src = _first(r, "原始图片URL") or ur.get("原始图片URL", "")
            page = _first(r, "来源页面", "商品页URL", "页面来源") or ur.get("页面来源", "")
            usage = _first(r, "建议用途", "使用提示")
            kind = "mall" if (is_mall_dir or fn.startswith("vmall") or "vmall" in page) else "official"
            if kind == "mall" and not usage:
                usage = "商城款式图，使用前核对具体 SKU、配色与活动状态"
            iid = fn if fn not in seen_ids else f"{mid}_{fn}"
            seen_ids.add(iid)
            if not src or not page:
                idx.audit.append(f"图片 {fn} 缺少来源 URL 或页面 URL")
            # cross-check with the CSV's own model column
            col_model = resolve_any(_first(r, "产品型号"))
            if col_model and col_model != mid:
                idx.audit.append(f"图片 {fn}：索引产品型号为 {col_model}，目录判定为 {mid}")
            idx.images.append(ImageAsset(
                id=iid, model_id=mid, caption=caption, kind=kind,
                tags=image_tags(caption, fn), color=image_color(caption), width=_int(r.get("宽度", "")),
                height=_int(r.get("高度", "")), source_url=src, page_url=page, kb_path=kb_path,
                usage_note=usage))
    for m in idx.images:
        pass
    idx.notes.extend(f"跳过图片 {x}" for x in skipped_images[:5])
    if len(skipped_images) > 5:
        idx.notes.append(f"另有 {len(skipped_images) - 5} 张图片因文件缺失被跳过")
    idx.audit.extend(f"跳过图片 {x}" for x in skipped_images)

    # cross-validate with union table
    by_id = {i.id: i for i in idx.images}
    for fn, r in union_by_name.items():
        local_dir = r.get("本地目录", "")
        umid = resolve_any(r.get("产品型号", "")) or resolve_path(local_dir)
        a = by_id.get(fn)
        if a is None:
            if umid:
                idx.audit.append(f"联合检索表有图片 {fn}（{umid}），但图片索引未收录或文件缺失")
            else:
                idx.audit.append(f"联合检索表图片 {fn} 无法判定型号（目录 {local_dir.rsplit('/', 1)[-1]}），未生成 ImageAsset")
        elif umid and a.model_id != umid:
            idx.audit.append(f"图片 {fn}：联合检索表型号 {umid} ≠ 索引型号 {a.model_id}")
    for a in idx.images:
        if union_by_name and a.id not in union_by_name:
            idx.audit.append(f"图片 {a.id} 不在联合检索表中")

    # ---- prices ------------------------------------------------------------
    if w.price_csv:
        idx.prices = parse_prices(_safe(vfs.read_text, w.price_csv, default=""))
    else:
        idx.notes.append("未找到官方价格快照，价格记录为空")
    priced = {p.model_id for p in idx.prices if p.model_id and citable_price(p)}
    for m in idx.models:
        m.has_public_price = m.model_id in priced

    # ---- bookkeeping -----------------------------------------------------
    idx.facts = [f for f in idx.facts if f.model_id in known]
    return idx
