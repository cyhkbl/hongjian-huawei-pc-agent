"""Small text helpers shared by the indexer and the store: tag/category rules,
markdown splitting, Chinese bigram tokenizer."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# tags / category
# --------------------------------------------------------------------------
TAG_RULES: list[tuple[str, re.Pattern]] = [
    ("portable", re.compile(r"轻薄|便携|重量|\d\s*g(?![a-zA-Z])|kg|厚度|轻盈|随身|机身|携带|厚\s*\d")),
    ("battery", re.compile(r"电池|续航|Wh|快充|充电|适配器|电量|待机")),
    ("ports", re.compile(r"接口|USB|HDMI|雷电|Thunderbolt|DisplayPort|DP\s?1|耳机|SD卡|Type-?C|扩展坞", re.I)),
    ("display", re.compile(r"屏幕|显示|OLED|分辨率|刷新率|亮度|色域|nits|尼特|护眼|柔光|防窥|屏占比|PWM|色准|对比度")),
    ("ai", re.compile(r"AI|小艺|智能|智慧|大模型", re.I)),
    ("collab", re.compile(r"协同|超级终端|多屏|互联|跨设备|键鼠共享|碰一碰|投屏|应用接续|华为分享|星闪|剪贴板|畅连")),
    ("creative", re.compile(r"创作|设计|剪辑|绘图|色彩|P3|专业|创拍|视频|摄影|修图")),
    ("office", re.compile(r"办公|会议|文档|Office|WPS|演示|商务|职场|文件管理")),
    ("study", re.compile(r"学习|学生|学业|上课|网课|笔记|开学|课堂|校园|考试")),
    ("travel", re.compile(r"差旅|出差|移动|旅行|通勤|外出")),
    ("performance", re.compile(r"性能|处理器|麒麟|酷睿|内存|CPU|GPU|显卡|散热|多任务|锐龙|英特尔|Intel", re.I)),
    ("storage", re.compile(r"存储|SSD|硬盘|固态|TB|NVMe", re.I)),
    ("camera", re.compile(r"摄像头|摄像|拍摄|前置|后置|像素")),
    ("audio", re.compile(r"音频|扬声器|麦克风|喇叭|音质|降噪|声场")),
    ("keyboard", re.compile(r"键盘|触控板|键程|指纹|电源键")),
    ("stylus", re.compile(r"手写笔|M-?Pen|手写|笔尖|触控笔|书写", re.I)),
    ("fold", re.compile(r"折叠|展开|铰链|闭合")),
    ("color", re.compile(r"配色|颜色|原野绿|樱粉金|柔光金|仲夏紫|深空灰|流光金|天际白|幻影黑|典藏")),
    ("os", re.compile(r"鸿蒙|HarmonyOS|Windows|Linux|系统", re.I)),
    ("privacy", re.compile(r"隐私|防窥|数据保护|加密")),
]

CARD_HINTS: list[tuple[str, str]] = [
    ("身份", "identity"), ("屏幕", "display"), ("显示", "display"), ("性能", "performance"),
    ("存储", "performance"), ("便携", "portable"), ("续航", "portable"), ("接口", "portable"),
    ("协同", "ecosystem"), ("兼容", "ecosystem"), ("系统", "ecosystem"), ("适用", "audience"),
    ("人群", "audience"), ("限制", "limit"),
]

_CONNECT = re.compile(r"USB|HDMI|雷电|Thunderbolt|接口|Wi-?Fi|WLAN|蓝牙|DisplayPort|DP\s?1|Type-?C", re.I)
_NOT_CONNECT = re.compile(r"电池|Wh|重量|\d\s*g(?![a-zA-Z])|厚|宽|深|续航")

_CATEGORY_KEYWORDS: list[tuple[str, re.Pattern]] = [
    ("display", re.compile(r"屏幕|显示|OLED|分辨率|刷新率|亮度|色域|nits|尼特|护眼|柔光|防窥")),
    ("connect", _CONNECT),
    ("portable", re.compile(r"重量|厚度|电池|续航|Wh|轻薄|便携|快充|机身")),
    ("performance", re.compile(r"处理器|内存|存储|性能|CPU|GPU|显卡|SSD|麒麟|酷睿")),
    ("ecosystem", re.compile(r"协同|超级终端|系统|HarmonyOS|鸿蒙|兼容|应用|AI|小艺", re.I)),
]


def infer_tags(*texts: str, limit: int = 8) -> list[str]:
    blob = " ".join(t for t in texts if t)
    tags = [name for name, pat in TAG_RULES if pat.search(blob)]
    return tags[:limit]


def infer_category(name: str, text: str, kind: str = "card") -> str:
    if kind in ("unfit", "boundary"):
        return "limit"
    if kind == "fit":
        return "audience"
    for kw, cat in CARD_HINTS:
        if kw in (name or ""):
            if cat == "portable" and _CONNECT.search(text) and not _NOT_CONNECT.search(text):
                return "connect"
            return cat
    for cat, pat in _CATEGORY_KEYWORDS:
        if pat.search(text or ""):
            if cat == "connect" and _NOT_CONNECT.search(text):
                continue
            return cat
    return "other"


# --------------------------------------------------------------------------
# markdown helpers
# --------------------------------------------------------------------------
_URL = re.compile(r"https?://[^\s)>\]`'\"，。；、]+")
_NOISE_LINE = re.compile(r"即将离开|您即将跳转|继续访问|^取消$|^继续$|第三方页面")


def find_urls(text: str) -> list[str]:
    out: list[str] = []
    for u in _URL.findall(text or ""):
        u = u.rstrip(".,;:)")
        if u not in out:
            out.append(u)
    return out


def cut_noise(text: str) -> str:
    """Drop the 'leaving consumer.huawei.com' footer and everything after it."""
    m = re.search(r"即将离开", text)
    return text[:m.start()] if m else text


def split_sections(text: str, level: int) -> list[tuple[str, str]]:
    """Split by markdown headings of exactly ``level`` ('##' -> 2). Returns [(heading, body)];
    text before the first heading gets heading ''."""
    pat = re.compile(rf"^{'#' * level}\s+(.+?)\s*$", re.M)
    out: list[tuple[str, str]] = []
    pos = 0
    head = ""
    for m in pat.finditer(text):
        out.append((head, text[pos:m.start()]))
        head = m.group(1).strip()
        pos = m.end()
    out.append((head, text[pos:]))
    return [(h, b.strip("\n")) for h, b in out if h or b.strip()]


def first_h1(text: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.、)])\s+(.*\S)\s*$")


def bullets(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _BULLET.match(line)
        if m:
            out.append(clean_inline(m.group(1)))
    return out


def clean_inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def first_paragraph(text: str) -> str:
    for para in re.split(r"\n\s*\n", text.strip()):
        p = clean_inline(" ".join(l.strip() for l in para.splitlines() if not l.strip().startswith(("#", ">", "-"))))
        if p:
            return p
    return ""


def doc_date(text: str) -> str:
    m = re.search(r"(?:抓取日期|事实基准日|抓取基准日|基准日)[：:\s]*(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------
# tokenizer / scoring
# --------------------------------------------------------------------------
_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOP = set("的了和与及是在有为也就都把被让对给吗呢吧啊嘛呀请帮我想要写一篇关于")


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()


def tokens(s: str) -> list[str]:
    """Chinese bigrams (+ single chars for 1-char runs) and latin/number words."""
    s = norm(s)
    out: list[str] = []
    for m in re.finditer(r"[\u4e00-\u9fff]+", s):
        run = "".join(ch for ch in m.group(0) if ch not in STOP) or m.group(0)
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    out.extend(_WORD.findall(s))
    return out


def unique(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
