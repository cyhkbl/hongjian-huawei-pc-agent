"""场景 × 平台 × 型号 → 可解释的 Strategy。

卖点排序 = 场景权重 + 型号适配加成 + 平台微调 + 资料可得性（KB 里有没有该标签的事实）；
用户指定卖点时覆盖，并在 rationale 里说明。rationale 逐条引用 Fact id。
"""
from __future__ import annotations

import re
from typing import Optional

from app.models import (
    Fact, ImageSlot, ProductModel, SellingPointPlan, Strategy, TaskSpec,
)
from app.agent import profiles as P

POSITIVE_KINDS = ("selling", "card", "spec", "fit", "faq")
LABEL_SEP = "｜"
_TAG_BY_LABEL = {v: k for k, v in P.TAG_LABEL.items()}

# 场景 → 各平台建议图数（均落在平台区间内；换场景图数/图位也会变）
IMG_COUNT = {
    "wechat_mp": dict(back_to_school=3, office=3, creator=4, home_upgrade=3, enterprise_procurement=3,
                      store_visit=2, new_launch=4, festival=3),
    "xiaohongshu": dict(back_to_school=5, office=4, creator=6, home_upgrade=4, enterprise_procurement=3,
                        store_visit=3, new_launch=5, festival=4),
    "moments": dict(back_to_school=2, office=2, creator=3, home_upgrade=2, enterprise_procurement=2,
                    store_visit=1, new_launch=3, festival=2),
    "poster": dict(),
}

IMG_ZH = {"appearance": "外观", "scene": "场景", "display": "屏幕", "ports": "接口", "detail": "细节", "collab": "协同", "performance": "性能", "color": "配色"}

SLOT_NAMES = {
    "wechat_mp": ["导语之后", "第1节标题下", "第2节标题下", "第3节标题下"],
    "xiaohongshu": ["封面", "场景图", "细节1", "细节2", "细节3", "收尾图"],
    "moments": ["主图", "细节图", "补充图"],
    "poster": ["主视觉"],
}


def label_tag(label: str) -> Optional[str]:
    """从 SellingPointPlan.label 还原卖点标签（label 形如“屏幕｜…”）。"""
    head = (label or "").split(LABEL_SEP, 1)[0]
    return _TAG_BY_LABEL.get(head)


def short_snippet(text: str, n: int = 22) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.split(r"[。；;]", t)[0]
    return t if len(t) <= n else t[:n].rstrip("，, ") + "…"


def _positive(pool: list[Fact], model_id: str) -> list[Fact]:
    ok = [f for f in pool if f.model_id == model_id and f.kind in POSITIVE_KINDS and f.category != "identity"
          and not f.text.startswith("待核验")]
    return P.dedupe_facts(sorted(ok, key=lambda f: (-P.KIND_RANK.get(f.kind, 0.5), f.id)))


# 人设 → 卖点偏好偏移。同一场景下，不同人设先讲什么不一样：
# 导购先讲顾客能摸到的（便携/屏幕），学长先讲学生真正愁的（续航/接口），
# 同事先讲场景（协同/AI），买手先讲有口径可查的（屏幕参数/性能）。
_PERSONA_TAG_NUDGE = {
    "counter": {"portable": 0.30, "display": 0.20, "ports": 0.15},
    "senior": {"battery": 0.30, "ports": 0.20, "study": 0.15},
    "neighbor": {"collab": 0.25, "ai": 0.20, "office": 0.20},
    "buyer": {"display": 0.25, "performance": 0.25, "storage": 0.15},
}


def persona_shift(task: TaskSpec) -> int:
    """从 extras 里读人设偏移：persona:<key>:<shift>。

    偏移由 persona_run 按「第几个人设」传入，保证挑中的 N 个人设
    拿到互不相同的 hook 与标题候选——不靠哈希，因为确定性哈希会让多个人设撞车。
    """
    for e in task.extras or []:
        if e.startswith("persona:"):
            parts = e.split(":")
            if len(parts) >= 3 and parts[2].strip().isdigit():
                return int(parts[2].strip())
    return 0


def _persona_of(task: TaskSpec):
    """从 task.extras 里取人设（persona:<key>），并带上该人设的语气与受众覆盖。"""
    key = ""
    for e in task.extras or []:
        if e.startswith("persona:"):
            key = e.split(":")[1].strip()
            break
    if not key:
        return None
    from app.agent.personas import PERSONAS  # noqa: PLC0415
    p = PERSONAS.get(key)
    if not p:
        return None
    return {"key": key, **p}


