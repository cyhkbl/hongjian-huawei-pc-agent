"""取证：先 kb.search（产生可见的检索 trace），再用结构化接口精选事实/图片/价格。"""
from __future__ import annotations

from typing import Optional
import re

from app.models import (
    EvidencePack, Fact, ImageAsset, ImageSlot, PriceRecord, Strategy, TaskSpec,
)
from app.kb.base import KnowledgeBase
from app.agent import profiles as P

FACT_MIN, FACT_MAX = 8, 14
LIMIT_MAX = 2

# 可引用的价格口径（按优先级）。预估到手价/搭配价/发布价不进入稿件，避免口径混淆。
CITABLE_TYPES = ["官方商城页面价", "当前商城页面价"]
NO_AMOUNT_HINTS = ("未公开", "询价", "下架", "无当前", "暂无")


def _search(kb: KnowledgeBase, query: str, model_id: str, limit: int = 8) -> int:
    try:
        return len(kb.search(query, model_id=model_id, limit=limit))
    except Exception:  # noqa: BLE001  检索失败不影响结构化取证；trace 里由 KB 层记录
        return 0


def citable_price(r: PriceRecord) -> bool:
    # 精确口径匹配：“（缺货）”“（未扣优惠券）”“活动页价”“预估到手价”“官网参考起价”都不进稿件
    return (r.amount is not None and r.amount > 0 and bool(r.spec) and bool(r.verified_at)
            and bool(r.url) and r.price_type in CITABLE_TYPES and "缺货" not in (r.stock or "") + (r.status or ""))


