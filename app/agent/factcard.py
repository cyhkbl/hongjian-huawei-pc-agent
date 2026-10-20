"""新品事实卡：生成之前，先把「这台机器能说什么、不能说什么」摆到桌面上。

评委提的原话：大模型对新发布的产品知识存在幻觉，新产品往往是首要推送任务；
把资料放在自建知识库和 ima 里，仍然无法同时满足「吸引人」和「数据准不过度承诺」。

所以这里不做「生成后再核验」，而是生成前先立规矩：
1. 能说的：从知识库里挑出该机型有依据的事实，按维度分组列出。
2. 不能说的：知识库明确写了「不适用/需先验证」的，以及资料里查不到的常见想问项。
3. 价格：只列有金额、有口径、有核验时间的记录；查不到就明说查不到。

事实卡同时是写作提示：Agent 只能从「能说的」里取料。
"""
from __future__ import annotations

from typing import Optional

from app.agent import profiles as P
from app.kb.base import KnowledgeBase
from app.models import FactCard, FactGroup

# 用户最常想问、但知识库经常没有的项。查不到就如实说"资料未确认"，
# 而不是让模型补一个——这正是幻觉的来源。
COMMON_ASKS = [
    ("能不能跑我需要的软件", ["Windows", "软件", "兼容", "驱动"]),
    ("实际续航多久", ["续航", "电池", "使用时间"]),
    ("现在多少钱", ["价格", "售价", "金额"]),
    ("有没有货", ["库存", "现货", "预售"]),
    ("能不能升级内存硬盘", ["升级", "内存", "存储", "插槽"]),
    ("售后政策是什么", ["保修", "售后", "服务"]),
]

_GROUP_ORDER = ["identity", "display", "performance", "portable", "connect", "ecosystem", "audience", "limit", "other"]
_GROUP_LABEL = {
    "identity": "机型身份",
    "display": "屏幕与显示",
    "performance": "性能与存储",
    "portable": "重量续航与接口",
    "connect": "接口与连接",
    "ecosystem": "系统与协同",
    "audience": "适合谁",
    "limit": "限制与不适用",
    "other": "其他",
}


def _matched(facts, keywords) -> list:
    out = []
    for f in facts:
        blob = f.text + " " + " ".join(f.constraints or [])
        if any(k in blob for k in keywords):
            out.append(f)
    return out


def build_fact_card(model_id: str, kb: KnowledgeBase) -> FactCard:
    m = kb.get_model(model_id)
    if not m:
        return FactCard(model_id=model_id, model_name="未知机型", ok=False,
                        note="知识库里没有这个机型，无法生成为它写的内容。")

    facts = kb.facts(model_id)
    prices = kb.prices(model_id)

    # ---- 能说的：按维度分组
    groups: list[FactGroup] = []
    by_cat: dict[str, list] = {}
    for f in facts:
        if f.kind in ("unfit", "boundary"):
            continue                      # 限制单独成组
        by_cat.setdefault(f.category, []).append(f)
    for cat in _GROUP_ORDER:
        fs = by_cat.get(cat) or []
        if not fs:
            continue
        lines = []
        for f in fs[:6]:
            t = f.text.strip().rstrip("。")
            cons = "；".join(c.strip().rstrip("。") for c in (f.constraints or [])[:2])
            lines.append(t + (f"（{cons}）" if cons else ""))
        groups.append(FactGroup(label=_GROUP_LABEL.get(cat, cat), facts=lines,
                                fact_ids=[f.id for f in fs[:6]]))

    # ---- 不能说的：知识库明确列的不适用 + 查不到的常见提问
    limits: list[str] = []
    limit_ids: list[str] = []
    for f in facts:
        if f.kind in ("unfit", "boundary"):
            limits.append(f.text.strip().rstrip("。"))
            limit_ids.append(f.id)
    limits = list(dict.fromkeys(limits))[:5]

    unconfirmed: list[str] = []
    for ask, kws in COMMON_ASKS:
        if _matched(facts, kws):
            continue
        if ask == "现在多少钱" and prices:
            continue
        unconfirmed.append(f"{ask}：资料未确认，稿件里不能写")

    # ---- 价格：只列可引用的
    price_lines: list[str] = []
    quotable = [p for p in prices if p.amount is not None and p.amount > 0]
    if quotable:
        ptype = quotable[0].price_type
        for p in quotable:
            if p.price_type != ptype:      # 口径不混
                continue
            price_lines.append(
                f"{p.price_type}｜{p.spec}｜{p.amount:.0f} 元｜核验 {p.verified_at[:16].replace('T', ' ')}"
                f"｜条件：{p.conditions or '无附加条件记录'}｜{p.url}")
    elif prices:
        p = prices[0]
        price_lines.append(f"{p.price_type}｜{p.product_name}｜核验 {p.verified_at[:16].replace('T', ' ')}｜{p.url}"
                           "｜官方未公开当前金额，稿件里不写数字")

    harmony = m.os_family == "harmonyos"
    if harmony:
        limits.insert(0, "鸿蒙电脑能否运行读者必须用的 Windows 专用软件，是选购前置条件，须在稿件里如实提示")

    return FactCard(
        model_id=model_id,
        model_name=m.name,
        ok=True,
        os_label=m.os_label,
        snapshot_date=m.snapshot_date,
        groups=groups,
        limits=limits,
        limit_fact_ids=limit_ids,
        unconfirmed=unconfirmed,
        price_lines=price_lines,
        note=("这台机器的所有参数都来自知识库快照（基准日 %s）。"
              " Agent 只能从上面「能说的」里取料；「不能说的」和「资料未确认」的项，"
              "稿件里要么不写，要么明确告诉读者去官方页面核对。" % (m.snapshot_date or "未知")),
    )
