"""一稿四发：同一任务跑多个平台，并算出平台间差异摘要。

用途：评委要「更换平台，比较输出差异」，门店销售员要「写一次，挑一个渠道发」。
差异摘要直接回答「只改平台名算不算完成适配」——结构、语气、图数、CTA 逐项列出。
"""
from __future__ import annotations

import json
import time
from typing import Optional

from app.agent import profiles as P
from app.agent.pipeline import run
from app.context import AppContext
from app.models import (
    BatchRunRequest, BatchRunResult, PlatformId, RunRequest, RunResult,
)


def _diff_of(runs: list[RunResult]) -> dict:
    """横向比较各平台成稿：结构、语气、图数、CTA、字数。"""
    rows: dict[str, dict] = {}
    for r in runs:
        if not r.article or not r.strategy:
            continue
        a, s = r.article, r.strategy
        body = "\n".join(b.text for b in a.blocks if b.kind in ("para", "list", "heading", "callout"))
        rows[a.platform] = {
            "平台": P.PLATFORM_LABELS.get(a.platform, a.platform),
            "标题": a.title,
            "结构": " → ".join(s.structure),
            "语气": s.tone,
            "篇幅": s.length,
            "正文字数": len(body.replace("\n", "")),
            "图片数": len(a.image_refs),
            "CTA": a.cta,
            "话题标签": len(a.hashtags),
            "卖点顺序": [sp.label for sp in s.selling_points],
        }
    if len(rows) < 2:
        return {"rows": rows, "same": [], "differs": []}

    keys = list(next(iter(rows.values())).keys())
    same, differs = [], []
    for k in keys:
        if k in ("平台",):
            continue
        # list/dict 不可哈希，序列化后再比较
        vals = {json.dumps(v.get(k), ensure_ascii=False, sort_keys=True) for v in rows.values()}
        (same if len(vals) <= 1 else differs).append(k)
    return {"rows": rows, "same": same, "differs": differs}


def batch_run(req: BatchRunRequest, ctx: AppContext, on_stage=None) -> BatchRunResult:
    platforms: list[PlatformId] = list(req.platforms) if req.platforms else list(P.PLATFORM_ORDER)
    platforms = [p for p in P.PLATFORM_ORDER if p in platforms][:4]

    runs: list[RunResult] = []
    for pf in platforms:
        r = run(RunRequest(
            text=req.text,
            model_ids=list(req.model_ids),
            platform=pf,
            scenario=req.scenario,
            audience=req.audience,
            selling_point=req.selling_point,
            parent_run_id=req.parent_run_id,
        ), ctx, on_stage)
        runs.append(r)

    return BatchRunResult(
        batch_id=f"batch-{int(time.time()*1000)}",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        task=runs[0].task if runs else None,  # type: ignore[arg-type]
        runs=runs,
        diff=_diff_of(runs),
    )
