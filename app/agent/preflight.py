"""发布前预演：这篇稿子发出去，顾客/读者最可能在哪一句上提问或质疑。

设计动机：评委说「内容要吸引人」，但更硬的一条是「素材跟真实产品要对得上，
不做虚假传播」。现有工具都在讲"怎么写得更好看"，没人讲"发出去之后会怎样"。

所以这个模块反过来做：站在**读者视角**挑刺。
它不讲文笔，只找三类风险：
1. 读者会追问的：文案提到但没给足条件的数字（「70 Wh」不说清是哪一档）。
2. 读者会质疑的：缺限定条件的绝对化表述残留。
3. 会被平台卡住的：标题/正文里可能触发审核或投诉的词。

输出是一份「进店前先想好怎么答」的清单，销售员提前备好答案，
不会在顾客面前被问住——这才是真正减少工作量。
"""
from __future__ import annotations

import re
from typing import Optional

from app.models import Preflight, PreflightItem

# 读者看到就想问的：数字/规格出现，但同句没有限定词
_NUM_RX = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|g|kg|Wh|nits|Hz|GB|TB|ppi|英寸|寸|万|小时|W)")
_QUALIFIER_RX = re.compile(
    r"约|典型|峰值|额定|最高|最大|最低|支持|可选|视|取决于|以.*为准|随.*变化|需.*核验|版本|条件")

# 容易被平台判定或引起投诉的说法。
# 注意：中文里「不一定」「都能感觉到」这类是正常用法，不是承诺，
# 所以承诺类只匹配「一定」后面跟肯定性动词的组合，并排除否定前缀。
_RISKY_RX = [
    (re.compile(r"最[好用低高快强轻]|第一|唯一|全网|顶级|极致|完美|无敌|史上|秒杀|吊打"), "绝对化用语",
     "平台可能限流，顾客也容易反问「凭什么」。"),
    (re.compile(r"(?<![不没])保证|(?<![不没])一定[是有会用能]|(?<![不没])绝对|(?<![不没])百分百|(?<![不没])100%"), "承诺性表述",
     "无法为所有使用环境兜底，容易被投诉。"),
    # 「必须」只在要求顾客做某事时才算承诺；「必须先验证」「需先确认」是善意提醒
    (re.compile(r"必须(?!运行|先|提前|确认|核实|核对|验证)"), "承诺性表述",
     "无法为所有使用环境兜底，容易被投诉。"),
    (re.compile(r"永远|终身|永久|长期有效"), "时效承诺",
     "政策与活动都会变，写了就收不回来。"),
    # 「所有」在否定或说明性语境里是正常用法（「不能换算所有场景」），
    # 只在前缀不是「不/没/非/无」且后面不是「这/这些/参数/说法/人/用户/场景」时才算全称判断
    (re.compile(r"(?<![不没非无])所有(?!这|这些|参数|说法|人|用户|场景|情况)"), "全称判断",
     "一处例外就会让整篇失去可信度。"),
    (re.compile(r"便宜|划算|超值"), "价格暗示",
     "没有依据的价格判断可能被认定为误导。"),
]
# 「都能」只在紧跟「兼容/接/支持/运行」时才算全称判断
_ALL_CAN_RX = re.compile(r"都能(?:兼容|接|支持|运行|用)")

# 出现这些词，说明该给读者一个明确的核验动作
_ACTION_WORDS = ["核验", "核对", "官方页面", "以官方", "官网"]


