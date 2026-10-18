"""全链路：parse → clarify → strategy → retrieve → extract → compose → verify_fact → verify_image
→ compliance → finalize。revise 用规则解析自然语言修改指令后整体重跑。

rules-dev 的模块（understand / verify / compliance）按 DESIGN 4.2 的签名 lazy import；
缺失时降级为直通并在 StageLog 里如实标注。
"""
from __future__ import annotations

import re
import secrets
import time
from datetime import datetime
from typing import Callable, Optional

from app.context import AppContext
from app.models import (
    Article, Block, ComplianceIssue, EngineInfo, EvidencePack, FactCheckItem, ImageCheckItem,
    ReviseRequest, RunRequest, RunResult, StageLog, Strategy, TaskSpec, Verification,
)
from app.agent import profiles as P
from app.agent.compose import compose, refresh_article
from app.agent.retrieve import gather
from app.agent.strategy import build_strategy

STAGE_LABEL = {
    "parse": "任务解析", "clarify": "缺失信息检查", "strategy": "场景与平台策略", "retrieve": "知识库检索",
    "extract": "事实点提取", "compose": "图文编排与生成", "verify_fact": "事实核验", "verify_image": "图片核验",
    "compliance": "合规检查", "finalize": "整理与落盘",
}
PRICE_WORDS = re.compile(r"国补|补贴|立减|优惠|折扣|降价|低价|最低价|赠品|库存|秒杀|限时|返现|以旧换新")
EXP_WORDS = re.compile(r"亲身|亲测|实测|我用了|体验")


class _Stages:
    """统一的阶段回调：每个阶段开始 + 结束各回调一次，timeline 只记录结束。"""

    def __init__(self, on_stage: Optional[Callable[[StageLog], None]]):
        self.on_stage = on_stage
        self.timeline: list[StageLog] = []
        self._t0: dict[str, float] = {}

    def _emit(self, log: StageLog) -> None:
        if self.on_stage:
            try:
                self.on_stage(log)
            except Exception:  # noqa: BLE001  回调出错不得影响生成
                pass

    def start(self, stage: str, note: str = "") -> None:
        self._t0[stage] = time.perf_counter()
        self._emit(StageLog(stage=stage, label=STAGE_LABEL.get(stage, stage), ms=0, note=note or "进行中…"))

    def end(self, stage: str, note: str) -> StageLog:
        ms = int((time.perf_counter() - self._t0.get(stage, time.perf_counter())) * 1000)
        log = StageLog(stage=stage, label=STAGE_LABEL.get(stage, stage), ms=ms, note=note)
        self.timeline.append(log)
        self._emit(log)
        return log


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _persist(ctx: AppContext, res: RunResult) -> None:
    try:
        d = ctx.settings.runs_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{res.run_id}.json").write_text(res.model_dump_json(indent=1), encoding="utf-8")
    except OSError as e:
        res.timeline.append(StageLog(stage="finalize", label="落盘失败", ms=0, note=f"运行档案未写入：{type(e).__name__}"))


# --------------------------------------------------------------------------
# rules-dev 模块的 lazy 适配
# --------------------------------------------------------------------------
def _parse(req: RunRequest, kb):
    try:
        from app.agent.understand import parse_task
    except ImportError:
        return _fallback_parse(req, kb), "understand 模块未就绪，使用最小解析"
    try:
        task, clar = parse_task(req, kb)
        return (task, clar), ""
    except ImportError:
        return _fallback_parse(req, kb), "understand 模块未就绪，使用最小解析"


def _fallback_parse(req: RunRequest, kb):
    from app.models import Clarification, ClarifyOption
    task = TaskSpec(raw=req.text, model_ids=list(req.model_ids), platform=req.platform, scenario=req.scenario,
                    audience=req.audience, selling_point=req.selling_point, want_price=req.want_price)
    if not task.model_ids:
        hits = kb.find_models(req.text or "") if req.text else []
        if len(hits) == 1 or (hits and hits[0][1] > (hits[1][1] if len(hits) > 1 else 0)):
            task.model_ids = [hits[0][0].model_id]
    clar = []
    if not task.model_ids:
        clar.append(Clarification(field="model", question="请选择要写的机型", reason="未识别到机型",
                                  options=[ClarifyOption(value=m.model_id, label=m.short_name) for m in kb.models()]))
    return task, clar