def pick_hook(scenario: str, platform: str, model_id: str, seed: str = "",
              shift: int = 0) -> dict:
    """按人设偏移取 hook。shift 直接决定取第几个，避开哈希撞车。"""
    sc = P.get_scenario(scenario)
    hooks = list(sc["hooks"])
    if not hooks:
        raise ValueError(f"场景 {scenario} 没有配置 hook")
    if shift:
        return hooks[shift % len(hooks)]
    return P.pick(hooks, scenario, platform, model_id, seed)


def _tag_candidates(pos: list[Fact], scenario: str, platform: str, model_id: str,
                    user_tag: Optional[str]):
    """返回 [(score, tag, facts_sorted)]，按得分降序。"""
    sc = P.get_scenario(scenario)
    fit = P.model_fit(model_id)
    nudge = P.PLATFORM_TAG_NUDGE.get(platform, {})
    by_tag: dict[str, list[Fact]] = {}
    for f in pos:
        for t in P.fact_tags(f):
            if t in P.TAG_LABEL:
                by_tag.setdefault(t, []).append(f)
    out = []
    for tag, facts in by_tag.items():
        w = sc["weights"].get(tag, 0.0)
        bonus = fit.get("bonus", {}).get(tag, 0.0)
        if w == 0 and bonus == 0 and tag != user_tag:
            continue
        avail = min(1.0, 0.45 + 0.2 * len(facts))
        quality = max(P.KIND_RANK.get(f.kind, 0.5) for f in facts)
        score = (w + bonus + nudge.get(tag, 0.0)) * avail * (0.7 + 0.3 * quality)
        if tag == user_tag:
            score += 10.0
        strong = [f for f in facts if tag in P.strong_tags(f)]
        if strong:                      # 有“本职”事实时，只用本职事实，避免关键词误挂
            facts = strong
        facts.sort(key=lambda f: (-P.KIND_RANK.get(f.kind, 0.5), len(P.fact_tags(f)), f.id))
        facts = P.dedupe_facts(facts)
        # 同一张卡的事实挨在一起，限定语才不会拖进别张卡的条件
        card = lambda f: f.id.rsplit(":", 1)[0]
        lead_card = card(facts[0])
        facts = [f for f in facts if card(f) == lead_card] + [f for f in facts if card(f) != lead_card]
        out.append((round(score, 4), tag, facts))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def _n_points(task: TaskSpec, platform: str, scenario: str) -> int:
    pf = P.get_platform(platform)
    sc = P.get_scenario(scenario)
    if sc.get("single_point") or platform == "moments":
        return 1
    n = pf["max_points"]
    if task.length_hint == "短":
        n = min(n, 2)
    return n