def build_preflight(run: dict, kb) -> Preflight:
    art = run.get("article") or {}
    task = run.get("task") or {}
    platform = art.get("platform") or task.get("platform") or ""
    items: list[PreflightItem] = []
    seen: set[str] = set()

    def add(kind, where, text, ask, prep):
        key = f"{kind}|{where}|{text[:20]}"
        if key in seen:
            return
        seen.add(key)
        items.append(PreflightItem(kind=kind, where=where, text=text, ask=ask, prep=prep))

    # 1. 标题
    title = art.get("title") or ""
    for rx, label, why in _RISKY_RX:
        for m in rx.finditer(title):
            add("risky", "标题", title, f"「{m.group(0)}」这类说法，{why}",
                "改成带条件的事实句，例如「官方口径是…，具体以…为准」。")
    m_all = _ALL_CAN_RX.search(title)
    if m_all:
        add("risky", "标题", title,
            f"「{m_all.group(0)}」属于全称判断",
            "改成「支持…（具体范围以官方说明为准）」。")

    # 2. 正文逐段
    asked_nums: set[str] = set()          # 同一数字只追问一次
    for b in art.get("blocks") or []:
        if b.get("kind") == "image":
            continue
        text = (b.get("text") or "").strip()
        if not text:
            continue
        where = "正文"

        # 2a. 有数字没限定
        for m in _NUM_RX.finditer(text):
            num = re.sub(r"\s+", "", m.group(0))
            if num in asked_nums:
                continue
            frag = text[max(0, m.start() - 24):m.end() + 24]
            if _QUALIFIER_RX.search(frag):
                continue
            asked_nums.add(num)
            add("ask", where, frag.strip(),
                f"顾客看到「{m.group(0)}」会问：这是哪一档配置？什么条件下测的？",
                "补上具体配置、测试条件和「以官方页面为准」。")

        # 2b. 风险词
        for rx, label, why in _RISKY_RX:
            for m in rx.finditer(text):
                add("risky", where, text[:70],
                    f"「{m.group(0)}」{why}",
                    "按 KB 的事实改写，或删除该判断。")
        m_all = _ALL_CAN_RX.search(text)
        if m_all:
            add("risky", where, text[:70],
                f"「{m_all.group(0)}」属于全称判断，一处例外就会让整篇失去可信度",
                "改成「支持…（具体范围以官方说明为准）」。")

    # 3. 价格：口径是否完整
    price_note = art.get("price_note") or ""
    if price_note:
        missing = []
        for need, label in (("SKU", "具体配置"), ("核验时间", "核验时间"),
                            ("条件", "附加条件"), ("http", "官方链接")):
            if need not in price_note:
                missing.append(label)
        if missing:
            add("risky", "价格", price_note[:70],
                f"价格依据缺少：{'、'.join(missing)}",
                "补齐后再发；缺一项就不要写金额。")
    elif re.search(r"\d+\s*元|多少钱|价格", "".join(
            (b.get("text") or "") for b in art.get("blocks") or []) + title):
        add("risky", "价格", "（正文出现价格相关表述但无依据）",
            "正文提到价格却没有对应的口径与来源",
            "要么补上带 SKU/时间/条件/链接的价格依据，要么删掉价格表述。")

    # 4. 图片：来源是否可追溯
    for ref in art.get("image_refs") or []:
        if not ref.get("source_url") or not ref.get("page_url"):
            add("ask", "配图", ref.get("image_id", ""),
                "图片来源不完整，被追问时无法出示",
                "补上图片名、来源 URL 和页面来源。")

    # 5. 全文是否有核验动作引导
    body = title + "".join((b.get("text") or "") for b in art.get("blocks") or [])
    if not any(w in body for w in _ACTION_WORDS):
        add("ask", "全文", "（缺少核验动作引导）",
            "读者看完不知道该去哪里核对，容易自行搜索到不准确的信息",
            "加一句「以官方当日页面为准」或给出官方页面入口。")

    # 汇总
    n_risky = sum(1 for i in items if i.kind == "risky")
    n_ask = sum(1 for i in items if i.kind == "ask")
    if n_risky >= 3:
        verdict, note = "risky", f"有 {n_risky} 处风险表述，建议改完再发"
    elif n_risky >= 1:
        verdict, note = "check", f"有 {n_risky} 处风险表述、{n_ask} 处可能被追问，逐条过一遍"
    else:
        verdict, note = "ok", f"未发现风险表述；{n_ask} 处建议提前准备答案"

    return Preflight(
        title=title, platform=platform, verdict=verdict, note=note,
        items=items[:14],
        ready_to_send=(n_risky == 0),
    )