def _blocked_reason(snippet: str) -> str:
    try:
        from app.agent.understand import blocked_reason
        r = blocked_reason(snippet)
        if r:
            return r
    except Exception:  # noqa: BLE001
        pass
    if PRICE_WORDS.search(snippet):
        return "KB 中没有该价格/补贴/库存类记录，已拒绝写入"
    if EXP_WORDS.search(snippet):
        return "不得虚构亲身体验或实测结果，已拒绝写入"
    return "该要求违反事实或合规红线（无依据、绝对化或贬低竞品），已拒绝写入"


def _verify_facts(article, evidence, kb, st_notes: list[str]):
    try:
        from app.agent.verify import check_facts
    except ImportError:
        st_notes.append("verify.check_facts 未就绪，事实核验为直通")
        items = []
        for b in article.blocks:
            if b.kind in ("para", "list", "heading", "callout") and b.text:
                items.append(FactCheckItem(block_id=b.id, sentence=b.text, status="pass", fact_ids=b.fact_ids,
                                           reason="直通（核验模块未就绪）"))
        return article, items, []
    return check_facts(article, evidence, kb)


def _verify_images(article, kb, task, st_notes: list[str]):
    try:
        from app.agent.verify import check_images
    except ImportError:
        st_notes.append("verify.check_images 未就绪，图片核验为直通（仅检查型号与来源）")
        items = []
        for r in article.image_refs:
            a = kb.get_image(r.image_id)
            ok = bool(a and a.model_id == r.model_id and (a.source_url or a.page_url))
            items.append(ImageCheckItem(image_id=r.image_id, model_ok=bool(a and a.model_id == r.model_id),
                                        source_ok=bool(a and (a.source_url or a.page_url)), file_ok=bool(a),
                                        status="pass" if ok else "fail", reason="简易核验"))
        return article, items
    try:
        return check_images(article, kb, task.model_ids)
    except TypeError:
        return check_images(article, kb)


def _check_compliance(article, task, strategy, st_notes: list[str]):
    try:
        from app.agent.compliance import check_compliance
    except ImportError:
        st_notes.append("compliance 模块未就绪，合规检查为直通")
        return article, []
    return check_compliance(article, task, strategy)


def _build_verification(fact_items, image_items, issues, pending, article) -> Verification:
    try:
        from app.agent.verify import build_verification
        return build_verification(fact_items, image_items, issues, pending, article)
    except ImportError:
        pass
    blocks = sum(1 for i in issues if i.severity == "block" and i.action == "blocked")
    stats = {"sentences": len(fact_items), "cited": sum(1 for i in fact_items if i.fact_ids),
             "removed": sum(1 for i in fact_items if i.status == "removed"),
             "rewritten": sum(1 for i in fact_items if i.status == "rewritten"),
             "flagged": sum(1 for i in fact_items if i.status == "flag"),
             "images_ok": sum(1 for i in image_items if i.status == "pass"), "compliance_blocks": blocks}
    verdict = "blocked" if blocks else ("pass_with_flags" if (stats["flagged"] or issues or pending
                                                               or stats["removed"] or stats["rewritten"]) else "pass")
    return Verification(facts=fact_items, images=image_items, compliance=issues, pending=pending,
                        verdict=verdict, stats=stats)


# --------------------------------------------------------------------------
# 自动修复：删除被 block 的块，标题/CTA 回退为场景模板
# --------------------------------------------------------------------------
def _auto_repair(article: Article, issues: list[ComplianceIssue], task: TaskSpec) -> list[str]:
    msgs = []
    sc = P.get_scenario(task.scenario)
    ids = {i.where for i in issues if i.action == "blocked" and i.severity == "block"}
    if "title" in ids:
        alt = [t for t in article.titles[1:]] or [f"{sc['label']}选电脑，先核对再决定"]
        article.title = alt[0]
        article.titles = alt
        msgs.append("标题命中 block 级问题，改用备选标题")
    if "cta" in ids:
        article.cta = sc["cta"][task.platform or P.DEFAULT_PLATFORM]
        msgs.append("CTA 命中 block 级问题，回退为场景默认 CTA")
    drop = {i for i in ids if i.startswith("b")}
    if drop:
        article.blocks = [b for b in article.blocks if b.id not in drop]
        msgs.append(f"移除 {len(drop)} 个 block 级问题块（{'、'.join(sorted(drop))}）")
    return msgs


