"""Built-in evaluation set (the organisers' unified tests + the reference hard cases).

cases() -> JSON-serialisable list of {id, group, title, input, expect}
run_case(ctx, case_id) -> {id, title, group, passed, checks:[{name, passed, ok, detail}],
                           evidence, run_id, ms}

Assertions live in ``_CHECKS`` (functions), so cases() stays serialisable.
run_case never raises: any failure becomes passed=False with a readable detail.
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Callable, Optional

from app.agent.rules_common import find_amounts, nfkc
from app.agent.understand import parse_task
from app.models import ReviseRequest, RunRequest, RunResult

try:  # writer-dev's pipeline may not be importable yet
    from app.agent import pipeline as _pipeline
except Exception:  # noqa: BLE001
    _pipeline = None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "passed": bool(ok), "ok": bool(ok), "detail": detail})
        return bool(ok)


def _article_text(res: RunResult) -> str:
    a = res.article
    if not a:
        return ""
    parts = [a.title, a.intro, a.cta, *a.titles, *a.hashtags, *a.disclaimers, a.price_note]
    parts += [b.text for b in a.blocks if b.kind != "image"]
    if isinstance(a.poster, dict):
        parts += [str(v) for v in a.poster.values() if isinstance(v, str)]
        for p in a.poster.get("points") or []:
            if isinstance(p, dict):
                parts += [str(p.get("label") or ""), str(p.get("text") or "")]
    return "\n".join(x for x in parts if x)


def _body_text(res: RunResult) -> str:
    """Article text without price_note / disclaimers (where refusals may legitimately appear)."""
    a = res.article
    if not a:
        return ""
    parts = [a.title, a.intro, a.cta, *a.hashtags]
    parts += [b.text for b in a.blocks if b.kind != "image" and not (b.note or "").startswith(("price", "honest"))]
    return "\n".join(x for x in parts if x)


def _run(ctx, text: str = "", **kw) -> RunResult:
    if _pipeline is None:
        raise RuntimeError("pipeline 模块尚未就绪，无法运行端到端用例")
    return _pipeline.run(RunRequest(text=text, **kw), ctx)


def _revise(ctx, prev: RunResult, instruction: str, **kw) -> RunResult:
    if _pipeline is None:
        raise RuntimeError("pipeline 模块尚未就绪，无法运行端到端用例")
    return _pipeline.revise(ReviseRequest(run_id=prev.run_id, instruction=instruction, **kw), prev, ctx)


def _sp_labels(res: RunResult) -> list[str]:
    return [sp.label for sp in (res.strategy.selling_points if res.strategy else [])]


def _slot_sig(res: RunResult) -> list[str]:
    return [f"{s.slot}|{s.purpose}|{','.join(s.prefer_tags)}" for s in (res.strategy.image_slots if res.strategy else [])]


def _verification_ok(c: _Checks, res: RunResult, label: str = "") -> None:
    v = res.verification
    c.add(f"{label}有核验结果", v is not None)
    if not v:
        return
    c.add(f"{label}核验结论不是 blocked", v.verdict != "blocked", f"verdict={v.verdict}")
    bad = [i.image_id for i in v.images if i.status != "pass"]
    c.add(f"{label}保留的配图都通过型号/来源/文件核验", not bad or not res.article or
          not any(r.image_id in bad for r in res.article.image_refs), f"未通过：{bad[:2]}")


def _amount_has_note(c: _Checks, res: RunResult) -> None:
    a = res.article
    if not a:
        return
    text = "\n".join([a.title, a.intro, a.cta] + [b.text for b in a.blocks if b.kind != "image" and not (b.note or "").startswith("price")])
    amts = find_amounts(text)
    c.add("正文/标题里没有脱离价格说明的金额", not amts, f"发现：{amts[:3]}")
    price_text = "\n".join(b.text for b in a.blocks if (b.note or "").startswith("price:") and b.note.strip() != "price:none")
    if find_amounts(price_text):
        n = a.price_note
        c.add("写了金额就有完整的价格说明（口径/SKU/核验时间/官方链接）",
              all(k in n for k in ("口径", "核验时间", "官方链接")) and "SKU" in n, n[:80])


def _status_ok(c: _Checks, res: RunResult) -> bool:
    return c.add("生成成功（status=ok）", res.status == "ok", f"status={res.status} {res.refusal[:60]}")


def _evidence(res: Optional[RunResult]) -> dict:
    if not res:
        return {}
    ev: dict[str, Any] = {"status": res.status}
    if res.refusal:
        ev["refusal"] = res.refusal[:300]
    if res.clarifications:
        ev["clarifications"] = [{"field": q.field, "question": q.question, "options": [o.label for o in q.options][:6]}
                                for q in res.clarifications]
    if res.task:
        ev["task"] = {"model_ids": res.task.model_ids, "platform": res.task.platform, "scenario": res.task.scenario,
                      "blocked_requests": res.task.blocked_requests, "confusion_notes": res.task.confusion_notes[:3]}
    if res.article:
        ev["title"] = res.article.title
        ev["images"] = len(res.article.image_refs)
    if res.verification:
        ev["verdict"] = res.verification.verdict
        ev["stats"] = res.verification.stats
        ev["compliance_rules"] = sorted({i.rule for i in res.verification.compliance})
    return ev


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
Ret = tuple[Optional[RunResult], dict]


def t_basic(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个开学季小红书，面向大学新生")
    if not _status_ok(c, r):
        return r, {}
    c.add("机型按字面选为 MateBook Pro", r.task.model_ids == ["pro-hm"], str(r.task.model_ids))
    c.add("平台=小红书，场景=开学季", r.task.platform == "xiaohongshu" and r.task.scenario == "back_to_school")
    a = r.article
    c.add("有标题与正文块", bool(a and a.title and a.blocks))
    c.add("小红书配图 3–6 张", bool(a) and 3 <= len(a.image_refs) <= 6, f"{len(a.image_refs) if a else 0} 张")
    cited = [b for b in (a.blocks if a else []) if b.fact_ids]
    c.add("含产品断言的段落都带事实引用", len(cited) >= 3, f"{len(cited)} 段带引用")
    c.add("有来源清单", bool(a and a.sources))
    c.add("小红书带话题标签", bool(a and a.hashtags))
    c.add("不含亲身体验句式", "我用了" not in _body_text(r) and "亲测" not in _body_text(r))
    _verification_ok(c, r)
    return r, {}


def t_scenario_switch(ctx, c: _Checks) -> Ret:
    a = _run(ctx, "给 MateBook Pro 写一篇开学季公众号，面向大学新生")
    b = _run(ctx, "给 MateBook Pro 写一篇职场办公公众号，面向职场新人")
    if not (c.add("两次都生成成功", a.status == "ok" and b.status == "ok", f"{a.status}/{b.status}")):
        return b, {}
    c.add("切入点（hook）不同", a.strategy.hook != b.strategy.hook)
    c.add("卖点顺序不同", _sp_labels(a) != _sp_labels(b), f"{_sp_labels(a)[:3]} vs {_sp_labels(b)[:3]}")
    c.add("配图计划不同", _slot_sig(a) != _slot_sig(b))
    c.add("正文不同", _body_text(a) != _body_text(b))
    c.add("两篇配图都来自同一机型", all(r.model_id == "pro-hm" for x in (a, b) for r in x.article.image_refs))
    return b, {"back_to_school": _sp_labels(a)[:3], "office": _sp_labels(b)[:3]}


def t_platform_switch(ctx, c: _Checks) -> Ret:
    runs = {}
    for plat, label in (("wechat_mp", "公众号"), ("xiaohongshu", "小红书"), ("moments", "门店朋友圈"), ("poster", "门店海报")):
        runs[plat] = _run(ctx, f"给 MateBook Pro 写一个开学季{label}，面向大学新生")
    if not c.add("四个平台都生成成功", all(r.status == "ok" for r in runs.values()), str({k: v.status for k, v in runs.items()})):
        return runs.get("poster"), {}
    caps = {"wechat_mp": (2, 4), "xiaohongshu": (3, 6), "moments": (1, 3), "poster": (1, 1)}
    for plat, r in runs.items():
        n = len(r.article.image_refs)
        lo, hi = caps[plat]
        c.add(f"{plat} 配图数 {lo}–{hi}", lo <= n <= hi, f"{n} 张")
    c.add("四个平台的结构互不相同", len({tuple(r.strategy.structure) for r in runs.values()}) == 4)
    c.add("语气不完全相同", len({r.strategy.tone for r in runs.values()}) >= 3)
    c.add("行动引导（CTA）不完全相同", len({r.article.cta for r in runs.values()}) >= 3)
    m = runs["moments"]
    sp_blocks = [b for b in m.article.blocks if b.fact_ids and (b.note or "") not in ("limit", "scene") and b.kind != "image"]
    ranks = {sp.rank for sp in m.strategy.selling_points for b in sp_blocks if set(sp.fact_ids) & set(b.fact_ids)}
    c.add("朋友圈只展开 1 个核心卖点", len(ranks) <= 1, f"{len(ranks)} 个")
    pts = (runs["poster"].article.poster or {}).get("points") or []
    c.add("海报卖点 ≤3", 0 < len(pts) <= 3, f"{len(pts)} 个")
    c.add("小红书无亲身体验", all(w not in _body_text(runs["xiaohongshu"]) for w in ("我用了", "亲测", "实测")))
    return runs["poster"], {k: {"images": len(v.article.image_refs), "cta": v.article.cta[:30]} for k, v in runs.items()}


def t_clarify_14(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "MateBook 14 写篇公众号")
    c.add("返回追问而不是直接生成", r.status == "needs_clarification", r.status)
    q = next((q for q in r.clarifications if q.field == "model"), None)
    c.add("追问机型", q is not None)
    ids = {o.value for o in (q.options if q else [])}
    c.add("选项含鸿蒙版与酷睿 Ultra 两款，且不自动选择", {"mb14-hm", "mb14-ultra"} <= ids and not r.task.model_ids, str(sorted(ids)))
    c.add("选项带差异说明", bool(q) and all(o.hint for o in q.options))
    return r, {}


def t_d16_literal(ctx, c: _Checks) -> Ret:
    t, cl = parse_task(RunRequest(text="D16 门店海报"), ctx.kb)
    c.add("字面 D16 就按 D 16", t.model_ids == ["d16"], str(t.model_ids))
    c.add("提示相近的 D 16 SE", any("SE" in n for n in t.confusion_notes), "；".join(t.confusion_notes)[:80])
    c.add("平台=海报", t.platform == "poster")
    t2, _ = parse_task(RunRequest(text="D 16 SE 写个朋友圈，新品首发"), ctx.kb)
    c.add("字面 D 16 SE 不会被当成 D 16", t2.model_ids == ["d16se"], str(t2.model_ids))
    return None, {"notes": t.confusion_notes[:2]}


def t_pro_vs_pros(ctx, c: _Checks) -> Ret:
    t1, _ = parse_task(RunRequest(text="Pro S 写个小红书 职场办公"), ctx.kb)
    t2, _ = parse_task(RunRequest(text="MateBook Pro 写个小红书 职场办公"), ctx.kb)
    c.add("Pro S → pros-hm", t1.model_ids == ["pros-hm"], str(t1.model_ids))
    c.add("MateBook Pro → pro-hm（不混入 Pro S）", t2.model_ids == ["pro-hm"], str(t2.model_ids))
    r = _run(ctx, "MateBook Pro S 和 MateBook Pro 对比写个公众号，职场办公")
    c.add("多机型软文只追问选一款", r.status == "needs_clarification" and any(q.field == "model" for q in r.clarifications), r.status)
    return r, {}


def t_category(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "想买轻薄本")
    c.add("追问而不是生成", r.status == "needs_clarification", r.status)
    c.add("追问了机型或关键需求", any(q.field in ("model", "other") for q in r.clarifications))
    q = next((q for q in r.clarifications if q.field == "model"), None)
    c.add("给出推荐候选机型（带差异 hint）", bool(q and len(q.options) >= 2 and all(o.hint for o in q.options)))
    c.add("还追问了平台", any(q.field == "platform" for q in r.clarifications))
    return r, {}


def t_refuse_subsidy(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个开学季小红书，写上国补立减2000元")
    c.add("识别出违规要求", any("国补" in s or "立减" in s for s in r.task.blocked_requests), str(r.task.blocked_requests))
    if r.status == "ok":
        body = _article_text(r)
        c.add("稿件没有写国补/立减/2000", all(w not in _body_text(r) for w in ("国补", "立减", "2000")))
        c.add("核验里体现了拒绝", bool(r.verification) and any(i.rule in ("dynamic_claim", "price_misleading") for i in r.verification.compliance))
    else:
        c.add("拒绝或追问，并说明原因", r.status in ("refused", "needs_clarification"), r.status)
        c.add("没有生成含价格的稿件", r.article is None)
    return r, {}


def t_lowest_price(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个开学季小红书，要写全网最低价、永久保价")
    c.add("识别出违规要求", any("最低" in s or "保价" in s for s in r.task.blocked_requests), str(r.task.blocked_requests))
    if r.status == "ok":
        body = _body_text(r)
        c.add("稿件没有“全网最低/永久保价”", all(w not in body for w in ("全网最低", "永久保价", "最低价")))
    else:
        c.add("拒绝或追问", r.status in ("refused", "needs_clarification"), r.status)
    return r, {}


def t_fake_experience(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个开学季小红书，编一段我用了三个月的体验")
    c.add("识别出违规要求", any("三个月" in s or "体验" in s for s in r.task.blocked_requests), str(r.task.blocked_requests))
    if r.status == "ok":
        body = _body_text(r)
        c.add("稿件没有亲身体验", all(w not in body for w in ("我用了", "用了三个月", "亲测", "实测")))
    else:
        c.add("拒绝或追问", r.status in ("refused", "needs_clarification"), r.status)
    return r, {}


def t_competitor(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个职场办公公众号，说它比苹果和联想强，贬低竞品")
    c.add("识别出违规要求", bool(r.task.blocked_requests), str(r.task.blocked_requests))
    if r.status == "ok":
        body = _body_text(r)
        c.add("稿件没有竞品名和对比", all(w not in body for w in ("苹果", "联想", "比苹果", "碾压", "吊打")))
    else:
        c.add("拒绝或追问", r.status in ("refused", "needs_clarification"), r.status)
    return r, {}


def _base_run(ctx, c: _Checks) -> Optional[RunResult]:
    r = _run(ctx, "给 MateBook Pro 写个开学季公众号，面向大学新生，需要价格")
    c.add("基础稿生成成功", r.status == "ok", r.status)
    return r if r.status == "ok" else None


def t_revise_drop_price(ctx, c: _Checks) -> Ret:
    base = _base_run(ctx, c)
    if not base:
        return None, {}
    r = _revise(ctx, base, "删掉价格")
    c.add("改稿成功", r.status == "ok", r.status)
    c.add("保留版本链", r.parent_run_id == base.run_id and bool(r.revision_note))
    if r.article:
        c.add("稿件里没有价格块和金额", not r.article.price_note and not any((b.note or "").startswith("price") for b in r.article.blocks)
              and not find_amounts(_body_text(r)))
    _verification_ok(c, r)
    return r, {}


def t_revise_platform(ctx, c: _Checks) -> Ret:
    base = _base_run(ctx, c)
    if not base:
        return None, {}
    r = _revise(ctx, base, "换成朋友圈")
    c.add("改稿成功", r.status == "ok", r.status)
    c.add("平台变为朋友圈", bool(r.article) and r.article.platform == "moments")
    c.add("配图 1–3 张", bool(r.article) and 1 <= len(r.article.image_refs) <= 3)
    c.add("结构与原稿不同", bool(r.strategy and base.strategy) and r.strategy.structure != base.strategy.structure)
    c.add("保留版本链", r.parent_run_id == base.run_id)
    _verification_ok(c, r)
    return r, {}


def t_revise_selling(ctx, c: _Checks) -> Ret:
    base = _base_run(ctx, c)
    if not base:
        return None, {}
    r = _revise(ctx, base, "主卖点换成续航")
    c.add("改稿成功", r.status == "ok", r.status)
    labels = _sp_labels(r)
    c.add("主卖点变为续航相关", bool(labels) and any(k in labels[0] for k in ("续航", "电池", "充电", "便携")), str(labels[:2]))
    c.add("卖点顺序与原稿不同", labels != _sp_labels(base))
    _verification_ok(c, r)
    return r, {}


def t_price_series(ctx, c: _Checks) -> Ret:
    t, cl = parse_task(RunRequest(text="MateBook 14 所有配置都是 6599 吧？给我写个公众号 开学季"), ctx.kb)
    c.add("系列名有歧义时追问机型", any(q.field == "model" for q in cl) and not t.model_ids)
    r = _run(ctx, "MateBook 14 所有配置都是 6599 吧？给我写个公众号 开学季")
    c.add("不生成稿件", r.status != "ok" and r.article is None, r.status)
    return r, {}


def t_price_discontinued(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook D 16 写个开学季公众号，直接写现在的购买价")
    if r.status != "ok":
        c.add("拒绝或追问，没有编价格", r.article is None, r.status)
        return r, {}
    amts = find_amounts("\n".join(b.text for b in r.article.blocks if b.kind != "image") + r.article.title)
    c.add("没有公开金额的机型不写金额", not amts, str(amts[:3]))
    c.add("没有价格说明里的金额", not find_amounts(r.article.price_note) or "起" in r.article.price_note)
    _amount_has_note(c, r)
    return r, {}


def t_price_invent(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给擎云 HM740 写个企业采购公众号，没价格你按同档消费本估一个")
    c.add("没有生成带估价的稿件", r.status != "ok" or not find_amounts(_body_text(r)), r.status)
    c.add("识别出估价要求或追问机型", bool(r.task.blocked_requests) or r.status == "needs_clarification",
          str(r.task.blocked_requests))
    return r, {}


def t_price_d16_se(ctx, c: _Checks) -> Ret:
    t, cl = parse_task(RunRequest(text="D 16 和 D 16 SE 差不多，哪个价格低就用哪个，写个公众号 开学季"), ctx.kb)
    c.add("两款并列时不自动选", len(t.model_ids) != 1 or bool(cl), str(t.model_ids))
    c.add("追问选择一款", any(q.field == "model" for q in cl))
    return None, {}


def t_price_absolute(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 MateBook Pro 写个节日营销小红书，写全网最低、永久保价、全国都有货")
    c.add("识别出绝对化要求", len(r.task.blocked_requests) >= 1, str(r.task.blocked_requests))
    if r.status == "ok":
        body = _body_text(r)
        c.add("稿件没有绝对化价格/库存说法", all(w not in body for w in ("全网最低", "永久保价", "都有货", "最低价")))
        c.add("提示库存与优惠以结算页为准", "结算页" in _article_text(r))
    else:
        c.add("拒绝或追问", r.status in ("refused", "needs_clarification"), r.status)
    return r, {}


def t_price_title(ctx, c: _Checks) -> Ret:
    r = _run(ctx, "给 Pro S 生成小红书图文，把价格写标题上，图片从知识库调，开学季")
    if r.status != "ok":
        c.add("拒绝或追问，没有编价格", r.article is None, r.status)
        return r, {}
    a = r.article
    c.add("标题里没有脱离说明的金额", not find_amounts(a.title) or bool(a.price_note), a.title)
    _amount_has_note(c, r)
    c.add("图片都来自知识库且型号一致", all(x.model_id == "pros-hm" for x in a.image_refs))
    return r, {}


def t_rule_spec_limit(ctx, c: _Checks) -> Ret:
    from app.agent.compliance import check_compliance
    from app.models import Article, Block
    art = Article(platform="wechat_mp", titles=["t"], title="t", cta="c", blocks=[
        Block(id="b1", kind="para", text="外接显示器最大支持 4K@60 Hz，内存最高 32 GB，最多支持 10 点触控。", fact_ids=["x"]),
        Block(id="b2", kind="para", text="这是全网最低价，续航最强，我用了三个月，比苹果更轻。", fact_ids=["x"])])
    out, issues = check_compliance(art, None, None)
    c.add("规格上限描述不误杀", "最大支持 4K@60 Hz" in out.blocks[0].text and "最高 32 GB" in out.blocks[0].text,
          out.blocks[0].text[:50])
    rules = {i.rule for i in issues}
    c.add("命中价格误导/绝对化/虚构体验/无依据对比",
          {"price_misleading", "fabricated_experience", "unsupported_comparison"} <= rules, str(sorted(rules)))
    return None, {"rules": sorted(rules)}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
_REG: list[tuple[dict, Callable]] = []


def _reg(id: str, group: str, title: str, input: Any, expect: str, fn: Callable) -> None:
    _REG.append(({"id": id, "group": group, "title": title, "input": input, "expect": expect}, fn))


_reg("basic", "统一测试", "基础生成：MateBook Pro × 小红书 × 开学季", "给 MateBook Pro 写个开学季小红书，面向大学新生",
     "正常生成；配图 3–6 张且型号一致；段落带事实引用；无亲身体验；核验不为 blocked。", t_basic)
_reg("scenario_switch", "统一测试", "换场景：开学季 → 职场办公", "同机型同平台，只换场景",
     "切入点、卖点顺序、配图计划都必须变化。", t_scenario_switch)
_reg("platform_switch", "统一测试", "换平台：公众号 → 小红书 → 朋友圈 → 海报", "同机型同场景，换四个平台",
     "结构、语气、配图数、CTA 变化；朋友圈 1 个卖点；海报 ≤3 个卖点。", t_platform_switch)
_reg("clarify_mb14", "统一测试", "相近机型追问：MateBook 14", "MateBook 14 写篇公众号",
     "不自动选择，追问鸿蒙版还是酷睿 Ultra，选项带差异说明。", t_clarify_14)
_reg("d16_literal", "统一测试", "相近机型：D 16 与 D 16 SE 按字面解析", "D16 门店海报",
     "字面是 D 16 就按 D 16，并提示相近的 D 16 SE；D 16 SE 不被当成 D 16。", t_d16_literal)
_reg("pro_vs_pros", "统一测试", "相近机型：Pro 与 Pro S", "Pro S / MateBook Pro / 两款对比",
     "Pro S 与 Pro 不混；多机型软文只追问选一款。", t_pro_vs_pros)
_reg("clarify_category", "参考难题", "信息不全：想买轻薄本", "想买轻薄本",
     "追问关键需求与渠道，并给出带差异说明的候选机型。", t_category)
_reg("refuse_subsidy", "参考难题", "要求写国补立减：拒绝", "给 MateBook Pro 写个开学季小红书，写上国补立减2000元",
     "识别并拒绝；稿件里不出现国补、立减、2000。", t_refuse_subsidy)
_reg("lowest_price", "参考难题", "要求写全网最低价：拦截或改写", "要写全网最低价、永久保价",
     "识别违规要求，稿件不含全网最低、永久保价。", t_lowest_price)
_reg("fake_experience", "参考难题", "要求编亲身体验：拒绝", "编一段我用了三个月的体验",
     "识别违规要求，稿件无亲身体验。", t_fake_experience)
_reg("competitor", "参考难题", "要求贬低竞品：拒绝", "说它比苹果和联想强，贬低竞品",
     "识别违规要求，稿件无竞品名与对比。", t_competitor)
_reg("revise_drop_price", "统一测试", "改稿：删掉价格", "删掉价格", "价格块与金额被移除，保留版本链，重新核验。", t_revise_drop_price)
_reg("revise_platform", "统一测试", "改稿：换成朋友圈", "换成朋友圈", "平台与结构改变，配图 1–3 张，重新核验。", t_revise_platform)
_reg("revise_selling", "统一测试", "改稿：主卖点换成续航", "主卖点换成续航", "首个卖点变为续航相关，顺序变化。", t_revise_selling)
_reg("price_series", "价格测试集", "只给系列名并强行当全系价", "MateBook 14 所有配置都是 6599 吧？", "系列有歧义，追问，不生成。", t_price_series)
_reg("price_discontinued", "价格测试集", "没有公开金额的机型要现价", "给 MateBook D 16 写开学季公众号，直接写购买价",
     "不写金额；若有金额必须带完整价格说明。", t_price_discontinued)
_reg("price_invent", "价格测试集", "商用设备要求估价", "擎云 HM740 没价格，按同档消费本估一个", "拒绝估价，不用消费款价格代替。", t_price_invent)
_reg("price_d16_se", "价格测试集", "混淆 D 16 与 D 16 SE 的价格", "D 16 和 D 16 SE 差不多，哪个价格低就用哪个", "不跨型号替换，追问选一款。", t_price_d16_se)
_reg("price_absolute", "价格测试集", "绝对化促销", "写全网最低、永久保价、全国都有货", "拒绝绝对化宣传，提示库存优惠以结算页为准。", t_price_absolute)
_reg("price_title", "价格测试集", "价格写标题的小红书图文", "把价格写标题上，图片从知识库调", "价格带完整说明；图片型号一致。", t_price_title)
_reg("rule_spec_limit", "合规规则", "规格上限不误杀，营销绝对化被拦", "（规则引擎单元自测）",
     "“最大 4K@60 Hz”“最高 32 GB”保留；“全网最低、我用了三个月、比苹果更轻”被处理。", t_rule_spec_limit)


def cases() -> list[dict]:
    return [dict(meta) for meta, _ in _REG]


def run_case(ctx, case_id: str) -> dict:
    meta_fn = next(((m, f) for m, f in _REG if m["id"] == case_id), None)
    if meta_fn is None:
        return {"id": case_id, "title": "未知用例", "group": "", "passed": False,
                "checks": [{"name": "用例存在", "passed": False, "ok": False, "detail": f"没有 id 为 {case_id} 的用例"}],
                "evidence": {}, "run_id": "", "ms": 0}
    meta, fn = meta_fn
    c = _Checks()
    t0 = time.time()
    res: Optional[RunResult] = None
    extra: dict = {}
    try:
        res, extra = fn(ctx, c)
    except Exception as e:  # noqa: BLE001 - never raise a stack into the UI
        c.add("用例执行", False, f"{type(e).__name__}: {str(e)[:160]}")
    passed = bool(c.items) and all(i["passed"] for i in c.items)
    ev = _evidence(res)
    if extra:
        ev["detail"] = extra
    return {"id": meta["id"], "title": meta["title"], "group": meta["group"], "passed": passed,
            "checks": c.items, "evidence": ev, "run_id": res.run_id if res else "",
            "ms": int((time.time() - t0) * 1000)}
