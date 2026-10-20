"""一题三解：同一个任务，用不同「人设」各写一篇。

评委 tip 里的原话：原系统「生产不出能够吸引不同人群的推文，AI 感足，千篇一律，
送到几千家门店后根本没办法发送」。

所以这里不做「换几个词」，而是换整个人设：谁在说、对谁说、用什么口气说、
先讲什么后讲什么、要不要讲限制。人设决定 hook 句式、卖点顺序、语气词和结尾动作，
同一批知识库事实能长出观感完全不同的稿子。

人设全部来自对真实门店场景的观察，不是凭空编的：
- 柜哥导购：在店里跟顾客面对面，短、直接、一个卖点
- 学姐/学长：给学生讲经验，口语、带取舍、敢说缺点
- 隔壁同事：像同事间推荐，生活化、不提参数提场景
- 严选买手：偏测评口吻，重口径和条件，适合新品首发
"""
from __future__ import annotations

import json
import time
from typing import Optional

from app.agent import profiles as P
from app.agent.pipeline import _new_run_id, _now_iso
from app.context import AppContext
from app.models import (
    EngineInfo, PersonaRunRequest, PersonaRunResult, PlatformId, RunRequest,
    RunResult, ScenarioId,
)


# 人设定义：name 用于展示，其余是注入 pipeline 的提示
PERSONAS: dict[str, dict] = {
    "counter": {
        "name": "柜哥导购",
        "tagline": "在店里面对面讲，短、直接、只讲一个卖点",
        "audience": "到店看机器的顾客",
        "selling_point": "",                      # 由策略决定
        "extras": ["语气像柜台销售：先问需求再讲卖点，不堆参数", "结尾给一个到店动作"],
        "tone": "直接、亲切、不绕弯",
        "best_for": ["store_visit", "office", "home_upgrade"],
    },
    "senior": {
        "name": "学长学姐",
        "tagline": "给学生讲踩坑经验，口语、敢说缺点",
        "audience": "即将入学或返校的学生",
        "selling_point": "",
        "extras": ["用学长学姐的口吻：可以说「我当时也纠结过」这种假设性表达，但不能编造真实使用经历",
                   "要讲一条真实的取舍或限制，别只说好话"],
        "tone": "口语、像聊天、带主观偏好",
        "best_for": ["back_to_school", "creator", "home_upgrade"],
    },
    "neighbor": {
        "name": "隔壁同事",
        "tagline": "同事间随口推荐，少提参数多提场景",
        "audience": "同事与朋友",
        "selling_point": "",
        "extras": ["像同事中午吃饭时随口推荐：先说场景再说机器，参数最多提两个",
                   "不要出现「综上所述」「值得一提的是」这类书面语"],
        "tone": "生活化、轻松、像发微信",
        "best_for": ["office", "home_upgrade", "festival"],
    },
    "buyer": {
        "name": "严选买手",
        "tagline": "偏测评口吻，重口径和条件，适合新品",
        "audience": "关注参数与性价比的用户",
        "selling_point": "",
        "extras": ["买手口吻：每个数字都带口径和条件，明确说出「这一项资料里没有确认」",
                   "新品内容要把价格与权益的依据讲清楚，没有依据就说不写"],
        "tone": "克制、重依据、像横评",
        "best_for": ["new_launch", "creator", "enterprise_procurement"],
    },
}

DEFAULT_ORDER = ["counter", "senior", "buyer"]


def personas_for(scenario: str, platform: str) -> list[str]:
    """挑三个最合适的人设，顺序稳定。

    返回顺序就是界面上从左到右的顺序；偏移量按这个顺序错开，
    保证同一任务下三篇拿到不同的 hook 与标题候选。
    """
    fits = [k for k, v in PERSONAS.items() if scenario in v.get("best_for", [])]
    rest = [k for k in DEFAULT_ORDER if k not in fits]
    return (fits + rest)[:3]