def _scenario_pending(task: TaskSpec, strategy: Strategy, evidence: EvidencePack) -> list[str]:
    sc = P.get_scenario(task.scenario)
    out = list(sc["pending"])
    if task.selling_point and not P.tag_for_user_point(task.selling_point):
        out.append(f"无法把“{task.selling_point}”对应到已知卖点，已按场景默认排序")
    elif task.selling_point and strategy.selling_points:
        tag = P.tag_for_user_point(task.selling_point)
        from app.agent.strategy import label_tag
        if label_tag(strategy.selling_points[0].label) != tag:
            out.append(f"KB 中没有“{task.selling_point}”的可引用事实，未作为主卖点")
    if task.want_price and not evidence.prices:
        out.append("KB 中没有该机型可引用的价格记录，稿件未写价格")
    if len(task.model_ids) > 1:
        out.append("本次只写第一个机型，不做多机型拼接；对比任务请分别生成")
    lo = P.get_platform(task.platform)["img_range"][0]
    if not evidence.images:
        out.append("KB 中没有该机型可用的图片，稿件不含配图")
    elif len(evidence.images) < lo:
        out.append(f"KB 中该机型只有 {len(evidence.images)} 张可用图片，少于{P.get_platform(task.platform)['label']}建议的 {lo} 张，未借用其他机型的图")
    return out