def build_strategy(task: TaskSpec, models: list[ProductModel], pool: list[Fact]) -> Strategy:
    scenario = task.scenario or P.DEFAULT_SCENARIO
    platform = task.platform or P.DEFAULT_PLATFORM
    sc, pf = P.get_scenario(scenario), P.get_platform(platform)
    model = models[0] if models else None
    model_id = model.model_id if model else (task.model_ids[0] if task.model_ids else "")
    model_name = model.short_name if model else "该机型"
    fit = P.model_fit(model_id)
    persona = _persona_of(task)
    rationale: list[str] = []

    pos = _positive(pool, model_id)
    user_tag = P.tag_for_user_point(task.selling_point) if task.selling_point else None
    persona_nudge = _PERSONA_TAG_NUDGE.get(persona["key"], {}) if persona else {}
    cands = _tag_candidates(pos, scenario, platform, model_id, user_tag)
    if persona_nudge:
        # 人设偏好只影响排序，不动事实本身
        bumped = [(score + persona_nudge.get(tag, 0.0), tag, facts) for score, tag, facts in cands]
        bumped.sort(key=lambda x: -x[0])
        cands = bumped

    # ---- 卖点：按分数取前 N，事实不重复
    n_points = _n_points(task, platform, scenario)
    used: set[str] = set()
    plans: list[SellingPointPlan] = []
    chosen_scores: list[tuple[float, str]] = []
    for score, tag, facts in cands:
        fresh = [f for f in facts if f.id not in used]
        if not fresh:
            continue
        take = fresh[:2] if platform in ("moments", "poster") else fresh[:3]
        used.update(f.id for f in take)
        lead = take[0]
        label = f"{P.TAG_LABEL[tag]}{LABEL_SEP}{short_snippet(lead.text)}"
        why = sc["why"].get(tag) or f"{P.TAG_LABEL[tag]}在“{sc['label']}”场景下的权重较高（{sc['weights'].get(tag, 0):.2f}）"
        if fit.get("bonus", {}).get(tag):
            why += "；该机型在这一项上有适配加成"
        plans.append(SellingPointPlan(rank=len(plans) + 1, label=label, fact_ids=[f.id for f in take], why=why))
        chosen_scores.append((score, tag))
        if len(plans) >= n_points:
            break

    # ---- 解释：切入点 / 排序 / 图 / CTA
    hook = pick_hook(scenario, platform, model_id, task.selling_point,
                     shift=persona_shift(task))
    rationale.append(
        f"切入点：选“{hook['angle']}”。因为“{sc['label']}”场景的读者处于“{sc['stage']}”，"
        f"最大的卡点是“{sc['pains'][0]}”；这个开场不含任何产品事实，只先让读者认出自己。")

    if user_tag and any(t == user_tag for _, t in chosen_scores):
        top = plans[0]
        rationale.append(
            f"卖点排序：用户指定了“{task.selling_point}”，覆盖场景默认排序，把“{P.TAG_LABEL[user_tag]}”排第一"
            f"（依据 {'、'.join(top.fact_ids)}）。其余卖点按“{sc['label']}”场景权重依次排列。")
    elif task.selling_point and not user_tag:
        rationale.append(f"用户写了“{task.selling_point}”，但无法映射到已知卖点标签，仍按场景默认排序，并在待确认中说明。")
    elif task.selling_point:
        rationale.append(f"用户指定的“{task.selling_point}”在 KB 中没有可引用的事实，未覆盖排序，按场景权重选卖点。")

    if plans:
        top = plans[0]
        top_tag = label_tag(top.label) or ""
        rationale.append(
            f"卖点排序：第一位“{P.TAG_LABEL.get(top_tag, top.label)}”，"
            f"{top.why}（依据 {'、'.join(top.fact_ids)}）。")
        if len(plans) > 1:
            rest = "；".join(
                f"第{p.rank}位“{P.TAG_LABEL.get(label_tag(p.label) or '', p.label)}”（{'、'.join(p.fact_ids)}）：{p.why}"
                for p in plans[1:])
            rationale.append("其余排序：" + rest + "。")
        if len(cands) > len(plans):
            dropped = [P.TAG_LABEL[t] for _, t, _f in cands[len(plans):len(plans) + 2]]
            reason = "门店到访只放大一个核心卖点" if sc.get("single_point") else \
                f"{pf['label']}最多展开 {pf['max_points']} 个卖点，一次说太多读者记不住"
            rationale.append(f"舍弃的卖点：{'、'.join(dropped)}。原因：{reason}。")
    else:
        rationale.append("资料不足：KB 里没有找到可用于该场景的卖点事实，稿件只写已确认的信息，并在待确认里提示。")

    if platform == "poster":
        count = 1
    else:
        base = IMG_COUNT[platform].get(scenario, pf["img_range"][0])
        lo, hi = pf["img_range"]
        count = max(lo, min(hi, base))
        if task.length_hint == "短":
            count = max(lo, count - 1)
        elif task.length_hint == "长":
            count = min(hi, count + 1)

    names = SLOT_NAMES[platform]
    slots: list[ImageSlot] = []
    prefs = list(sc["img_pref"])
    sp_tags = [label_tag(p.label) for p in plans if label_tag(p.label)]
    for i in range(count):
        slot = names[i] if i < len(names) else f"配图{i + 1}"
        if platform == "poster":
            tags = ["appearance"] if scenario not in ("creator", "new_launch") else ["display", "appearance"]
            if sp_tags:
                tags = P.TAG_IMG.get(sp_tags[0], tags)[:1] + tags
            slots.append(ImageSlot(slot=slot, purpose="海报主视觉：同型号官方图，按原比例展示不拉伸", prefer_tags=tags[:3]))
        elif i == 0:
            first = prefs[0]
            purpose = {"appearance": "开篇用外观图交代这是哪一台电脑", "scene": "开篇用场景图让读者代入",
                       "display": "开篇用屏幕图先抓住视线", "ports": "开篇用接口图说明这台电脑能接什么"}.get(first, "开篇配图")
            slots.append(ImageSlot(slot=slot, purpose=purpose, prefer_tags=[first] + P.TAG_IMG.get(sp_tags[0], [])[:1] if sp_tags and scenario in ("creator", "new_launch") else [first]))
        else:
            k = i - 1
            if k < len(sp_tags):
                t = sp_tags[k]
                slots.append(ImageSlot(slot=slot, purpose=f"配合卖点“{P.TAG_LABEL[t]}”，让读者看到对应的部位或画面",
                                       prefer_tags=P.TAG_IMG.get(t, ["detail"])))
            else:
                t2 = prefs[min(i, len(prefs) - 1)]
                slots.append(ImageSlot(slot=slot, purpose="补充细节或使用场景，避免与前图重复", prefer_tags=[t2, "detail"]))
    rationale.append(
        f"配图计划：{pf['label']}取 {count} 张（平台区间 {pf['img_range'][0]}–{pf['img_range'][1]}），"
        f"按“{sc['label']}”偏好依次选{'、'.join(IMG_ZH.get(x, x) for x in prefs[:3])}类图；每个卖点配一张能对应上的画面，"
        f"全部限定为 {model_name} 的官方图，颜色保持一致。")

    rationale.append(f"CTA：{pf['label']}采用“{pf['cta_style']}”；{sc['label']}场景下读者处于“{sc['stage']}”，"
                     f"所以只给一个动作：{sc['cta'][platform]}")

    if model:
        if model.os_family == "harmonyos":
            rationale.append(f"系统提示：{model.name} 是鸿蒙电脑，{P.HARMONY_SOFTWARE_NOTE}。稿件会在“限制”段引用 KB 的“不适用/需先验证”事实。")
        else:
            rationale.append(f"系统提示：{model.name} 运行 {model.os_label}，{P.WINDOWS_SOFTWARE_NOTE}。")
        if fit.get("note"):
            rationale.append(f"机型适配：{fit['note']}。")
        careful = fit.get("careful", {}).get(scenario)
        if careful:
            rationale.append(f"需谨慎：{careful}。")
        elif scenario in fit.get("good", []):
            rationale.append(f"机型与场景匹配：{model_name} 与“{sc['label']}”场景是资料里的常见搭配。")
    for tb in sc["taboo"][:2]:
        rationale.append(f"场景禁忌：{tb}。")

    sections = P.resolve_sections(platform, scenario, len(plans), task.want_price, task.length_hint, task.extras)
    structure = []
    sec_labels = P.SECTION_LABEL.get(platform, {})
    for k in sections:
        if k[0] == "p" and k[1:].isdigit():
            idx = int(k[1:]) - 1
            structure.append(f"卖点{idx + 1}：{plans[idx].label.split(LABEL_SEP)[0]}" if idx < len(plans) else f"卖点{idx + 1}")
        else:
            structure.append(sec_labels.get(k, k))

    length = pf["length"]
    if task.length_hint == "短":
        length = f"短版：{length.split('（')[0]} 压缩约 40%"
    elif task.length_hint == "长":
        length = f"长版：{length.split('（')[0]} 上限"

    tone = pf["tone"]
    if persona:
        tone = f"{persona['tone']}（人设：{persona['name']}）"
    if sc.get("single_point"):
        tone += "；本场景只放大一个核心卖点"
    if persona:
        rationale.insert(0, f"人设：{persona['name']}——{persona['tagline']}。同一批知识库事实，换人设重写，避免千篇一律。")
        if persona.get("extras"):
            rationale.append("人设约束：" + "；".join(persona["extras"]) + "。")

    return Strategy(
        scenario_label=sc["label"], platform_label=pf["label"],
        audience=(persona["audience"] if persona and persona.get("audience") else (task.audience or sc["audience"])),
        usage_scene=sc["usage_scene"], purchase_stage=sc["stage"],
        pain_points=list(sc["pains"]), goal=sc["goal"],
        hook=f"{hook['angle']}：{hook['short']}", tone=tone,
        structure=structure, length=length, image_count=count, image_slots=slots,
        cta=sc["cta"][platform], selling_points=plans, rationale=rationale,
    )
