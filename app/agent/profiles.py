"""8 场景 × 4 平台的策略数据 + 型号适配。

这里只有“怎么写”的知识（切入点、卖点偏好、结构、语气、文案蓝本），没有任何产品事实。
产品事实一律来自 KB 的 Fact；本文件里的句子要么是场景描写（明示假设、不含数字），
要么是行动建议，不构成产品断言。

确定性：所有“随机”选择都走 pick()，同输入同输出。
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional, Sequence

from app.models import Fact

# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
SCENARIO_ORDER = [
    "back_to_school", "office", "creator", "home_upgrade",
    "enterprise_procurement", "store_visit", "new_launch", "festival",
]
PLATFORM_ORDER = ["wechat_mp", "xiaohongshu", "moments", "poster"]
DEFAULT_SCENARIO = "office"
DEFAULT_PLATFORM = "wechat_mp"


def pick(seq: Sequence, *keys: str):
    """确定性“随机”：同样的 keys 永远选同一项。"""
    if not seq:
        raise ValueError("pick() on empty sequence")
    h = hashlib.md5("|".join(str(k) for k in keys).encode("utf-8")).hexdigest()
    return seq[int(h, 16) % len(seq)]


def pick_index(n: int, *keys: str) -> int:
    h = hashlib.md5("|".join(str(k) for k in keys).encode("utf-8")).hexdigest()
    return int(h, 16) % max(n, 1)


def sub(template: str, **tokens: str) -> str:
    """只替换 {m} {p} 这类简单占位，避免 str.format 与中文大括号冲突。"""
    out = template
    for k, v in tokens.items():
        out = out.replace("{" + k + "}", v)
    return out


# --------------------------------------------------------------------------
# 卖点标签体系
# --------------------------------------------------------------------------
TAG_LABEL = {
    "portable": "轻薄便携", "battery": "续航与充电", "display": "屏幕", "performance": "性能与存储",
    "ports": "接口与扩展", "ai": "AI 功能", "collab": "多设备协同", "creative": "创作能力",
    "office": "办公效率", "study": "学习场景", "travel": "出行", "security": "数据与安全",
    "manage": "统一管理", "stylus": "手写与触控", "aftersales": "服务与保障",
    "keyboard": "键盘输入", "audio": "会议音视频",
}

# 事实类别 → 隐含标签（KB 的 tags 缺失时兜底）
CATEGORY_TAGS = {
    "display": ["display"], "performance": ["performance"], "portable": ["portable"],
    "connect": ["ports"], "ecosystem": ["collab"], "audience": [], "identity": [], "limit": [], "other": [],
}

# 文本关键词 → 标签（让策略对 KB 打标质量不敏感）
KEYWORD_TAGS: list[tuple[str, str]] = [
    (r"续航|电池|\d\s*Wh|充电|快充|电源适配", "battery"),
    (r"接口|USB|HDMI|雷电|Thunderbolt|Type-?C|耳机|音频口|扩展坞|转接|DisplayPort", "ports"),
    (r"重量|\d\s*kg|厚度|轻薄|便携|机身|折叠", "portable"),
    (r"屏幕|OLED|nits|分辨率|色域|P3|sRGB|刷新率|亮度|屏占比|柔光|PPI|触控屏", "display"),
    (r"处理器|内存|存储|SSD|\d\s*GB|散热|显卡|性能|麒麟|酷睿|锐龙|多核|热设计", "performance"),
    (r"(?<![A-Za-z])AI(?![A-Za-z])|小艺|智能体|大模型", "ai"),
    (r"协同|多屏|互传|碰一碰|超级终端|同一华为账号|星闪|投屏|全场景|华为账号", "collab"),
    (r"触控笔|手写|M-Pen|压感|10 点触控", "stylus"),
    (r"摄像头|麦克风|扬声器|视频会议|通话|降噪", "audio"),
    (r"键盘|键程|键帽", "keyboard"),
    (r"安全|加密|指纹|防窥|隐私", "security"),
    (r"统一管理|运维|企业版|批量部署", "manage"),
    (r"售后|保修|上门", "aftersales"),
    (r"创作|剪辑|绘图|设计|修图|调色|色彩|P3", "creative"),
    (r"办公|文档|表格|协作", "office"),
    (r"学习|学生|网课|论文|笔记|教师", "study"),
    (r"出差|差旅|移动办公|外出", "travel"),
]

# KB 标签词表 → 我们的标签
KB_TAG_ALIAS = {"storage": "performance", "privacy": "security", "camera": "audio", "fold": "portable"}

# 用户口头的“主卖点” → 标签
USER_POINT_KEYWORDS: list[tuple[str, str]] = [
    (r"续航|电池|充电|耐用", "battery"),
    (r"屏幕|显示|OLED|屏", "display"),
    (r"接口|扩展|拓展|USB|HDMI|转接", "ports"),
    (r"轻|薄|重量|便携|携带|好带", "portable"),
    (r"性能|处理器|内存|存储|散热|流畅|速度", "performance"),
    (r"AI|小艺|智能", "ai"),
    (r"协同|多屏|互传|生态|联动", "collab"),
    (r"手写|触控|笔", "stylus"),
    (r"安全|加密|隐私", "security"),
    (r"管理|运维", "manage"),
    (r"创作|剪辑|绘图|设计|修图", "creative"),
    (r"办公|效率", "office"),
    (r"会议|音频|摄像头|麦克风|扬声器", "audio"),
    (r"键盘|打字", "keyboard"),
    (r"售后|服务|保修", "aftersales"),
    (r"学习|学生|网课", "study"),
]

# 卖点标签 → 优先匹配的图片标签
TAG_IMG = {
    "display": ["display"], "portable": ["appearance"], "battery": ["appearance", "detail"],
    "ports": ["ports"], "performance": ["performance", "detail"], "ai": ["scene", "collab"],
    "collab": ["collab", "scene"], "creative": ["display", "scene"], "office": ["scene"],
    "study": ["scene"], "travel": ["scene", "appearance"], "stylus": ["display", "detail"],
    "keyboard": ["detail"], "audio": ["detail", "scene"], "security": ["detail"],
    "manage": ["ports", "detail"], "aftersales": ["scene"],
}

# 事实 kind 在选句时的优先级
KIND_RANK = {"card": 1.0, "selling": 0.9, "spec": 0.7, "fit": 0.7, "faq": 0.5}
LIMIT_KINDS = ("unfit", "boundary")


def tag_for_user_point(text: str) -> Optional[str]:
    for pat, tag in USER_POINT_KEYWORDS:
        if re.search(pat, text or "", re.I):
            return tag
    return None


def _norm_kb_tags(f: Fact) -> set[str]:
    out = set()
    for t in (f.tags or []):
        t = KB_TAG_ALIAS.get(t, t)
        if t in TAG_LABEL or t in ("appearance", "scene"):
            out.add(t)
    return out


def fact_tags(f: Fact) -> set[str]:
    """一条事实的标签：文本关键词优先（更精确）；没有命中时才用 KB 打标/类别兜底。
    KB 的卡片级标签是整张卡共享的，直接用会让“续航”卖点挂上尺寸句，所以不作首选。"""
    text = f.text or ""
    tags = {tag for pat, tag in KEYWORD_TAGS if re.search(pat, text, re.I)}
    if f.kind == "spec" and ("：" in text or ":" in text):
        key = re.split(r"[：:]", text, maxsplit=1)[0]
        tags = {tag for pat, tag in KEYWORD_TAGS if re.search(pat, key, re.I)} or tags
    if not tags:
        tags = _norm_kb_tags(f) or set(CATEGORY_TAGS.get(f.category, []))
    return tags


strong_tags = fact_tags


# --------------------------------------------------------------------------
# 平台
# --------------------------------------------------------------------------
PLATFORMS: dict[str, dict] = {
    "wechat_mp": dict(
        label="公众号",
        length="1200-1800字（短版约 700-1000 字）",
        length_chars=(900, 2400), short_chars=(500, 1200),
        tone="叙事型、克制、有条理，像一位懂行的朋友把事情讲清楚；允许用“设想”“如果你”明示假设，不写亲身体验",
        title_style="一个矛盾或一个结果 + 具体场景，20-30 字，不叠感叹号、不用空泛形容词",
        title_max=32, titles_min=3,
        img_range=(2, 4), max_points=3,
        cta_style="文末给一个单一动作：先去官方页面核对，再决定是否预约体验",
        hashtag_rule="公众号不加话题标签；文末以一句话给出核对入口",
        hashtag_range=(0, 0),
        structure_note="标题备选 → 导语 → 场景切入 → 按卖点分节（每节：先讲用户动作，再出现功能）→ 诚实的限制 → 结尾行动",
    ),
    "xiaohongshu": dict(
        label="小红书",
        length="400-700字（短版约 250-400 字）",
        length_chars=(250, 900), short_chars=(150, 500),
        tone="口语、短段、贴近生活，一段只讲一个意思；不写亲身体验，用“设想”“如果你”",
        title_style="口语化，不超过 24 字，抛出一个具体场景或问题，不堆叠感叹号",
        title_max=24, titles_min=3,
        img_range=(3, 6), max_points=3,
        cta_style="留一个评论区问题，引导收藏和提问",
        hashtag_rule="4-6 个话题标签：场景 + 型号 + 人群，不蹭无关热点",
        hashtag_range=(4, 6),
        structure_note="首句钩子 → 场景 → 每个卖点一小段（动作在前）→ 一条限制 → 核对清单 → 评论区问题",
    ),
    "moments": dict(
        label="门店朋友圈",
        length="90-180字",
        length_chars=(60, 240), short_chars=(60, 160),
        tone="熟人口吻、低打扰，第一句点出人群和任务，只讲一个核心卖点",
        title_style="无标题，首句即点题",
        title_max=0, titles_min=1,
        img_range=(1, 3), max_points=1,
        cta_style="邀请私聊，请对方发来用途、软件和预算",
        hashtag_rule="不加话题标签，不堆表情",
        hashtag_range=(0, 0),
        structure_note="一句话点人群与任务 → 一个核心卖点 → 一句限制 → 一个行动入口",
    ),
    "poster": dict(
        label="门店海报",
        length="主标题 12-22 字；每个卖点 40-90 字；脚注一行",
        length_chars=(80, 520), short_chars=(80, 400),
        tone="短句、陈述句、一屏一个结论，条件写在同屏脚注",
        title_style="主标题 12-22 字，副标题一句话，不放价格",
        title_max=24, titles_min=3,
        img_range=(1, 1), max_points=3,
        cta_style="到店动作 + 咨询入口，一句话",
        hashtag_rule="海报不加话题标签",
        hashtag_range=(0, 0),
        structure_note="主标题 → 副标题 → 至多三个卖点 → 活动/脚注 → 行动",
    ),
}

SECTION_LABEL = {
    "wechat_mp": {"intro": "标题与导语", "scene": "场景切入", "limit": "诚实的限制",
                  "price": "价格说明（有出处才写）", "checklist": "核对清单", "cta": "结尾行动"},
    "xiaohongshu": {"hook": "首句钩子", "scene": "场景", "limit": "一条限制",
                    "price": "价格说明（有出处才写）", "checklist": "核对清单", "cta": "评论区问题"},
    "moments": {"hook": "点题", "limit": "一句限制", "price": "价格一句话（有出处才写）", "cta": "行动入口"},
    "poster": {"headline": "主标题与副标题", "limit": "脚注", "price": "价格脚注（有出处才写）", "cta": "到店行动"},
}

BASE_SECTIONS = {
    "wechat_mp": ["intro", "scene", "p1", "p2", "p3", "limit", "price", "checklist", "cta"],
    "xiaohongshu": ["hook", "scene", "p1", "p2", "p3", "limit", "price", "checklist", "cta"],
    "moments": ["hook", "p1", "limit", "price", "cta"],
    "poster": ["headline", "p1", "p2", "p3", "limit", "price", "cta"],
}

# 各平台默认“不带”的节；场景/长度/用户指令再增减
DEFAULT_OFF = {
    "wechat_mp": {"price", "checklist"},
    "xiaohongshu": {"price"},
    "moments": {"price"},
    "poster": {"price"},
}


def resolve_sections(platform: str, scenario: str, n_points: int, want_price: bool,
                     length_hint: str = "", extras: Iterable[str] = ()) -> list[str]:
    """平台结构 × 场景 × 长度 × 用户指令 → 最终要写的节（有序 key 列表）。"""
    sc = SCENARIOS.get(scenario) or SCENARIOS[DEFAULT_SCENARIO]
    keys = list(BASE_SECTIONS[platform])
    off = set(DEFAULT_OFF[platform])
    # 场景改变结构
    for k in sc.get("sections_on", {}).get(platform, []):
        off.discard(k)
    for k in sc.get("sections_off", {}).get(platform, []):
        off.add(k)
    if want_price:
        off.discard("price")
    else:
        off.add("price")
    if length_hint == "短":
        off.update({"p3", "checklist"})
        if platform == "wechat_mp":
            off.add("p3")
    elif length_hint == "长":
        if platform in ("wechat_mp", "xiaohongshu"):
            off.discard("checklist")
    for e in extras or []:
        if e.startswith("drop:"):
            off.add(e[5:])
        elif e.startswith("add:"):
            off.discard(e[4:])
    out = []
    for k in keys:
        if k in off:
            continue
        if k[0] == "p" and k[1:].isdigit() and int(k[1:]) > n_points:
            continue
        out.append(k)
    # 至少保留一个卖点节（否则稿件没有内容）
    if n_points >= 1 and "p1" not in out:
        out.insert(1 if len(out) > 1 else 0, "p1")
    return out


# --------------------------------------------------------------------------
# 型号适配（策略判断，不是产品事实）
# --------------------------------------------------------------------------
MODEL_FIT: dict[str, dict] = {
    "mb14-hm": dict(
        bonus={"ports": 0.2, "portable": 0.15, "office": 0.15, "study": 0.1, "display": 0.1},
        good=["office", "back_to_school", "home_upgrade"],
        careful={"creator": "专业创作软件在鸿蒙电脑上的支持范围需先核对"},
        note="鸿蒙电脑路线的 14 英寸级机型，KB 的定位是“重视 3:2 OLED 触控屏和较丰富传统接口的移动办公者”"),
    "pro-hm": dict(
        bonus={"display": 0.25, "creative": 0.2, "performance": 0.15, "ai": 0.1, "collab": 0.1},
        good=["creator", "office", "new_launch"],
        careful={"enterprise_procurement": "批量采购的服务与价格要走官方询价，不在稿件里承诺"},
        note="鸿蒙电脑的 Pro 路线，屏幕与性能是主要讲点"),
    "pros-hm": dict(
        bonus={"display": 0.2, "creative": 0.15, "portable": 0.15, "ai": 0.15, "collab": 0.1},
        good=["office", "creator", "new_launch", "festival"],
        careful={},
        note="鸿蒙电脑的 Pro S 路线，屏幕、便携与 AI 能力并重"),
    "fold": dict(
        bonus={"creative": 0.3, "display": 0.3, "portable": 0.25, "office": 0.2, "stylus": 0.15},
        good=["creator", "office", "new_launch", "festival"],
        careful={"back_to_school": "折叠形态与价位未必贴合学生预算，需提醒读者先核对预算与课程软件",
                 "home_upgrade": "折叠形态需要先确认家里人的使用习惯"},
        note="折叠形态，更适合创作、商务和愿意为形态买单的读者"),
    "mb14-ultra": dict(
        bonus={"performance": 0.2, "ports": 0.2, "office": 0.2, "manage": 0.15},
        good=["office", "enterprise_procurement", "home_upgrade"],
        careful={"new_launch": "该机型不是当前首发机型，写新品首发需以 KB 的发布时间为准"},
        note="Windows 路线，办公与软件兼容是主要讲点"),
    "d14": dict(
        bonus={"study": 0.3, "office": 0.25, "ports": 0.2, "battery": 0.1, "portable": 0.1},
        good=["back_to_school", "home_upgrade", "office"],
        careful={"new_launch": "D 系列不是首发机型，写新品首发需核对发布时间",
                 "creator": "创作类软件的性能需求需读者自行核对"},
        note="D 系列，更适合预算敏感、学生与家庭使用的读者"),
    "d16": dict(
        bonus={"display": 0.3, "study": 0.25, "ports": 0.25, "office": 0.2},
        good=["home_upgrade", "office", "back_to_school"],
        careful={"new_launch": "D 系列不是首发机型，写新品首发需核对发布时间"},
        note="D 系列大屏，适合表格、文档和家庭共用"),
    "d16se": dict(
        bonus={"study": 0.2, "office": 0.2, "ports": 0.15, "display": 0.1},
        good=["home_upgrade", "back_to_school", "office"],
        careful={"new_launch": "D 系列不是首发机型，写新品首发需核对发布时间"},
        note="D 16 SE 版，与 D 16 是不同机型，参数与价格不能互相借用"),
    "gt14": dict(
        bonus={"performance": 0.35, "creative": 0.2, "display": 0.1},
        good=["creator", "office"],
        careful={"back_to_school": "性能向机型需提醒读者核对重量与预算"},
        note="GT 系列，偏性能路线"),
    "xpro": dict(
        bonus={"portable": 0.3, "display": 0.2, "office": 0.25, "collab": 0.1},
        good=["office", "festival", "new_launch"],
        careful={"enterprise_procurement": "批量采购价格走官方询价，不写金额"},
        note="X Pro 系列，偏轻薄商务路线"),
}
DEFAULT_FIT = dict(bonus={}, good=[], careful={}, note="")

HARMONY_SOFTWARE_NOTE = "鸿蒙电脑能否运行读者必须用的 Windows 专用软件，是选购的前置条件，须在稿件里如实提示（来自 KB 的“不适用/需先验证”事实）"
WINDOWS_SOFTWARE_NOTE = "Windows 机型不套用鸿蒙电脑的软件前置提示，但具体软件的系统要求仍建议读者向厂商核对"

# 平台对卖点标签的轻微偏好（加在场景权重上）
PLATFORM_TAG_NUDGE = {
    "wechat_mp": {"office": 0.05, "collab": 0.05},
    "xiaohongshu": {"portable": 0.08, "display": 0.05, "ai": 0.04},
    "moments": {"display": 0.05, "portable": 0.05},
    "poster": {"display": 0.1, "portable": 0.06, "ports": 0.05},
}

# 通用“用户动作在前”文案：(小标题, 引子)。场景里有专属版本时优先用专属。
GENERIC_ACTION = {
    "portable": ("要带着走，先看机身", "设想你一周有好几天要背着电脑出门，机身的尺寸和重量，会比参数表上的其他项更早被你感觉到。"),
    "battery": ("不一定有插座，续航才重要", "如果一天里有大半时间不在固定工位，续航和充电方式，就决定了你要不要随身带一块电源。"),
    "display": ("屏幕是盯得久的部分", "文档、表格、网页，大部分时间你都在盯着屏幕，所以屏幕的比例、分辨率和亮度条件值得单独看。"),
    "performance": ("多个窗口同时开着", "设想你同时开着文档、浏览器和聊天窗口，还要导出一份文件，这时候处理器、内存和存储就开始起作用了。"),
    "ports": ("外设和转接头", "键盘鼠标、U 盘、投影、显示器，每多一样外设，就要多想一下接口够不够用。"),
    "ai": ("重复的活，想少做一点", "如果你每天有一部分时间花在重复的整理、查找和归纳上，AI 功能能不能接进你的流程，值得认真看一眼。"),
    "collab": ("手机、平板、电脑接力", "设想你在手机上拍了一张白板照片，下一步要在电脑上用，文件怎么过来，就是协同要回答的问题。"),
    "creative": ("做内容，先看画面", "修图、剪辑、排版，这些活对屏幕的色彩和输入方式各有要求。"),
    "office": ("日常办公的几个动作", "开会、写文档、做表格、发邮件，每天反复做的就是这几个动作，顺不顺手靠细节。"),
    "study": ("查资料、做笔记", "查资料、做笔记、写报告，窗口多、切换频繁，屏幕比例和输入方式都会影响节奏。"),
    "travel": ("出差路上的电脑", "设想一次出差：高铁上写材料，到酒店接着改，候机时再补一段，电脑得跟得上这种节奏。"),
    "security": ("数据和账号的底线", "如果电脑里放着工作资料，设备怎么登录、数据怎么保护，是采购前必须问清的问题。"),
    "manage": ("多台设备怎么管", "设想一次交付几十台电脑，后续的统一配置和运维方式，往往比单台参数更影响成本。"),
    "stylus": ("手写和触控", "如果你习惯手写批注、用触控翻页，触控屏和笔的支持范围就要先确认。"),
    "aftersales": ("买了之后的事", "设备出问题时去哪里、怎么报修、保修范围多大，这些问题最好在购买前问清楚。"),
    "keyboard": ("输入手感", "每天打字的人，键盘的布局和键程，比规格表上的很多项更直接。"),
    "audio": ("开会和通话", "设想一场半小时的视频会议，摄像头、麦克风和扬声器就是你的门面。"),
}

# 连接词：把引子接到事实句上（场景类文字，不含产品断言）
BRIDGES = [
    "落到这台机器上，官方资料是这样写的：",
    "翻了一遍官方资料，对应的信息是：",
    "资料里和这件事有关的几条是：",
    "对照官方资料，能确认的有这些：",
]
BRIDGES_SHORT = [
    "这部分官方给的数据是：",
    "官方页面能查到的是：",
    "资料中对应的一条是：",
    "同来源里还写着：",
    "官方规格页这一栏是：",
    "整理自公开资料的一条：",
]

GENERIC_SHORT = {
    "portable": "要带着走，先看机身。", "battery": "不一定有插座，续航要看。", "display": "屏幕盯得久，值得单独看。",
    "performance": "窗口一多，配置就看出来了。", "ports": "外设一多，接口就是问题。", "ai": "重复的活，想少做一点。",
    "collab": "手机、平板、电脑要接力。", "creative": "做内容，先看画面。", "office": "文档表格邮件，天天都在做。",
    "study": "查资料、做笔记，窗口多。", "travel": "出差路上，电脑要跟得上。", "security": "数据和账号，要先守住。",
    "manage": "设备多了，管理是成本。", "stylus": "手写和触控，先确认支持。", "aftersales": "买了之后的事，先问清。",
    "keyboard": "天天打字，手感要紧。", "audio": "视频会议，是你的门面。",
}


def action_for(scenario: str, tag: str) -> tuple[str, str, str]:
    """(小标题, 长引子, 短引子)：用户动作在前，不含任何产品断言。"""
    sc = SCENARIOS.get(scenario) or {}
    if tag in sc.get("actions", {}):
        return sc["actions"][tag]
    h, lead = GENERIC_ACTION.get(tag, ("再看一项", "还有一项值得放进比较清单。"))
    return h, lead, GENERIC_SHORT.get(tag, h)


SCENARIOS: dict[str, dict] = {}

SCENARIOS["back_to_school"] = dict(
    label="开学季",
    audience="即将入学或返校的大学生，以及帮孩子挑电脑的家长",
    usage_scene="宿舍、教室、图书馆之间来回，查资料、写论文、做课件、上网课",
    stage="比较（开学前一两个月，已经在列候选）",
    pains=["每天要背着电脑走，机身重量和尺寸是实实在在的负担",
           "宿舍、教室、图书馆不一定都有插座，一天能不能撑下来要提前想",
           "课程要用的软件能不能装，买之前没人替你确认",
           "预算有限，既怕买贵，也怕买了不合用"],
    goal="让读者带着“课程软件清单 + 预算”去官方页面核对，而不是被一堆参数吓退",
    weights=dict(portable=.95, battery=.9, study=.85, ai=.6, ports=.55, display=.45, office=.4,
                 collab=.35, performance=.35, keyboard=.3),
    why=dict(portable="学生每天背着电脑穿梭在宿舍、教室和图书馆，重量和尺寸最先被感知",
             battery="课表连着排时没法回宿舍充电，续航和充电方式是真实约束",
             study="查资料、写论文、记笔记是主要用法，屏幕比例和输入方式直接影响效率",
             ai="笔记和文献整理是学生的重复劳动，AI 功能能否接入流程值得一看"),
    img_pref=["appearance", "scene", "display", "ports"],
    taboo=["不写“学霸”“保证成绩”一类结果承诺", "不写教育优惠、国补、立减等未出现在 KB 的权益", "不编同学或家长的评价"],
    sections_on=dict(wechat_mp=["checklist"], xiaohongshu=["checklist"]),
    sections_off=dict(),
    hooks=[
        dict(angle="背包里的一天",
             open="设想开学第一周的某个早晨：八点的课在教学楼一层，十点半要去图书馆占座，下午还有小组讨论。电脑要跟着你从宿舍走到教室，再走到图书馆，中间不一定有插座可用。",
             short="开学第一周，电脑要跟你跑三个地方。"),
        dict(angle="宿舍群里的老问题",
             open="每年开学前，宿舍群里总有人问同一句话：电脑到底买哪台？问到最后，大家发现真正在意的只有几件事：背着累不累，上课能不能撑一整天，课程要用的软件装不装得上。",
             short="选电脑先别看跑分，先列课程软件清单。"),
        dict(angle="家长视角",
             open="假设你正在帮孩子挑上大学用的电脑。孩子说要轻一点，你想的是耐用，预算又摆在那里。这类选择里，容易被忽略的反而是基础的几件事：带出门、撑一天、软件装不装得上。",
             short="给要上大学的孩子挑电脑，先问三个问题：背着累不累，上课能不能撑一天，课程要用的软件装不装得上。"),
    ],
    scene2="课表、社团和实验课排下来，一天里能稳稳坐在书桌前的时间并不多。写论文、整理笔记、做课件、上网课，这些事会分散在宿舍、教室和图书馆里完成，所以挑电脑更像在挑一件随身工具。",
    titles=dict(
        wechat_mp=["开学前选电脑，先想清楚这三件事", "从宿舍到图书馆，一台电脑要陪你走多远", "{m}：写给新生的一份选购核对清单"],
        xiaohongshu=["新生选电脑，我会先看这几项", "开学前的电脑功课，一篇说清", "宿舍党选电脑，先列清单再下单"],
        poster=["开学季选{m}，先看{p}", "{m}｜写给新生的{p}清单", "新学期，{m}与你的{p}"]),
    poster_sub=["开学前，把课程软件清单带来核对", "新学期选电脑，先对清单再对配置"],
    actions=dict(
        portable=("每天背着走，重量是真实的负担", "设想你一天要在宿舍、教学楼和图书馆之间走三趟，背包里每多一点重量，肩膀都能感觉到。所以机身尺寸和重量，值得放在清单前列。", "背着它跑教室，重量要先看。"),
        battery=("没有插座的那堂课", "如果课表是连着排的，一上午没法回宿舍充电，那续航和充电方式就比多数参数更实际。", "连着上课，插座不一定有。"),
        study=("查资料、写论文、整理笔记", "设想你在图书馆里同时开着论文文档、文献网页和笔记，窗口来回切换。屏幕比例和输入方式，会直接影响你的节奏。", "论文、文献、笔记一起开。"),
        ai=("整理笔记，少花一点时间", "如果你手里有一堆课堂笔记和文献要归纳，AI 功能能不能接进这个流程，值得认真看一眼。", "笔记整理，想少花点时间。"),
    ),
    checklist=["列出本学期必用的软件，逐个去软件官网确认支持的系统",
               "确认预算上限，再打开官方页面核对你要买的那一档配置",
               "找一个有展机的地方，把电脑放进你平时的背包里比一比"],
    limit_lead="选电脑别只听好话，还有一件事要提前说清：",
    pending=["课程指定软件对该系统的支持情况需读者自行核对", "购买价格与权益以官方页面当日显示为准"],
    cta=dict(wechat_mp="把课程软件清单和预算列出来，打开官方页面核对你要的那一档配置，再决定要不要去门店上手试一试。",
             xiaohongshu="你们这学期必装的软件有哪些？评论区告诉我，我帮你对照资料看看。",
             moments="要上大学的朋友，把课程软件和预算发我，我按当前配置逐项帮你核对。",
             poster="扫码查看官方页面，带上课程软件清单到店核对"),
    hashtags=["#开学季", "#大学生装备", "#笔记本选购", "#新生必看"],
)

SCENARIOS["office"] = dict(
    label="职场办公",
    audience="经常开会、写材料、做表格的办公族和小团队负责人",
    usage_scene="工位、会议室、出差路上，文档、表格、会议与跨设备传文件",
    stage="比较到决策（旧电脑开始拖后腿，正在做最后筛选）",
    pains=["会议材料在手机、平板、电脑之间来回绕路",
           "进会议室才发现接口对不上，要翻转接头",
           "文档、表格、聊天窗口一多，切换就不顺手",
           "出差路上电量和充电条件不确定"],
    goal="让读者把“一次完整的开会流程”套进来，核对这台电脑在每个环节会不会掉链子",
    weights=dict(office=.9, collab=.88, ports=.78, ai=.7, display=.55, portable=.5, battery=.5,
                 audio=.5, performance=.45, keyboard=.35, security=.3),
    why=dict(collab="办公里最耗时间的往往是材料在设备间流转，协同能力决定流程是否顺",
             ports="会议室投影、U 盘、外接显示器几乎每天都会遇到，接口是否直连影响体验",
             ai="纪要、汇总、整理是重复劳动，AI 功能能接管哪一步最值得看",
             office="文档、表格、窗口切换是最高频动作"),
    img_pref=["scene", "ports", "display", "appearance"],
    taboo=["不写“提升多少效率”这类无法证实的数字", "不编同事或客户的评价", "不写 KB 之外的软件兼容结论"],
    sections_on=dict(wechat_mp=["checklist"]),
    sections_off=dict(),
    hooks=[
        dict(angle="周一早晨的会议",
             open="设想一个周一早晨：九点半的周会，白板照片在手机里，上周的纪要在电脑上，参考表格在另一台设备里。开会前十分钟，你在三台设备之间来回找文件。",
             short="周一九点半开会，文件还在另一台设备里。"),
        dict(angle="会议室里的转接头",
             open="很多人都经历过：走进会议室，投影线、U 盘和键盘一起上场，然后发现手里的电脑缺一个口。会议开始前的两分钟，被一个小小的转接头占掉了。",
             short="进会议室才发现缺个转接头？"),
        dict(angle="出差一天",
             open="设想一次当天往返的出差：高铁上写材料，客户办公室里接投影讲方案，回程路上再补一份纪要。电脑要跟着你在三种环境里切换，中间未必有插座。",
             short="一天三个场景，电脑要都接得住。"),
    ],
    scene2="办公电脑的好坏，往往不在某个参数上，而在一整套流程里有没有哪一步卡住：材料怎么过来，会议怎么接，文档怎么改，改完怎么发。下面按这个顺序，把能确认的信息过一遍。",
    titles=dict(
        wechat_mp=["一份会议材料，为什么总要在三台设备间绕路", "进会议室之前，先把这几件事核对一遍", "{m}：从周会到出差，一台办公电脑的核对清单"],
        xiaohongshu=["打工人换电脑，我会先看这几点", "开会前十分钟，别再翻转接头", "办公电脑怎么挑？按一天流程来对"],
        poster=["办公选{m}，先看{p}", "{m}｜为开会、写材料准备", "{m}，把{p}交给它"]),
    poster_sub=["从周会到出差，把流程里的每一步都核对到", "办公电脑，按一天的流程来选"],
    actions=dict(
        collab=("会议材料不再在三台设备间绕路", "设想一个周一早晨：白板照片在手机里，会议纪要在电脑上，参考文件在平板里。材料怎么在设备间过来，就是协同要回答的问题。", "手机里的图，要到电脑上用。"),
        ports=("会议室里的转接头", "设想你走进会议室，投影线、U 盘和键盘一起上场，接口够不够，决定你要不要再摸出一个转接头。", "接投影，别再翻转接头。"),
        ai=("把重复的整理交出去一部分", "如果你每周都要写纪要、整理邮件、汇总表格，重复动作越多，越值得看 AI 功能能接管哪一步。", "纪要和汇总，想交出去一部分。"),
        office=("每天反复做的那几个动作", "开会、写文档、做表格、发邮件，每天反复做的就是这几个动作，顺不顺手要靠细节一点点攒出来。", "文档、表格、邮件，天天都在做。"),
    ),
    checklist=["把你一天里用到的软件列成清单，逐个确认支持的系统",
               "带上你常用的外设（投影线、U 盘、扩展坞），到店里现场插一遍",
               "打开官方页面，核对你要买的那一档配置与当日价格"],
    limit_lead="办公选型，有一条要提前说清：",
    pending=["办公软件、插件与外设对该系统的支持需读者自行核对", "协同能力依赖设备、账号与系统版本"],
    cta=dict(wechat_mp="先把你每天必开的软件列出来，对照官方页面里的系统要求，再约一个时间去门店把外设接一遍。",
             xiaohongshu="你们办公必开的软件有哪些？评论区聊聊，我帮你对一下资料。",
             moments="每天开会写材料的朋友，把常用软件和外设发我，我按当前配置帮你逐项核对。",
             poster="到店带上常用外设，现场接一遍；扫码看官方页面"),
    hashtags=["#职场办公", "#打工人好物", "#办公电脑", "#开会效率"],
)

SCENARIOS["creator"] = dict(
    label="内容创作",
    audience="做图文、短视频、设计和摄影后期的内容创作者",
    usage_scene="素材整理、修图排版、剪辑导出、外接设备与跨设备取素材",
    stage="比较（工作流已经成型，在找能接得住的机器）",
    pains=["屏幕色彩和比例影响判断，出图后在别处看颜色不一样",
           "素材从手机、相机到电脑，路径太长",
           "导出时间、风扇声、掉帧，都是创作节奏的敌人",
           "常用的创作软件在新系统上能不能用，没人替你确认"],
    goal="让读者按自己的创作流程逐环节核对：屏幕、输入、素材传输、软件是否支持",
    weights=dict(display=.95, creative=.9, performance=.85, stylus=.7, collab=.6, ports=.55,
                 ai=.5, portable=.4, audio=.25),
    why=dict(display="创作者对屏幕的依赖最强：比例、分辨率、亮度和色域口径都要看清条件",
             performance="剪辑和导出直接吃处理器与存储，但只能引用 KB 里带条件的规格，不写测试结果",
             stylus="手写和触控影响绘制、批注类工作流",
             creative="先看资料里有没有明确的创作任务适配描述"),
    img_pref=["display", "scene", "detail", "appearance"],
    taboo=["不得编造软件测试结果、渲染时间、帧率或跑分", "不写“专业级”“媲美工作站”等无依据对比", "不编创作者的亲身评价"],
    sections_on=dict(),
    sections_off=dict(),
    hooks=[
        dict(angle="出图后的颜色",
             open="如果你做过修图，大概经历过这件事：在一块屏幕上调好的颜色，换到另一块屏幕上就不对了。创作者挑电脑，起点往往是挑一块自己信得过的屏幕。",
             short="修好的图，换块屏幕就变色？"),
        dict(angle="从素材到成片",
             open="设想一个周末的创作日：早上从手机里导出素材，中午在电脑上粗剪，下午调色、出图、发布。每一步用到的东西不一样，电脑得把这些环节串起来。",
             short="素材、粗剪、出图，电脑要串起整条线。"),
        dict(angle="桌面的第二块画布",
             open="设想你习惯在屏幕上直接批注、画草图，再切回键盘继续排版。这时候屏幕的触控与笔的支持，就不再是锦上添花，而是工作流的一部分。",
             short="屏幕上画草图，再回键盘排版。"),
    ],
    scene2="做内容的人，对电脑的要求很具体：看得准、传得快、导得稳。下面只讲资料里能确认的部分，没有测试数据的地方，不替它说话。",
    titles=dict(
        wechat_mp=["做内容的人，挑电脑先看这块屏幕", "从素材到成片，一台创作电脑要接住哪些环节", "{m}：创作者的选购核对表"],
        xiaohongshu=["修图党选电脑，我先看屏幕", "创作者换电脑，按工作流来对", "剪辑、修图、排版，电脑怎么选"],
        poster=["创作选{m}，先看{p}", "{m}｜给创作者的{p}", "画面之外，{m}还有{p}"]),
    poster_sub=["素材到成片，先把画面这一关看清", "创作者选电脑，先对屏幕再对性能"],
    actions=dict(
        display=("出图之后，颜色别变样", "如果你修图时总担心颜色在别处会变，那屏幕的比例、色域和亮度条件，就是要先看的一项。注意这些数字都带典型值或版本条件。", "颜色在别的屏幕上会变，要先看屏。"),
        performance=("导出的那几分钟", "设想你把一段素材拖进时间线，加了几层调色，点导出。资料里的处理器、内存和存储规格，只能告诉你硬件基础，具体用时取决于你的软件和素材。", "导出前，先看硬件基础。"),
        stylus=("直接在屏幕上批注和画草图", "如果你习惯用笔在屏幕上勾画，触控点数和笔的支持范围，要比其他项更先确认。", "屏幕上勾画，先确认笔支持。"),
        collab=("素材从手机到电脑", "设想你在外面用手机拍了一批素材，回到电脑前要做的事就是把它们弄过来。协同方式决定这一步要不要掏线。", "手机里的素材，怎么过来？"),
        creative=("先看资料怎么写创作场景", "不同机型的创作任务适配描述不一样，这一项直接引用资料的原话更稳妥。", "创作适配，看资料原话。"),
    ),
    checklist=["把你常用的创作软件列成清单，逐个确认支持的系统",
               "带一张你自己的作品去门店，在目标机型的屏幕上看一遍颜色",
               "核对你要买的那一档配置，再比较价格"],
    limit_lead="创作电脑还有一条要先说清：",
    pending=["创作软件对该系统的支持需读者自行核对", "资料中无软件测试结果，稿件不涉及渲染/导出耗时"],
    cta=dict(wechat_mp="带上一张你自己的作品，去门店在目标机型上看一遍；回家后再对照官方页面核对配置。",
             xiaohongshu="你平时用什么软件修图或剪辑？评论区说一声，我帮你看看资料里怎么写。",
             moments="做内容的朋友，把你常用的软件和作品类型发我，我帮你对照资料核对。",
             poster="带一张自己的作品到店，在这块屏幕上看一遍"),
    hashtags=["#内容创作", "#创作者工具", "#修图剪辑", "#生产力工具"],
)

SCENARIOS["home_upgrade"] = dict(
    label="家庭换新",
    audience="想给家里换一台电脑的家庭用户，常见是全家共用、孩子上网课、长辈偶尔使用",
    usage_scene="客厅或书房，孩子网课作业、家长办公、长辈看视频和视频通话",
    stage="认知到比较（旧电脑慢了，不知道从哪里看起）",
    pains=["全家共用，每个人要的东西不一样",
           "预算有限，不想为用不到的配置买单",
           "家里人不懂配置，买回去能不能直接用才是关键",
           "旧电脑里的文件和照片怎么搬"],
    goal="让读者按“谁用、用来做什么、预算多少”三问选，而不是比参数",
    weights=dict(office=.75, study=.75, display=.7, ports=.7, portable=.45, battery=.45, performance=.5,
                 collab=.5, keyboard=.5, aftersales=.4, ai=.35),
    why=dict(display="全家共用时屏幕是被使用最多的部分，尺寸和比例影响每个人",
             ports="旧的 U 盘、打印机、显示器等外设还要接，接口决定换电脑要不要再买转接头",
             study="孩子的作业和网课是家庭电脑的刚需",
             office="家长的办公和表格是第二大类需求"),
    img_pref=["appearance", "scene", "display", "ports"],
    taboo=["不写“全家都适用”这类绝对说法", "不写 KB 之外的以旧换新/补贴", "不编家人的使用反馈"],
    sections_on=dict(wechat_mp=["checklist"], xiaohongshu=["checklist"]),
    sections_off=dict(),
    hooks=[
        dict(angle="全家共用的那一台",
             open="设想一个周末的晚上：孩子在客厅写作业，爸爸在查一份表格，奶奶在旁边用同一台电脑看视频。一台电脑，三个人，三种用法。换电脑之前，这个场景得先想清楚。",
             short="一台电脑，全家三个人轮着用。"),
        dict(angle="旧电脑的告别",
             open="家里那台用了很多年的电脑，开机要等，开几个网页就卡，但里面有全家的照片和孩子的作业。换新电脑，让人犹豫的往往不是价格，而是怎么把这些东西平稳地搬过去。",
             short="旧电脑卡了，可里面有全家的照片。"),
        dict(angle="先问三个问题",
             open="给家里换电脑，不用急着看参数。先问三个问题：谁用？主要做什么？预算多少？这三个答案清楚了，后面的选择会简单很多。",
             short="给家里换电脑，先问三句话。"),
    ],
    scene2="家用电脑的特点是“人多、用法杂、不想折腾”。所以我们按家庭里常见的几种用法，分别看资料里能确认什么，再说哪些地方要提前问清。",
    titles=dict(
        wechat_mp=["给家里换电脑，先别急着看参数", "一台电脑全家用，这几件事要先想清楚", "{m}：写给家庭用户的换机核对清单"],
        xiaohongshu=["家里换电脑，我会先问这三句", "全家共用一台电脑，怎么选", "旧电脑该换了？先看这几项"],
        poster=["家用选{m}，先看{p}", "{m}｜全家共用的{p}", "给家换一台：{m}"]),
    poster_sub=["全家共用，先问清谁用、做什么、预算多少", "换电脑之前，把旧外设带来试一试"],
    actions=dict(
        display=("全家人盯得久的就是屏幕", "设想孩子写作业、家长看表格、长辈看视频，大家都在看同一块屏幕。尺寸和比例是否舒服，是所有人都会感受到的事。", "全家都在看这一块屏。"),
        ports=("家里的旧外设还能不能接", "如果家里还有打印机、U 盘、移动硬盘，接口够不够、要不要买转接头，是换电脑后很快就会撞上的问题。", "旧外设还能接吗？"),
        study=("孩子的作业和网课", "设想孩子晚上要上网课、写作业、查资料，窗口开得不少。屏幕和输入，会比参数表里的其他项更先被感觉到。", "孩子写作业、上网课，要看这几项。"),
        office=("家长的表格与文档", "如果家长偶尔也要在家处理表格和文档，那么屏幕大小、键盘手感这些细节会反复被用到。", "家长回家也要处理文档。"),
        keyboard=("打字的手感", "全家人轮流用的电脑，键盘是常被碰到的部分。布局和键程是否习惯，值得上手试一试。", "打字手感，要上手试。"),
    ),
    checklist=["先问清楚谁用、主要做什么、预算大概多少",
               "把家里要继续用的外设（打印机、U 盘、鼠标）列出来，确认接口",
               "旧电脑里的文件先备份，再去门店比一比"],
    limit_lead="家里换电脑，有一条要提前讲清楚：",
    pending=["家用软件、打印机等外设的兼容需读者自行核对", "购买价格与权益以官方页面当日显示为准"],
    cta=dict(wechat_mp="先把“谁用、做什么、预算多少”写在手机备忘录里，再带着旧外设去门店逐项试一遍。",
             xiaohongshu="你们家电脑主要谁在用？评论区聊聊，我帮你看看该看哪几项。",
             moments="家里想换电脑的朋友，把谁用、做什么、预算发我，我帮你按当前配置核对。",
             poster="带上家里的旧外设到店试一试"),
    hashtags=["#家庭换新", "#家用电脑", "#换电脑", "#笔记本推荐"],
)

SCENARIOS["enterprise_procurement"] = dict(
    label="企业采购",
    audience="企业 IT 负责人、行政采购与部门负责人",
    usage_scene="批量配置、统一管理、数据安全、售后保障和试点验收",
    stage="决策（已进入方案评估，需要可核对的材料）",
    pains=["批量采购后的统一管理与运维是隐性成本",
           "业务软件、外设与现有系统能不能接上，需要试点验证",
           "数据安全与账号体系要符合企业要求",
           "价格与服务条款走询价流程，口头承诺难以落地"],
    goal="给采购决策人一份“先试点、再扩量”的核对框架，把能确认的事实和必须询价的事项分开",
    weights=dict(manage=.9, security=.88, ports=.75, aftersales=.72, office=.65, collab=.55, performance=.5,
                 portable=.4, battery=.4, display=.35, keyboard=.3),
    why=dict(manage="企业采购看的是设备规模化之后的统一管理，资料里有明确描述的才引用",
             security="数据与账号安全是采购评审的硬性问题，只引用资料里带条件的表述",
             ports="外设与现场环境多样，接口决定部署阻力",
             aftersales="服务与保障条款以官方渠道为准，稿件不得承诺 KB 之外的政策"),
    img_pref=["ports", "detail", "appearance", "scene"],
    taboo=["禁止承诺 KB 之外的政策：批量折扣、定制服务、售后时效、交付周期", "不写采购价、项目价、渠道价", "不写“绝对安全”“零故障”"],
    sections_on=dict(wechat_mp=["checklist"]),
    sections_off=dict(),
    hooks=[
        dict(angle="先试点，再扩量",
             open="设想一家公司准备更新一批办公电脑。财务、研发和外勤三类岗位的需求差别不小，直接一次性下单，风险都压在下单那一步。稳妥的办法是先选几类岗位各试用一批，记录问题再决定规模。",
             short="批量换电脑，先试点再扩量。"),
        dict(angle="采购评审会上的三个问题",
             open="采购评审会上，常被问到的往往不是参数，而是三件事：现有软件能不能接上？数据怎么管？出了问题找谁？这三问先有答案，方案才站得住。",
             short="评审会上，被问得多的是这三件事。"),
        dict(angle="清单与询价",
             open="企业采购和个人购买不同：公开页面上的价格只是参考，批量的价格、服务与交付条款，要走官方询价。所以一份好的采购材料，要把“能确认的”和“要询价的”分开写。",
             short="能确认的，和要询价的，分开写。"),
    ],
    scene2="下面按采购评审里常见的顺序整理：先看资料里能确认的产品事实，再把必须验证的部分单独列出来。价格、批量政策与服务条款，这里不写，走官方询价。",
    titles=dict(
        wechat_mp=["企业换一批电脑，评审会前先备好这份清单", "批量采购前，把能确认的和要询价的分开", "{m}：企业采购的试点与核对框架"],
        xiaohongshu=["给公司选电脑，我会先做这几步", "IT 采购的试点清单", "批量换电脑前，先问清这三件事"],
        poster=["企业采购{m}，先看{p}", "{m}｜试点先行的{p}", "{m}，采购清单里的{p}"]),
    poster_sub=["批量与服务条款，请走官方询价", "先试点，再扩量"],
    actions=dict(
        manage=("设备多了，管理是长期成本", "设想一次交付几十台电脑，后续的统一配置与运维方式，往往比单台参数更影响成本。资料里有明确描述的才引用，其余要在试点里验证。", "设备多了，管理是长期成本。"),
        security=("数据和账号的底线", "如果电脑里放着工作资料，设备怎么登录、数据怎么保护，是评审里常会被问到的问题。", "数据与账号，评审必问。"),
        ports=("会议室、工位和外设的现实环境", "设想不同岗位的现场：有的接两块显示器，有的要连投影，有的靠扩展坞。接口决定部署阻力。", "外设环境各不同，接口先看。"),
        aftersales=("买了之后找谁", "采购评审通常会问服务与保障。具体条款以官方渠道为准，稿件里只引用资料确认的部分。", "服务保障，以官方渠道为准。"),
        office=("办公岗位的日常", "不同岗位的办公任务不同，试点时按岗位各取一批，让规模决策有据可依。", "按岗位试点，再定规模。"),
    ),
    checklist=["按岗位（财务、研发、外勤）各选一批做试点，并记录应用兼容与故障情况",
               "列出必用的业务软件与外设，逐项向厂商确认支持的系统",
               "批量价格、服务范围、交付周期走官方询价，书面确认"],
    limit_lead="采购评审里，必须单独列出的一项：",
    pending=["批量价格、服务条款、交付周期未在资料中，须走官方询价", "业务软件与外设兼容需试点验证"],
    cta=dict(wechat_mp="先选三类岗位做小规模试点；批量价格、服务和交付，请通过官方企业渠道询价并书面确认。",
             xiaohongshu="你们公司采购电脑看重哪一项？评论区聊聊。",
             moments="做企业采购的朋友，把岗位、台数和必用软件发我，我帮你整理一份试点核对清单；价格走官方询价。",
             poster="企业采购咨询：请通过官方企业渠道询价"),
    hashtags=["#企业采购", "#IT采购", "#办公设备", "#试点先行"],
)

SCENARIOS["store_visit"] = dict(
    label="门店到访",
    audience="已经有明确兴趣、准备或刚刚到店体验的顾客",
    usage_scene="到店体验、上手对比、现场提问",
    stage="到店（只差一个确认动作）",
    pains=["到店后信息太多，记不住该看什么",
           "导购介绍很多，真正要核对的只有一两件事",
           "担心现场说的和官方页面不一致"],
    goal="只放大一个核心卖点，让顾客到店后知道摸什么、看什么、问什么",
    weights=dict(display=.9, portable=.85, ports=.8, keyboard=.7, battery=.6, ai=.55, collab=.5,
                 performance=.4, office=.4),
    why=dict(display="到店体验最直观的是屏幕：一眼就能比较，也最容易被现场验证",
             portable="重量和厚度，拿起来就知道，是最适合到店验证的卖点",
             ports="接口数量和类型，现场插一插就清楚"),
    img_pref=["appearance", "scene", "display", "detail"],
    taboo=["全文只选 1 个核心卖点，其余内容不展开", "不写“限量”“最后几台”等库存稀缺话术", "不写未出处的到店礼、优惠或活动"],
    sections_on=dict(),
    sections_off=dict(xiaohongshu=["checklist"]),
    single_point=True,
    hooks=[
        dict(angle="到店先摸一样东西",
             open="如果你这周打算去门店看电脑，不用把所有参数都背下来。只带着一个问题去：这台电脑要紧的那一点，当场确认一下。",
             short="到店先确认一件事就够了。"),
        dict(angle="站在展台前的三十秒",
             open="设想你站在展台前，面前是一台打开的电脑。三十秒里你该做的，是把它值得看的那一点看明白，而不是被一屏参数拉走。",
             short="站在展台前，先看明白一点。"),
    ],
    scene2="到店这一步，只要一个动作：用手和眼睛确认一个点。下面只讲这一点，其他的留给你在现场问。",
    titles=dict(
        wechat_mp=["到店之前，先记住这一件事", "站在展台前，只看一个点", "{m}：到店体验，先确认这一项"],
        xiaohongshu=["去门店之前，只带一个问题", "逛电脑店，先确认这一点", "到店看电脑，别被参数拉走"],
        poster=["到店体验{m}，先看{p}", "{m}｜现场上手确认{p}", "{m}，来店里看{p}"]),
    poster_sub=["到店上手试一下，一次只确认一件事", "现场体验，一个点就够"],
    actions=dict(),
    checklist=["到店后先确认这一项，再问其他", "对照官方页面核对配置", "让店员演示你关心的那个场景"],
    limit_lead="到店前说清一件事：",
    pending=["到店活动、赠品、库存请以门店当日公示为准"],
    cta=dict(wechat_mp="这周找个时间来店里上手确认这一项；有疑问现场问，我们对着官方页面一起核对。",
             xiaohongshu="你到店想确认哪一项？评论区告诉我。",
             moments="这周来店里上手看看，直接说你关心的一点，我现场演示给你。",
             poster="到店体验，现场演示"),
    hashtags=["#门店体验", "#到店打卡", "#笔记本体验"],
)

SCENARIOS["new_launch"] = dict(
    label="新品首发",
    audience="关注新品、愿意为新形态或新能力了解细节的数码爱好者与换机用户",
    usage_scene="首发信息了解、与上一代比较、决定是否尝鲜",
    stage="认知到比较（刚看到新品，想知道变化在哪）",
    pains=["首发信息太多太杂，分不清哪些是官方确认",
           "新品的价格、权益和发售信息，必须有出处才能信",
           "不确定新品和自己用的软件是否匹配"],
    goal="只把官方资料里能确认的新特性讲清楚，价格与权益一律以官方页面为准",
    weights=dict(ai=.9, display=.85, performance=.8, portable=.7, collab=.65, creative=.55, battery=.5,
                 ports=.4, stylus=.4),
    why=dict(ai="新品的差异点通常体现在新能力上，AI 与新系统特性是读者最想知道的变化",
             display="屏幕是新品最容易被感知的变化，且规格有明确口径可引用",
             performance="新平台的硬件基础是首发讲点，但只引用带条件的规格"),
    img_pref=["appearance", "display", "scene", "detail"],
    taboo=["价格、权益、发售时间必须有出处，没有就不写", "不写“首发抢购”“限量”“库存紧张”", "不拿上一代或其他品牌做无依据对比"],
    sections_on=dict(),
    sections_off=dict(),
    hooks=[
        dict(angle="变化在哪里",
             open="每次看到新品发布，读者想问的就一句：和我现在用的相比，变化在哪里？下面只讲官方资料里写明的内容，没写的不替它补。",
             short="新品出来了，变化到底在哪？"),
        dict(angle="尝鲜之前的功课",
             open="想早一点用上新品的人，往往也容易被信息淹没。尝鲜之前，值得先把三件事核清楚：官方确认了什么，条件是什么，哪些要自己验证。",
             short="尝鲜之前，先做三件功课。"),
    ],
    scene2="首发阶段常见的问题是信息混杂：官方的、转述的、猜测的挤在一起。下面只摘官方资料里能确认的内容，并带上各自的条件。",
    titles=dict(
        wechat_mp=["新品来了，先看官方确认了什么", "尝鲜之前，先把这几件事核清楚", "{m}：新品首发，哪些信息能确认"],
        xiaohongshu=["新品发布，官方到底写了什么", "{m}首发信息整理", "尝鲜前的功课：新品这几项要看"],
        poster=["首发{m}，先看{p}", "{m}｜新品变化一屏看完", "{m}，{p}一屏看清"]),
    poster_sub=["以官方资料为准，价格以官方页面为准", "新品变化，一屏看清"],
    actions=dict(
        ai=("新能力，要看能做什么、需要什么条件", "设想你刚看到新品的 AI 功能介绍，先想的是：这能帮我省哪一步？再想的应该是：它需要什么条件？", "新能力，先问条件。"),
        display=("新屏幕，先看规格口径", "新品的屏幕变化容易被感知，但亮度、色域这些数字都带典型值或版本条件，引用时不能去掉。", "新屏幕，规格口径要看全。"),
        performance=("新平台的硬件基础", "新品的处理器和存储是首发常提的讲点。资料里只写规格，没有测试数据，这里同样只讲规格。", "新平台，只讲规格不讲跑分。"),
    ),
    checklist=["打开官方产品页，核对机型名称、配置与发布信息",
               "价格与权益以官方商城当日展示为准",
               "确认自己必用的软件对新系统的支持情况"],
    limit_lead="首发阶段要说清楚的一点：",
    pending=["价格、发售时间和权益未在资料中的，一律不写", "新品功能的适用条件需读者核对"],
    cta=dict(wechat_mp="打开官方产品页核对配置与条件，再决定要不要预约体验。",
             xiaohongshu="你想知道新品哪一项？评论区留言。",
             moments="想了解新品的朋友，直接告诉我你关心哪一项，我对着官方资料给你讲。",
             poster="扫码查看官方产品页"),
    hashtags=["#新品首发", "#华为电脑", "#新品解读"],
)

SCENARIOS["festival"] = dict(
    label="节日营销",
    audience="节日期间想给自己或家人添置设备的人，也包括挑礼物的人",
    usage_scene="节日前后的购买决策、送礼与自用",
    stage="决策（有明确的购买理由和时间窗口）",
    pains=["节日促销信息很多，分不清哪些是官方的",
           "送礼要考虑对方是否用得上",
           "担心被“限时”“限量”话术催着下单"],
    goal="借节日的情感契机，讲清“适合谁、怎么核对”，而不是靠促销话术",
    weights=dict(portable=.8, display=.75, ai=.7, collab=.65, office=.6, battery=.55, ports=.45, study=.4,
                 performance=.45),
    why=dict(portable="节日送礼和出行都要带，便携外观是最容易讲清楚的角度",
             display="节日氛围里读者更看重初次看到的观感，屏幕规格可作为核对点",
             collab="送给家人的设备，是否能与手机、平板配合，是常见顾虑"),
    img_pref=["appearance", "scene", "display", "detail"],
    taboo=["不得编造折扣、补贴、赠品、库存；KB 没有的活动一律不写", "不写“限时”“限量”“最后”“抢购”", "不借节日渲染焦虑或攀比"],
    sections_on=dict(),
    sections_off=dict(),
    hooks=[
        dict(angle="送给家人的那一份",
             open="设想节日前一周，你在想送家人一份实用的礼物。电脑不是随手买的东西，所以送之前，要多想两步：对方用来做什么，会不会用得上。",
             short="送电脑之前，先想两步。"),
        dict(angle="给自己的节日",
             open="很多人把换电脑留到节日前后：工作告一段落，有一点时间，也有一点理由。这时候不用被活动信息推着走，把需求和预算对清楚就够了。",
             short="节日换电脑，不被活动信息推着走。"),
    ],
    scene2="节日期间的信息很热闹，但对读者真正有用的只有两类：这台电脑适合谁，购买前该核对什么。优惠和活动，以官方页面当日展示为准，这里不写。",
    titles=dict(
        wechat_mp=["节日想送电脑？先问对方用来做什么", "节日换电脑，不被活动信息推着走", "{m}：节日选购的核对清单"],
        xiaohongshu=["送电脑之前，先想两步", "节日换电脑，我会先看这几项", "节日礼物选电脑，怎么不踩坑"],
        poster=["节日选{m}，先看{p}", "{m}｜送人自用都要核对{p}", "{m}，节日里的{p}"]),
    poster_sub=["活动以官方页面当日展示为准", "送人自用，先核对再决定"],
    actions=dict(
        portable=("送人的电脑要拿得出手，还要带得走", "设想你把电脑送给家人，对方可能背着它去上班、回家探亲。外观与便携，是拆开盒子后最先看到的部分。", "送人的电脑，先看外观和便携。"),
        collab=("送给家人，能不能和手机配合", "如果对方已经在用华为手机或平板，那么多设备协同就是一个值得加分的核对点，但需要同一账号等条件。", "送给家人，先问手机是什么。"),
        display=("拆开盒子后先看到的", "节日送人，初次印象往往来自屏幕。尺寸、比例和亮度条件，是核对的起点。", "先看到的，是屏幕。"),
    ),
    checklist=["先问清对方用来做什么，再对照下面的卖点",
               "活动、优惠和库存以官方页面当日展示为准",
               "送人时可以附上发票，并提示对方到店核对配置"],
    limit_lead="节日期间，请先注意这一点：",
    pending=["节日折扣、补贴、赠品与库存均不在资料中，稿件不涉及", "购买前请以官方页面当日展示为准"],
    cta=dict(wechat_mp="先问清对方的用途和预算，再打开官方页面核对配置；活动信息以官方当日展示为准。",
             xiaohongshu="你们送电脑会先问对方什么？评论区聊聊。",
             moments="节日想送电脑的朋友，告诉我对方用来做什么，我帮你按当前配置挑。",
             poster="到店咨询，活动以官方页面为准"),
    hashtags=["#节日礼物", "#送电脑", "#节日选购"],
)

for _sid, _sc in SCENARIOS.items():
    _sc["id"] = _sid


def get_scenario(scenario: Optional[str]) -> dict:
    return SCENARIOS.get(scenario or "") or SCENARIOS[DEFAULT_SCENARIO]


def get_platform(platform: Optional[str]) -> dict:
    return PLATFORMS.get(platform or "") or PLATFORMS[DEFAULT_PLATFORM]


def model_fit(model_id: str) -> dict:
    return MODEL_FIT.get(model_id, DEFAULT_FIT)


def scenario_score(f: Fact, scenario: str, platform: str, user_tag: Optional[str] = None,
                   model_id: str = "") -> tuple[float, list[str]]:
    """单条事实在“场景×平台×型号”下的得分，同时返回命中的标签。"""
    sc = get_scenario(scenario)
    w = sc["weights"]
    nudge = PLATFORM_TAG_NUDGE.get(platform, {})
    fit = model_fit(model_id or f.model_id).get("bonus", {})
    tags = fact_tags(f)
    hit = [t for t in tags if t in w or t in fit]
    base = sum(w.get(t, 0) + nudge.get(t, 0) + fit.get(t, 0) for t in tags if t in w)
    base += 0.5 * sum(fit.get(t, 0) for t in tags if t not in w)
    if user_tag and user_tag in tags:
        base += 2.0
    base *= KIND_RANK.get(f.kind, 0.6)
    return base, hit


def norm_text(s: str) -> str:
    return re.sub(r"[\s。；;，,、：:（）()“”\"']", "", s or "")


def dedupe_facts(facts: list[Fact]) -> list[Fact]:
    """同一模型下文本相同或互为包含的事实只留一条（保留先出现者）。"""
    out, seen = [], []
    for f in facts:
        n = norm_text(f.text)
        if not n:
            continue
        if any(n == s or (len(n) > 12 and n in s) or (len(s) > 12 and s in n) for s in seen):
            continue
        seen.append(n)
        out.append(f)
    return out