# --------------------------------------------------------------------------
# 核心流程（parse 之后）
# --------------------------------------------------------------------------
def _execute(task: TaskSpec, ctx: AppContext, st: _Stages, run_id: str, parent: str, note: str) -> RunResult:
    kb = ctx.kb
    created = _now_iso()
    notes: list[str] = []
    refusal = ""
    if task.blocked_requests:
        refusal = "；".join(f"“{s}”：{_blocked_reason(s)}" for s in task.blocked_requests)

    # ---- strategy
    st.start("strategy")
    model_id = task.model_ids[0]
    model = kb.get_model(model_id)
    if not task.scenario or not task.platform:
        task = task.model_copy(update={"scenario": task.scenario or P.DEFAULT_SCENARIO,
                                       "platform": task.platform or P.DEFAULT_PLATFORM})
        task.confusion_notes = list(task.confusion_notes) + ["场景/平台未指定，已按默认值（职场办公/公众号）处理"]
    pool = kb.facts(model_id)
    strategy = build_strategy(task, [model] if model else [], pool)
    st.end("strategy", f"{strategy.scenario_label} × {strategy.platform_label}；切入点“{strategy.hook.split('：')[0]}”；"
                       f"{len(strategy.selling_points)} 个卖点；配图 {strategy.image_count} 张")

    # ---- retrieve
    st.start("retrieve")
    evidence = gather(task, strategy, kb)
    st.end("retrieve", f"检索 {len(evidence.trace)} 次（{evidence.trace[0].origin if evidence.trace else kb.status().mode}）；"
                       f"取证 {len(evidence.facts)} 条事实、{len(evidence.images)} 张同型号图片、{len(evidence.prices)} 条价格")

    # ---- extract
    st.start("extract")
    kinds: dict[str, int] = {}
    for f in evidence.facts:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    st.end("extract", "事实点：" + "、".join(f"{k}×{v}" for k, v in kinds.items()))

    # ---- compose
    st.start("compose")
    article, engine = compose(task, strategy, evidence, ctx.llm)
    try:
        engine.kb_mode = kb.status().mode
    except Exception:  # noqa: BLE001
        engine.kb_mode = ""
    st.end("compose", ("LLM 生成：" + engine.llm_model if engine.writer == "llm" else "确定性 Composer 生成")
           + (f"｜{engine.note}" if engine.note else "") + f"｜{len(article.blocks)} 个块")

    # ---- verify + compliance（最多自动修复 1 轮）
    attempts = 0
    while True:
        st.start("verify_fact")
        article, fact_items, pending = _verify_facts(article, evidence, kb, notes)
        st.end("verify_fact", f"逐句核验 {len(fact_items)} 句："
                              f"通过 {sum(1 for i in fact_items if i.status == 'pass')}，"
                              f"删除 {sum(1 for i in fact_items if i.status == 'removed')}，"
                              f"改写 {sum(1 for i in fact_items if i.status == 'rewritten')}，"
                              f"标注 {sum(1 for i in fact_items if i.status == 'flag')}")
        st.start("verify_image")
        article, image_items = _verify_images(article, kb, task, notes)
        st.end("verify_image", f"图片 {sum(1 for i in image_items if i.status == 'pass')}/{len(image_items)} 张通过型号·来源·文件核验")
        st.start("compliance")
        article, issues = _check_compliance(article, task, strategy, notes)
        blocked_now = [i for i in issues if i.action == "blocked" and i.severity == "block"]
        st.end("compliance", f"发现 {len(issues)} 项（block {len(blocked_now)}）")
        if blocked_now and attempts == 0:
            attempts += 1
            msgs = _auto_repair(article, issues, task)
            notes.extend(msgs)
            refresh_article(article, evidence)
            continue
        break
    refresh_article(article, evidence)

    # ---- finalize
    st.start("finalize")
    if task.blocked_requests and not any(i.where == "request" for i in issues):
        for s in task.blocked_requests:
            issues.append(ComplianceIssue(rule="false_promise" if not PRICE_WORDS.search(s) else "price_misleading",
                                          rule_label="用户请求被拒", severity="warn", text=s,
                                          suggestion=_blocked_reason(s), action="removed", where="request"))
    pending = list(pending) + _scenario_pending(task, strategy, evidence)
    for s in task.blocked_requests:
        pending.append(f"已拒绝：{s}（{_blocked_reason(s)}）")
    pending += [n for n in notes if n]
    pending = list(dict.fromkeys(pending))
    verification = _build_verification(fact_items, image_items, issues, pending, article)
    status = "ok"
    if verification.verdict == "blocked":
        status = "blocked"
    ev_trace = len(evidence.trace)
    st.end("finalize", f"verdict={verification.verdict}｜引用事实 {len(evidence.used_fact_ids)} 条｜配图 {len(article.image_refs)} 张｜检索记录 {ev_trace} 条")

    res = RunResult(run_id=run_id, created_at=created, parent_run_id=parent, revision_note=note, status=status,
                    refusal=refusal, task=task, strategy=strategy, evidence=evidence, article=article,
                    verification=verification, engine=engine, timeline=list(st.timeline))
    _persist(ctx, res)
    return res


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
def run(req: RunRequest, ctx: AppContext, on_stage: Optional[Callable[[StageLog], None]] = None) -> RunResult:
    st = _Stages(on_stage)
    run_id, created = _new_run_id(), _now_iso()
    try:
        st.start("parse")
        (task, clar), parse_note = _parse(req, ctx.kb)
        st.end("parse", parse_note or f"机型 {len(task.model_ids)} 个｜场景 {task.scenario or '未指定'}｜平台 {task.platform or '未指定'}"
                        + (f"｜待拒绝要求 {len(task.blocked_requests)} 条" if task.blocked_requests else ""))
        st.start("clarify")
        if clar:
            st.end("clarify", f"需要追问 {len(clar)} 项：" + "、".join(c.field for c in clar))
            res = RunResult(run_id=run_id, created_at=created, parent_run_id=req.parent_run_id,
                            status="needs_clarification", task=task, clarifications=clar, timeline=list(st.timeline))
            _persist(ctx, res)
            return res
        if not task.model_ids:
            st.end("clarify", "未识别到机型")
            res = RunResult(run_id=run_id, created_at=created, parent_run_id=req.parent_run_id,
                            status="refused" if task.blocked_requests else "needs_clarification", task=task,
                            refusal="；".join(f"“{s}”：{_blocked_reason(s)}" for s in task.blocked_requests),
                            timeline=list(st.timeline))
            _persist(ctx, res)
            return res
        st.end("clarify", "信息齐全，无需追问")
        if task.blocked_requests and not (task.scenario or task.platform) and not req.text.strip().strip("，。 "):
            res = RunResult(run_id=run_id, created_at=created, parent_run_id=req.parent_run_id, status="refused",
                            task=task, refusal="；".join(f"“{s}”：{_blocked_reason(s)}" for s in task.blocked_requests),
                            timeline=list(st.timeline))
            _persist(ctx, res)
            return res
        return _execute(task, ctx, st, run_id, req.parent_run_id, "")
    except Exception as e:  # noqa: BLE001  不向上抛，返回可读的失败结果
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        st.timeline.append(StageLog(stage="finalize", label="运行失败", ms=0, note=msg))
        st._emit(st.timeline[-1])
        res = RunResult(run_id=run_id, created_at=created, parent_run_id=req.parent_run_id, status="blocked",
                        refusal=f"生成过程出错：{msg}", task=TaskSpec(raw=req.text), timeline=list(st.timeline))
        _persist(ctx, res)
        return res