def select_prices(records: list[PriceRecord], model_id: str, limit: int = 3) -> list[PriceRecord]:
    """同一口径、同一机型、有 SKU/金额/时间/URL 的记录；没有金额的机型带 1-2 条状态记录用于如实说明。"""
    mine = [r for r in records if r.model_id == model_id]
    for ptype in CITABLE_TYPES:        # 一次只用一种口径
        ok = [r for r in mine if r.price_type == ptype and citable_price(r)]
        if ok:
            seen, out = set(), []
            for r in sorted(ok, key=lambda r: (r.amount, r.spec)):
                if r.spec in seen:
                    continue
                seen.add(r.spec)
                out.append(r)
            # 取最低、中位、最高，让读者看到“配置会改变金额”
            if len(out) > limit:
                out = [out[0], out[len(out) // 2], out[-1]]
            return out[:limit]
    status = [r for r in mine if r.amount is None and r.url]
    status.sort(key=lambda r: (0 if any(h in (r.price_type + r.status + r.stock) for h in NO_AMOUNT_HINTS) else 1, r.record_id))
    return status[:2]


def _pick_limits(all_facts: list[Fact], model_id: str, top_tags: Optional[set] = None) -> list[Fact]:
    """限制段取 1-2 条：先取“系统/软件”类 unfit（鸿蒙电脑的前置条件），再取与第一卖点同主题的 unfit。"""
    mine = [f for f in all_facts if f.model_id == model_id]
    unfit = [f for f in mine if f.kind == "unfit"]
    boundary = [f for f in mine if f.kind == "boundary" and not f.text.startswith("待核验")]
    out: list[Fact] = []
    def odd(f: Fact) -> int:       # 点名其它机型/系统的句子放后面，避免限制段里出现跨型号字样
        return 1 if re.search(r"Linux|MateBook|混为|套用|其他年份", f.text) else 0
    sw = [f for f in unfit if re.search(r"Windows|软件|驱动|兼容|插件", f.text)]
    sw.sort(key=lambda f: (odd(f), 0 if "Windows" in f.text else 1, len(f.text), f.id))
    if sw:
        out.append(sw[0])
    if top_tags:
        same = [f for f in unfit if f not in out and (P.fact_tags(f) & top_tags)]
        same.sort(key=lambda f: (odd(f), len(f.text), f.id))
        if same:
            out.append(same[0])
    for f in sorted(unfit, key=lambda f: (odd(f), f.id)) + boundary:
        if len(out) >= LIMIT_MAX:
            break
        if f not in out:
            out.append(f)
    return out[:LIMIT_MAX]


def select_facts(task: TaskSpec, strategy: Strategy, all_facts: list[Fact], model_id: str) -> list[Fact]:
    scenario = task.scenario or P.DEFAULT_SCENARIO
    platform = task.platform or P.DEFAULT_PLATFORM
    user_tag = P.tag_for_user_point(task.selling_point) if task.selling_point else None
    mine = [f for f in all_facts if f.model_id == model_id]
    by_id = {f.id: f for f in mine}
    picked: dict[str, Fact] = {}

    # 1) 身份：一条，用来在文中第一次出现型号时有据可依
    ident = [f for f in mine if f.category == "identity" and f.kind in ("card", "spec")]
    ident.sort(key=lambda f: (0 if "官方完整名称" in f.text else 1 if "操作系统" in f.text else 2, f.id))
    if ident:
        picked[ident[0].id] = ident[0]
    # 2) 策略已选的卖点事实
    for sp in strategy.selling_points:
        for fid in sp.fact_ids:
            if fid in by_id:
                picked[fid] = by_id[fid]
    # 3) 限制：同型号 unfit/boundary 一两条
    top_tags = set()
    if strategy.selling_points:
        from app.agent.strategy import label_tag
        t0 = label_tag(strategy.selling_points[0].label)
        if t0:
            top_tags = {t0}
    limits = _pick_limits(mine, model_id, top_tags)
    for f in limits:
        picked[f.id] = f
    # 4) 按场景分数补足（优先 card/spec/selling）
    rest = P.dedupe_facts(sorted([f for f in mine if f.id not in picked and f.kind in ("selling", "card", "spec", "fit", "faq")
            and f.category != "identity" and not f.text.startswith("待核验")], key=lambda f: f.id))
    have = {P.norm_text(x.text) for x in picked.values()}
    rest = [f for f in rest if P.norm_text(f.text) not in have]
    scored = []
    for f in rest:
        s, _ = P.scenario_score(f, scenario, platform, user_tag, model_id)
        scored.append((s, f))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    target = FACT_MAX if platform == "wechat_mp" else 12 if platform == "xiaohongshu" else FACT_MIN + 1
    for s, f in scored:
        if len(picked) >= target:
            break
        if s <= 0 and len(picked) >= FACT_MIN:
            break
        picked[f.id] = f
    # 5) 仍不足 8 条则不管分数补齐
    if len(picked) < FACT_MIN:
        for s, f in scored:
            if len(picked) >= FACT_MIN:
                break
            picked.setdefault(f.id, f)
    facts = list(picked.values())
    facts = facts[:FACT_MAX] if len(facts) > FACT_MAX else facts
    # 固定的稳定顺序：身份、卖点、其它、限制
    order = {f.id: i for i, f in enumerate(facts)}
    limit_ids = {f.id for f in limits}
    facts.sort(key=lambda f: (1 if f.id in limit_ids else 0, order[f.id]))
    return facts


_OFF_TOPIC = re.compile(r"创作|手写|绘")
_ALWAYS_OFF = re.compile(r"影音|游戏|娱乐")


def _img_score(img: ImageAsset, prefer: list[str], allow_creative: bool = False) -> float:
    s = 0.0
    for i, t in enumerate(prefer):
        if t in img.tags:
            s += 3.0 - i * 0.7
    if img.kind == "official":
        s += 0.8
    if img.width and img.height and min(img.width, img.height) >= 600:
        s += 0.4
    if img.source_url or img.page_url:
        s += 0.3
    if _OFF_TOPIC.search(img.caption or "") and not allow_creative:
        s -= 2.5
    if _ALWAYS_OFF.search(img.caption or ""):
        s -= 1.5
    return s


def select_images(task: TaskSpec, strategy: Strategy, imgs: list[ImageAsset], model_id: str) -> list[ImageAsset]:
    """每个 slot 一张，同型号、不重复、颜色一致；返回按 slot 顺序的列表（可能少于 slot 数，不凑数）。"""
    imgs = [i for i in imgs if i.model_id == model_id and (i.source_url or i.page_url)]
    chosen: list[ImageAsset] = []
    used: set[str] = set()
    locked_color = ""
    creative_ok = (task.scenario in ("creator", "new_launch")) or task.selling_point in ("创作", "手写") \
        or any(w in (task.selling_point or "") for w in ("手写", "触控", "创作", "笔"))

    def pick_for(slot: ImageSlot) -> Optional[ImageAsset]:
        nonlocal locked_color
        cands = [i for i in imgs if i.id not in used and (not locked_color or i.color in ("", locked_color))]
        if not cands:
            return None
        cands.sort(key=lambda i: (-_img_score(i, slot.prefer_tags, creative_ok), i.id))
        best = cands[0]
        # 候选都与偏好无关时仍取最佳（比空着好），但海报主视觉必须有官方图
        if best.color and not locked_color:
            locked_color = best.color
        return best

    for slot in strategy.image_slots:
        img = pick_for(slot)
        if img is None:
            break
        used.add(img.id)
        chosen.append(img)
    return chosen


def gather(task: TaskSpec, strategy: Strategy, kb: KnowledgeBase) -> EvidencePack:
    if not task.model_ids:
        raise ValueError("gather() 需要 task.model_ids；缺机型应在追问阶段处理")
    model_id = task.model_ids[0]
    model = kb.get_model(model_id)
    models = [model] if model else []
    sc = P.get_scenario(task.scenario)
    sp_labels = " ".join(P.TAG_LABEL.get(t, "") for t in
                         [x for x in (_label_tag(p.label) for p in strategy.selling_points) if x][:2])
    name = model.short_name if model else model_id

    # ---- 1) 可见检索：产品事实 / 场景相关 / 图片 / (价格)
    queries = [f"{name} 产品事实 {sc['label']} {sp_labels}".strip(),
               f"{name} 卖点与限制 不适用"]
    queries.append(f"{name} 官方图片 {' '.join(strategy.image_slots[0].prefer_tags) if strategy.image_slots else ''}".strip())
    if task.want_price:
        queries.append(f"{name} 官方价格 核验")
    hits = 0
    for q in queries:
        hits += _search(kb, q, model_id)

    # ---- 2) 结构化取证
    all_facts = kb.facts(model_id)
    facts = select_facts(task, strategy, all_facts, model_id)
    images = select_images(task, strategy, kb.images(model_id), model_id)
    prices: list[PriceRecord] = []
    if task.want_price:
        prices = select_prices(kb.prices(model_id), model_id)

    try:
        trace = kb.drain_trace()
    except Exception:  # noqa: BLE001
        trace = []
    return EvidencePack(models=models, facts=facts, images=images, prices=prices, trace=trace)


def _label_tag(label: str) -> Optional[str]:
    from app.agent.strategy import label_tag
    return label_tag(label)