def persona_run(req: PersonaRunRequest, ctx: AppContext, on_stage=None) -> PersonaRunResult:
    """同一任务用不同人设各写一篇。

    做法：检索、事实核验、图片核验、合规检查只跑一次（这些与人设无关），
    人设只影响「策略」和「文案」两层。这样三篇的总耗时接近一次流水线，
    而不是三倍——线上才能塞进网关超时。
    """
    from app.agent.understand import parse_task  # noqa: PLC0415
    from app.agent.strategy import build_strategy  # noqa: PLC0415
    from app.agent.retrieve import gather  # noqa: PLC0415
    from app.agent.compose import compose_with_composer  # noqa: PLC0415
    from app.agent.verify import check_facts, check_images, build_verification  # noqa: PLC0415
    from app.agent.compliance import check_compliance  # noqa: PLC0415
    from app.models import RunResult, TaskSpec  # noqa: PLC0415

    base_req = RunRequest(text=req.text, model_ids=list(req.model_ids),
                          scenario=req.scenario, platform=req.platform,
                          audience=req.audience, selling_point=req.selling_point)
    task, _clar = parse_task(base_req, ctx.kb)
    scenario = task.scenario or req.scenario or P.DEFAULT_SCENARIO
    platform = task.platform or req.platform or P.DEFAULT_PLATFORM

    keys = req.personas or personas_for(scenario, platform)
    if not task.model_ids:
        return PersonaRunResult(
            persona_set_id=f"ps-{int(time.time()*1000)}",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            scenario=scenario, platform=platform,
            personas=[{"key": k, "name": PERSONAS[k]["name"], "tagline": PERSONAS[k]["tagline"]}
                      for k in keys if k in PERSONAS],
            runs=[], diff={"rows": {}, "varies": [], "identical": [],
                           "note": "没有识别到机型，无法生成。"})

    model = ctx.kb.get_model(task.model_ids[0])
    pool = ctx.kb.facts(task.model_ids[0])

    runs: list[RunResult] = []
    shared_evidence = None            # 第一篇检索到的证据，后续复用
    for i, key in enumerate(keys):
        p = PERSONAS.get(key)
        if not p:
            continue
        t = task.model_copy(update={
            "scenario": scenario,
            "platform": platform,
            "audience": p["audience"] if not req.audience else req.audience,
            "selling_point": p["selling_point"],
            # 第三个字段是位置索引：保证 N 个人设的 hook 与标题候选错开
            "extras": list(dict.fromkeys([f"persona:{key}:{i}"] + list(p["extras"]))),
        })
        try:
            strategy = build_strategy(t, [model] if model else [], pool)
            if shared_evidence is None:
                shared_evidence = gather(t, strategy, ctx.kb)
            evidence = shared_evidence
            article = compose_with_composer(t, strategy, evidence)
            article, fact_items, pending = check_facts(article, evidence, ctx.kb)
            article, image_items = check_images(article, ctx.kb)
            article, issues = check_compliance(article, t, strategy)
            verification = build_verification(fact_items, image_items, issues, pending, article)
            runs.append(RunResult(
                run_id=_new_run_id(), created_at=_now_iso(),
                status="ok" if article else "blocked",
                task=t, strategy=strategy, evidence=evidence, article=article,
                verification=verification,
                engine=EngineInfo(writer="composer", note="一题三解：共享检索与核验，人设只影响策略与文案"),
                timeline=[],
            ))
        except Exception as e:  # noqa: BLE001  单篇失败不影响其余
            runs.append(RunResult(
                run_id=_new_run_id(), created_at=_now_iso(), status="blocked",
                task=t, refusal=f"这一篇生成失败：{type(e).__name__}: {str(e)[:120]}",
                engine=EngineInfo(writer="composer", note="一题三解"),
                timeline=[],
            ))

    return PersonaRunResult(
        persona_set_id=f"ps-{int(time.time()*1000)}",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        scenario=scenario,
        platform=platform,
        personas=[{"key": k, "name": PERSONAS[k]["name"], "tagline": PERSONAS[k]["tagline"]}
                  for k in keys if k in PERSONAS],
        runs=runs,
        diff=_style_diff(runs),
    )


def _style_diff(runs: list[RunResult]) -> dict:
    """横向比较几篇稿子：标题、开头、语气、卖点顺序、字数、图数、结尾。

    同时给出「这几篇到底哪里不一样」的可读结论——这是给评委和销售员看的：
    同样的机器、同样的场景，换个写法就能发给不同的人。
    """
    rows: dict[str, dict] = {}
    for r in runs:
        a = r.article
        if not a:
            continue
        body = [b for b in a.blocks if b.kind in ("para", "list", "heading", "callout")]
        first = next((b.text for b in a.blocks if b.kind in ("para", "callout")), "")
        persona = ""
        for e in r.task.extras or []:
            if e.startswith("persona:"):
                persona = e.split(":", 1)[1]
                break
        sp = r.strategy.selling_points if r.strategy else []
        rows[persona or a.platform] = {
            "标题": a.title,
            "开头": first[:70],
            "切入点": (r.strategy.hook if r.strategy else "")[:60],
            "语气": r.strategy.tone if r.strategy else "",
            "卖点顺序": [p.label.split("｜")[0] for p in sp],
            "正文字数": sum(len(b.text) for b in body),
            "图片数": len(a.image_refs),
            "结尾动作": a.cta[:60],
        }
    if len(rows) < 2:
        return {"rows": rows, "varies": [], "identical": []}
    varies, identical = [], []
    for k in next(iter(rows.values())):
        if k == "标题":
            continue
        vals = {json.dumps(v.get(k), ensure_ascii=False, sort_keys=True) for v in rows.values()}
        (varies if len(vals) > 1 else identical).append(k)
    return {"rows": rows, "varies": varies, "identical": identical}