# --------------------------------------------------------------------------
# revise：规则解析自然语言指令
# --------------------------------------------------------------------------
_PLATFORM_WORDS = [("xiaohongshu", r"小红书"), ("moments", r"朋友圈"), ("poster", r"海报|长图"), ("wechat_mp", r"公众号|长文")]
_SCENARIO_WORDS = [
    ("back_to_school", r"开学"), ("office", r"职场|办公|上班"), ("creator", r"创作|剪辑|修图"),
    ("home_upgrade", r"家庭|换新|家用"), ("enterprise_procurement", r"企业|采购"), ("store_visit", r"门店到访|到访|到店"),
    ("new_launch", r"新品|首发"), ("festival", r"节日|春节|中秋|国庆|双十一|圣诞"),
]
_SECTION_WORDS = [
    ("limit", r"限制|局限|边界|不适用"), ("checklist", r"清单|核对"), ("price", r"价格|价钱|报价"),
    ("scene", r"场景|背景"), ("intro", r"导语|开头|引言"), ("hook", r"钩子|开场|开头"),
    ("p3", r"第三个卖点|第3个卖点|卖点三|卖点3|第三节"), ("p2", r"第二个卖点|第2个卖点|卖点二|卖点2|第二节"),
    ("p1", r"第一个卖点|第1个卖点|卖点一|卖点1|第一节"),
]


def parse_revision(instruction: str, prev_task: TaskSpec, req: Optional[ReviseRequest] = None) -> tuple[TaskSpec, list[str]]:
    """返回 (新 task, 变更说明列表)。"""
    t = prev_task.model_copy(deep=True)
    ins = (instruction or "").strip()
    changes: list[str] = []
    switch = r"(换成|改成|改为|转成|转为|换到|变成|改写成|改写为|写成|做成)"
    if req and req.platform:
        t.platform = req.platform
        changes.append(f"平台改为 {P.get_platform(req.platform)['label']}")
    else:
        for pid, pat in _PLATFORM_WORDS:
            if re.search(switch + r"[^，。,；]{0,6}(" + pat + ")", ins) or re.search("(" + pat + ")[^，。,；]{0,4}" + switch[:-1] + "|版)", ins):
                if pid != t.platform:
                    t.platform = pid
                    changes.append(f"平台改为 {P.get_platform(pid)['label']}")
                break
    if req and req.scenario:
        t.scenario = req.scenario
        changes.append(f"场景改为 {P.get_scenario(req.scenario)['label']}")
    else:
        for sid, pat in _SCENARIO_WORDS:
            if re.search(switch + r"[^，。,；]{0,6}(" + pat + ")", ins) and not re.search(r"卖点", ins[:ins.find("成") + 1]):
                if sid != t.scenario:
                    t.scenario = sid
                    changes.append(f"场景改为 {P.get_scenario(sid)['label']}")
                break
    # 主卖点
    sp = (req.selling_point if req else "").strip()
    if not sp:
        m = (re.search(r"(?:把|将)?(.{1,8}?)(?:换成|改成|改为|设为|作为)(?:主卖点|第一卖点|核心卖点|主打)", ins)
             or re.search(r"(?:主卖点|核心卖点|第一卖点|主打|突出|重点写|以)(?:换成|改成|改为|是|写)?[：:]?(.{1,8}?)(?:为主|为核心|$|，|。|吧)", ins))
        if m:
            cand = m.group(1).strip("“”\"' ，。把将")
            if cand and P.tag_for_user_point(cand):
                sp = cand
    if sp:
        t.selling_point = sp
        changes.append(f"主卖点改为“{sp}”")
    # 价格
    if re.search(r"(删|去|不要|不写|拿掉|移除|取消)[掉除]?[^，。]{0,3}(价格|价钱|报价|金额)", ins):
        if t.want_price:
            t.want_price = False
            changes.append("删除价格")
        t.extras = [e for e in t.extras if e != "add:price"]
    elif re.search(r"(加|写|补|带|增加|附上)[上入进]?[^，。]{0,3}(价格|价钱|报价)", ins):
        if not t.want_price:
            t.want_price = True
            changes.append("增加价格（仅限 KB 可引用记录）")
    # 长短
    if re.search(r"短一?点|缩短|精简|简短|压缩|再短|少写|简洁", ins):
        t.length_hint = "短"
        changes.append("缩短篇幅")
    elif re.search(r"长一?点|展开|详细|加长|扩写|多写|丰富", ins):
        t.length_hint = "长"
        changes.append("展开篇幅")
    # 删/加某节
    for mt in re.finditer(r"(?:删掉|删除|去掉|不要|拿掉|砍掉)([^，。,；]{0,10})", ins):
        seg = mt.group(1)
        if re.search(r"价格|价钱|报价", seg):
            continue
        for key, pat in _SECTION_WORDS:
            if re.search(pat, seg):
                t.extras = [e for e in t.extras if e != f"add:{key}"]
                if f"drop:{key}" not in t.extras:
                    t.extras.append(f"drop:{key}")
                changes.append(f"删除“{P.SECTION_LABEL.get(t.platform or 'wechat_mp', {}).get(key, key)}”一节")
                break
    for mt in re.finditer(r"(?:加一?[节段个]?|增加一?[节段个]?|补一?[节段个]?|加上|补上)([^，。,；]{0,10})", ins):
        seg = mt.group(1)
        for key, pat in _SECTION_WORDS:
            if key in ("p1", "p2", "p3", "price"):
                continue
            if re.search(pat, seg):
                t.extras = [e for e in t.extras if e != f"drop:{key}"]
                if f"add:{key}" not in t.extras:
                    t.extras.append(f"add:{key}")
                changes.append(f"增加“{P.SECTION_LABEL.get(t.platform or 'wechat_mp', {}).get(key, key)}”一节")
                break
    return t, changes


def revise(req: ReviseRequest, prev: RunResult, ctx: AppContext,
           on_stage: Optional[Callable[[StageLog], None]] = None) -> RunResult:
    st = _Stages(on_stage)
    run_id, created = _new_run_id(), _now_iso()
    try:
        st.start("parse", "解析修改指令")
        if not prev.task.model_ids:
            st.end("parse", "上一版没有确定机型，无法在其基础上修改")
            st.start("clarify")
            st.end("clarify", "请先回答上一版的追问")
            res = RunResult(run_id=run_id, created_at=created, parent_run_id=prev.run_id,
                            revision_note=req.instruction, status="needs_clarification", task=prev.task,
                            clarifications=prev.clarifications, timeline=list(st.timeline))
            _persist(ctx, res)
            return res
        task, changes = parse_revision(req.instruction, prev.task, req)
        task.raw = (prev.task.raw + f"｜修改：{req.instruction}").strip("｜")
        # 指令里新出现的违规要求：沿用 understand 的识别
        try:
            from app.agent.understand import parse_task
            _t2, _ = parse_task(RunRequest(text=req.instruction, model_ids=task.model_ids, platform=task.platform,
                                           scenario=task.scenario), ctx.kb)
            for s in _t2.blocked_requests:
                if s not in task.blocked_requests:
                    task.blocked_requests.append(s)
        except Exception:  # noqa: BLE001
            pass
        note = "；".join(changes) if changes else "未识别出可执行的修改项，已按原设置重新生成并重新核验"
        st.end("parse", f"{note}")
        st.start("clarify")
        st.end("clarify", "沿用上一版的机型与参数，无需追问")
        res = _execute(task, ctx, st, run_id, prev.run_id, f"{req.instruction}（{note}）")
        return res
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        st.timeline.append(StageLog(stage="finalize", label="修改失败", ms=0, note=msg))
        st._emit(st.timeline[-1])
        res = RunResult(run_id=run_id, created_at=created, parent_run_id=prev.run_id, revision_note=req.instruction,
                        status="blocked", refusal=f"修改过程出错：{msg}", task=prev.task, timeline=list(st.timeline))
        _persist(ctx, res)
        return res
