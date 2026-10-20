"""生成：LLM 路径 + 确定性 Composer 路径。

Composer 的原则：
- 产品断言只来自 Fact 原句（保留限定语）；场景句只写读者的处境/动作，不含数字、型号名、参数。
- 每个含产品断言的 Block 带 fact_ids；场景/过渡块 fact_ids=[] 且 note="scene"。
- 句式、段落蓝本由 profiles（场景）与本文件（平台）共同决定，同输入同输出。
"""
from __future__ import annotations

import re
from typing import Optional

from app.models import (
    Article, Block, EngineInfo, EvidencePack, Fact, ImageAsset, ImageRef, PriceRecord,
    SourceItem, Strategy, TaskSpec,
)
from app.agent import profiles as P
from app.agent.strategy import label_tag, persona_shift, pick_hook
from app.agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message

VALID_KINDS = {"heading", "para", "list", "image", "quote", "callout"}

HEAD_SCENE = ["先把场景说清楚", "为什么要先看这几项", "动手之前，先对一下需求"]
HEAD_LIMIT = ["有一件事要提前说清", "下单之前，先看这条限制", "哪些情况要先核对"]
HEAD_PRICE = ["价格怎么看", "说到价格，先看口径"]
HEAD_CHECK = ["动手之前，核对这几步", "下单前的核对清单"]
SOWHAT = [
    "如果这正是你在意的一项，打开官方页面时，先找它。",
    "这一条值得带到现场，对着真机再确认一遍。",
    "把这一条记进你的对比清单，别的参数可以放到后面再看。",
    "读到这里如果你点头了，就把它列进必须核对的名单。",
]
VERIFY_ACTION = [
    "建议下单前把你必用的软件和外设列成清单，到官方页面或门店逐项确认。",
    "核验动作很简单：把你的使用清单带到官方页面，对着配置逐条打钩。",
    "如果你正好属于这种情况，先别急着决定，用你的真实文件和软件在门店试一遍。",
]
LIMIT_FRAME = {
    "unfit": "资料里把下面这种情况列为需要先验证的任务：",
    "boundary": "资料里还有一条表达边界要一起带上：",
    "fit": "资料里的适用说明是：",
}
XHS_LIMIT_FRAME = {"unfit": "先说一条限制：", "boundary": "再补一条边界：", "fit": "适用说明："}
SHORT_VERIFY = ["下单前先核对。", "买之前自己对一遍。", "先核对再决定。"]


# --------------------------------------------------------------------------
# 句子渲染
# --------------------------------------------------------------------------
_VERB_START = re.compile(r"^(支持|采用|配备|提供|具备|内置|搭载|可|带|带有|配有|采用了|列有|为)")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def fact_sentence(f: Fact, with_constraints: bool = False) -> str:
    t = _clean(f.text).rstrip("。；;，, ")
    if f.kind == "spec" and ("：" in t or ":" in t):
        k, v = [x.strip() for x in re.split(r"[：:]", t, maxsplit=1)]
        if k and v:
            if "：" in v or "；" in v:
                t = f"{k}：{v}"
            else:
                t = f"{k}{v}" if _VERB_START.match(v) else f"{k}为{v}"
    if with_constraints:
        cons = [c for c in (f.constraints or []) if c and _clean(c).rstrip("。；") not in t]
        if cons:
            t += "（限定：" + "；".join(_clean(c).rstrip("。；;") for c in cons) + "）"
    return t + "。"


def _split_fit(facts: list[Fact]):
    return [f for f in facts if f.kind != "fit"], [f for f in facts if f.kind == "fit"]


class _ConsBook:
    """限定语登记簿。限定语只跟最需要它的那一段一次，其余段落不重复；
    登记过的限定统一进文末“使用前请注意”。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def take(self, facts: list[Fact], used_text: list[str]) -> list[str]:
        return []      # 一律不内联，文末统一给

    def tail(self) -> list[str]:
        return list(self.seen)


_book = None            # per-compose 的单例登记簿


def reset_cons_book(evidence: Optional[EvidencePack] = None) -> None:
    """重置登记簿；给了 evidence 就把本次引用的全部事实的限定语登记进来。"""
    global _book
    _book = _ConsBook()
    if evidence is not None:
        cand = [f for f in evidence.facts]
        prio = {"spec": 0, "card": 1, "selling": 2, "boundary": 3, "fit": 4, "unfit": 5}
        for f in sorted(cand, key=lambda x: prio.get(x.kind, 9)):
            for c in f.constraints or []:
                c = _clean(c).rstrip("。；;")
                if c and c not in _book.seen:
                    _book.seen.append(c)


def limit_text_for(f: Fact) -> str:
    return fact_sentence(f, with_constraints=False)


def _fit_sentence(fits: list[Fact], platform: str = "") -> str:
    """fit 事实多是名词短语（“需要…的任务”），统一加一个引导，避免和上一句硬接。"""
    if not fits:
        return ""
    if platform == "xiaohongshu":
        lead = P.pick(["对应得上的是：", "资料里归到这类：", "适合的情况包括："], "fit")
    else:
        lead = P.pick(["对应得上的是：", "资料把适用情形归为：", "适合的情况包括："], "fit")
    return lead + "；".join(_clean(f.text).rstrip("。；;") for f in fits) + "。"


def render_facts(facts: list[Fact], prefix: str = "") -> str:
    """多条事实合成一段：陈述句依次排列，fit 短语加引导，限定语合并去重后只出现一次（放在末尾）。"""
    plain, fits = _split_fit(facts)
    sents = [fact_sentence(f, with_constraints=False) for f in plain]
    text = prefix + "".join(sents) + _fit_sentence(fits)
    return text


def render_items(facts: list[Fact]) -> str:
    """list 块：每条事实一行（限定语统一走文末“使用前请注意”）。"""
    plain, fits = _split_fit(facts)
    lines = [fact_sentence(f, with_constraints=False) for f in plain]
    if fits:
        lines.append(_fit_sentence(fits))
    return "\n".join(lines)


def _date_of(*vals: str) -> str:
    for v in vals:
        if v:
            return v[:10]
    return ""


def _fmt_amount(x: Optional[float]) -> str:
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}"


def _fmt_time(s: str) -> str:
    return s[:16].replace("T", " ") if s else ""


class _Builder:
    def __init__(self):
        self.blocks: list[Block] = []
        self._n = 0

    def add(self, kind: str, text: str, fact_ids: Optional[list[str]] = None, note: str = "") -> Block:
        self._n += 1
        b = Block(id=f"b{self._n}", kind=kind, text=text, fact_ids=list(dict.fromkeys(fact_ids or [])), note=note)
        self.blocks.append(b)
        return b

    def scene(self, text: str) -> Block:
        return self.add("para", text, [], "scene")


# --------------------------------------------------------------------------
# 价格
# --------------------------------------------------------------------------
def price_lines(prices: list[PriceRecord]) -> tuple[list[str], list[str], list[str]]:
    """(price_note 行, 正文句, record_ids)。无金额记录如实说明。"""
    note_lines, sentences, rids = [], [], []
    with_amount = [r for r in prices if r.amount is not None and r.amount > 0]
    if with_amount:
        ptype = with_amount[0].price_type
        for r in with_amount:
            if r.price_type != ptype:      # 口径不混
                continue
            amt = _fmt_amount(r.amount)
            cond = r.conditions or "无附加条件记录"
            when = _fmt_time(r.verified_at)
            note_lines.append(
                f"- 口径：{r.price_type}；SKU：{r.spec}；金额：{amt} 元；核验时间：{when}；条件：{cond}；官方链接：{r.url}")
            sentences.append(f"{r.spec}：{amt} 元（{r.price_type}，{when} 核验）")
            rids.append(r.record_id)
    else:
        for r in prices[:2]:
            when = _fmt_time(r.verified_at)
            note_lines.append(
                f"- 口径：未公开金额；机型：{r.product_name}；状态：{r.price_type}{('/' + r.status) if r.status else ''}；"
                f"核验时间：{when}；官方链接：{r.url}；说明：官方未公开当前金额，如实告知")
            rids.append(r.record_id)
    return note_lines, sentences, rids


def price_block(b: _Builder, task: TaskSpec, evidence: EvidencePack, short: bool = False) -> str:
    """向 builder 追加价格 callout，返回 price_note。"""
    recs = evidence.prices
    if short:                                   # 朋友圈/海报只写一个 SKU，price_note 与正文严格对应
        first = next((r for r in recs if r.amount is not None and r.amount > 0), None)
        recs = [first] if first else recs[:1]
    lines, sents, rids = price_lines(recs)
    if sents:
        cond_any = next((r.conditions for r in recs if r.record_id in rids and r.conditions), "")
        # 正文只带不含金额与晒单类字样的条件；完整条件在 price_note 里原样保留
        segs = [s for s in re.split(r"[；;]", cond_any) if s.strip() and not re.search(r"\d\s*元|晒单", s)]
        tail = "页面价会随库存、地区和活动变化，完整条件见价格出处，以华为商城结算页为准。"
        if segs:
            tail = f"页面条件：{'；'.join(segs)}。" + tail
        text = ("价格口径：" + "；".join(sents) + "。" + tail) if not short else \
            ("价格：" + sents[0] + "。以结算页为准。")
        b.add("callout", text, [], "price:" + ",".join(rids))
        return "\n".join(lines)
    if lines:
        text = "关于价格，如实说一句：官方未公开当前金额。具体情况请以华为商城或官方渠道当日页面为准，这里不写数字。"
    else:
        text = "价格这一项，资料里没有可引用的记录，所以这里不写数字，请以华为商城或官方渠道当日页面为准。"
    b.add("callout", text, [], "price:none")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Composer
# --------------------------------------------------------------------------
def _plan_info(task: TaskSpec, strategy: Strategy, evidence: EvidencePack):
    fmap = {f.id: f for f in evidence.facts}
    plans = []
    for sp in strategy.selling_points:
        tag = label_tag(sp.label) or "office"
        facts = [fmap[i] for i in sp.fact_ids if i in fmap]
        if facts:
            plans.append((sp, tag, facts))
    return plans


def _limit_facts(evidence: EvidencePack, model_id: str) -> list[Fact]:
    return [f for f in evidence.facts if f.model_id == model_id and f.kind in ("unfit", "boundary")][:2]


def _identity(evidence: EvidencePack, model_id: str) -> Optional[Fact]:
    for f in evidence.facts:
        if f.model_id == model_id and f.category == "identity":
            return f
    return None


def _titles(task: TaskSpec, strategy: Strategy, model_short: str, top_label: str, scenario: str, platform: str) -> list[str]:
    sc, pf = P.get_scenario(scenario), P.get_platform(platform)
    if platform == "moments":
        hk = pick_hook(scenario, platform, task.model_ids[0] if task.model_ids else "", task.selling_point,
                       shift=persona_shift(task))
        return [hk["short"]]
    raw = list(sc["titles"].get(platform) or sc["titles"]["wechat_mp"])
    # 人设旋转标题候选：同一场景的备选标题按人设错开，避免几篇同一个标题
    shift = persona_shift(task)
    if shift and len(raw) > 1:
        raw = raw[shift % len(raw):] + raw[:shift % len(raw)]
    out = []
    for t in raw:
        out.append(P.sub(t, m=model_short, p=top_label or "核心卖点"))
    if platform == "poster":
        out = [t for t in out]
    # 去重补足
    extra = {"wechat_mp": f"{model_short}：{sc['label']}场景的选购核对表",
             "xiaohongshu": f"{sc['label']}选电脑，这几项先看",
             "poster": f"{model_short}｜{sc['label']}"}.get(platform, "")
    while len(out) < pf["titles_min"] and extra:
        out.append(extra)
        extra = extra + "（备选）"
    return list(dict.fromkeys(out))


def _hashtags(strategy: Strategy, scenario: str, model_short: str, platform: str) -> list[str]:
    if platform != "xiaohongshu":
        return []
    sc = P.get_scenario(scenario)
    tags = ["#" + model_short.replace(" ", "")] + list(sc["hashtags"])
    tags += ["#华为电脑", "#选购攻略"]
    return list(dict.fromkeys(tags))[:6]


def compose_with_composer(task: TaskSpec, strategy: Strategy, evidence: EvidencePack) -> Article:
    scenario = task.scenario or P.DEFAULT_SCENARIO
    platform = task.platform or P.DEFAULT_PLATFORM
    sc, pf = P.get_scenario(scenario), P.get_platform(platform)
    reset_cons_book(evidence)
    model = evidence.models[0] if evidence.models else None
    model_id = model.model_id if model else (task.model_ids[0] if task.model_ids else "")
    model_name = model.name if model else "该机型"
    model_short = model.short_name if model else "该机型"
    seed = task.selling_point
    hook = pick_hook(scenario, platform, model_id, seed)
    plans = _plan_info(task, strategy, evidence)
    short = task.length_hint == "短"
    long = task.length_hint == "长"
    sections = P.resolve_sections(platform, scenario, len(plans), task.want_price, task.length_hint, task.extras)
    top_tag = plans[0][1] if plans else "office"
    top_label = P.TAG_LABEL.get(top_tag, "")
    titles = _titles(task, strategy, model_short, top_label, scenario, platform)
    ident = _identity(evidence, model_id)
    limits = _limit_facts(evidence, model_id)
    harmony = bool(model and model.os_family == "harmonyos")
    b = _Builder()
    anchors: list[Optional[str]] = []          # 与图片 slot 对应的 after_block
    anchor_pos: list[str] = []
    intro = ""
    price_note = ""
    poster: Optional[dict] = None
    # persona 进种子：同任务不同人设会选到不同的过渡句、结尾句式
    persona_key = ""
    for e in (task.extras or []):
        if e.startswith("persona:"):
            persona_key = e.split(":", 1)[1].strip()
            break
    k = (scenario, platform, model_id, persona_key)

    def model_intro_text() -> tuple[str, list[str]]:
        lead = P.pick(["今天要写的是 ", "先说到机器本身，", "要对照资料看的是 ", "本稿的主角是 "], *k, "mi")
        if ident:
            sent = fact_sentence(ident, with_constraints=False)
            named = model_name in sent or model_short in sent
            if named:
                return f"{lead}{sent}", [ident.id]
            return f"{lead}{model_name}。{sent}", [ident.id]
        return f"{lead}{model_name}。", []

    def point_facts(i: int, facts: list[Fact]) -> list[Fact]:
        n = 1 if (short or platform == "moments") else (3 if long else 2)
        if platform == "poster":
            n = 2
        return facts[:max(n, 1)]

    def limit_text(style: str) -> tuple[str, list[str]]:
        ids = [f.id for f in limits]
        if not limits:
            return ("资料里没有给这个机型列出明确的不适用任务。买之前请用你自己的软件、文件和外设逐项核对，别把“资料没写”当成“没有限制”。", [])
        unfit = [f for f in limits if f.kind == "unfit"]
        other = [f for f in limits if f.kind != "unfit"]
        def j(fs): return "；".join(_clean(f.text).rstrip("。；;") for f in fs)
        if style == "short":
            f0 = limits[0]
            lead = "提醒一句，这种情况要先验证：" if f0.kind == "unfit" else "提醒一句："
            return lead + fact_sentence(f0, with_constraints=False) + P.pick(SHORT_VERIFY, *k, "lv"), [f0.id]
        parts = []
        if unfit:
            lead = {"xhs": "先说一条限制，下面这些情况要先验证：", "long": "资料把下面这类情况列为需要先验证的任务："}[style]
            parts.append(lead + j(unfit) + "。")
        for f in other:
            parts.append(("再补一条边界：" if style == "xhs" else "资料里还有一条表达边界要一起带上：") + fact_sentence(f, with_constraints=False))
        body = "".join(parts)
        if style == "xhs":
            return body + P.pick(SHORT_VERIFY, *k, "lv"), ids
        extra = ""
        if harmony and any(("Windows" in f.text or "软件" in f.text) for f in limits):
            extra = "鸿蒙电脑能否运行你必须用的 Windows 专用软件，是选购的前置条件，这一项要先确认。"
        return body + extra + P.pick(VERIFY_ACTION, *k, "lv"), ids

    # ================= 公众号 =================
    if platform == "wechat_mp":
        intro = hook["open"]
        anchors.append(None); anchor_pos.append("导语之后")
        for key in sections:
            if key == "intro":
                continue
            if key == "scene":
                b.add("heading", P.pick(HEAD_SCENE, *k, "hs"))
                b.scene(sc["scene2"])
                text, ids = model_intro_text()
                b.add("para", text, ids)
            elif key[0] == "p" and key[1:].isdigit():
                idx = int(key[1:]) - 1
                if idx >= len(plans):
                    continue
                sp, tag, facts = plans[idx]
                heading, lead, _s = P.action_for(scenario, tag)
                h = b.add("heading", heading)
                anchors.append(h.id); anchor_pos.append(f"第{idx + 1}节标题下")
                b.scene(lead)
                fs = point_facts(idx, facts)
                bridge = P.pick(P.BRIDGES, *k, "br", str(idx))
                if len(fs) >= 2 and idx % 2 == 0:
                    b.add("para", bridge.rstrip("：") + "：", [])
                    b.blocks[-1].note = "scene"
                    b.add("list", render_items(fs), [f.id for f in fs])
                else:
                    b.add("para", render_facts(fs, bridge), [f.id for f in fs])
                if not short and idx != 1:
                    b.scene(P.pick(SOWHAT, *k, "sw", str(idx)))
            elif key == "limit":
                b.add("heading", P.pick(HEAD_LIMIT, *k, "hl"))
                text, ids = limit_text("long")
                lb = b.add("callout", text, ids, "limit")
                anchors.append(lb.id); anchor_pos.append("限制段之后")
            elif key == "price":
                b.add("heading", P.pick(HEAD_PRICE, *k, "hp"))
                price_note = price_block(b, task, evidence)
            elif key == "checklist":
                b.add("heading", P.pick(HEAD_CHECK, *k, "hc"))
                b.add("list", "\n".join(sc["checklist"]), [], "scene")
        cta = sc["cta"]["wechat_mp"]

    # ================= 小红书 =================
    elif platform == "xiaohongshu":
        b.scene(hook["open"] if long else hook["short"] + " " + sc["scene2"].split("。")[0] + "。")
        anchors.append(None); anchor_pos.append("封面")
        first = True
        for key in sections:
            if key == "hook":
                continue
            if key == "scene":
                text, ids = model_intro_text()
                sb = b.add("para", text, ids)
                anchors.append(sb.id); anchor_pos.append("场景图（型号出场后）")
            elif key[0] == "p" and key[1:].isdigit():
                idx = int(key[1:]) - 1
                if idx >= len(plans):
                    continue
                sp, tag, facts = plans[idx]
                heading, lead, shortlead = P.action_for(scenario, tag)
                b.add("heading", heading)
                b.scene(shortlead if (short or idx > 0) else lead)
                fs = point_facts(idx, facts)
                pre = P.pick(P.BRIDGES_SHORT, *k, "br", str(idx))
                last = b.add("para", render_facts(fs, pre), [f.id for f in fs])
                anchors.append(last.id); anchor_pos.append(f"卖点{idx + 1}之后")
            elif key == "limit":
                b.add("heading", "一条要提前说的限制")
                text, ids = limit_text("xhs")
                lb = b.add("callout", text, ids, "limit")
                anchors.append(lb.id); anchor_pos.append("收尾图（限制之后）")
            elif key == "price":
                b.add("heading", "价格怎么看")
                price_note = price_block(b, task, evidence)
            elif key == "checklist":
                b.add("heading", "收藏用：核对清单")
                b.add("list", "\n".join(sc["checklist"]), [], "scene")
        cta = sc["cta"]["xiaohongshu"]

    # ================= 门店朋友圈 =================
    elif platform == "moments":
        b.scene(hook["short"] + P.pick([" 只说一件事。", " 一句话讲清楚。", " 给熟人的一条提醒。"], *k, "mm"))
        if plans:
            sp, tag, facts = plans[0]
            _h, _l, shortlead = P.action_for(scenario, tag)
            f = min(facts, key=lambda f: len(fact_sentence(f, with_constraints=False)))
            ids = [f.id] + ([ident.id] if ident else [])
            main = b.add("para", f"{shortlead}说回{model_short}：{fact_sentence(f, with_constraints=False)}", ids)
            anchors += [main.id] * 3; anchor_pos += ["文案下方·主图", "文案下方·细节图", "文案下方·补充图"]
        for key in sections:
            if key == "limit":
                text, ids = limit_text("short")
                b.add("callout", text, ids, "limit")
            elif key == "price":
                price_note = price_block(b, task, evidence, short=True)
        cta = sc["cta"]["moments"]

    # ================= 门店海报 =================
    else:
        pts = []
        for idx, (sp, tag, facts) in enumerate(plans[:3]):
            fs, txt = [], ""
            for f in facts:
                cand = render_facts(fs + [f])
                if fs and len(cand) > 110:
                    break
                fs.append(f)
                txt = cand
            pts.append({"label": P.TAG_LABEL.get(tag, ""), "text": txt, "fact_ids": [f.id for f in fs]})
        sub = P.pick(sc["poster_sub"], *k, "ps")
        b.add("heading", titles[0], [], "poster-title")
        b.add("para", sub, [], "scene")
        for pt in pts:
            b.add("heading", pt["label"], [], "poster-point")
            b.add("para", pt["text"], pt["fact_ids"])
        if ident:
            b.add("para", f"{model_name}。" + fact_sentence(ident, with_constraints=False), [ident.id], "model")
        for key in sections:
            if key == "limit":
                text, ids = limit_text("short")
                b.add("callout", text, ids, "limit")
            elif key == "price":
                price_note = price_block(b, task, evidence, short=True)
        anchors.append(None); anchor_pos.append("海报主视觉")
        date = _date_of(model.snapshot_date if model else "", *(f.verified_date for f in evidence.facts))
        poster = {"main_title": titles[0], "sub_title": sub, "points": pts,
                  "event_note": f"活动与价格请以华为官方渠道当日展示为准（资料核验日 {date}）" if date else "活动与价格请以华为官方渠道当日展示为准",
                  "image_id": evidence.images[0].id if evidence.images else "",
                  "cta": sc["cta"]["poster"]}
        cta = sc["cta"]["poster"]
        sub_title = sub
        intro = sub_title

    article = Article(
        platform=platform, titles=titles, title=titles[0], intro=intro, blocks=b.blocks, cta=cta,
        hashtags=_hashtags(strategy, scenario, model_short, platform), price_note=price_note, poster=poster,
        disclaimers=_disclaimers(task, strategy, evidence, model),
    )
    place_images(article, strategy, evidence, anchors, anchor_pos)
    finalize_article(article, evidence)
    _append_cons_note(article, evidence)
    return article


def _append_cons_note(article: Article, evidence: EvidencePack) -> None:
    """把全文借用的限定语集中到末尾一条“使用前请注意”，正文不再逐段复读。"""
    if _book is None:
        return
    cons = _book.tail()
    if not cons:
        return
    seen = "".join(b.text for b in article.blocks)
    keep: list[str] = []
    for c in cons:
        head = c.split("。")[0][:12]
        if head in seen:
            continue
        # 半句、无实质内容的提示不入尾注
        if len(c) < 8 or re.search(r"如有疑问|有问题|疑问|欢迎", c) and "前" not in c:
            continue
        keep.append(c)
    cons = keep[:6]
    if not cons:
        return
    if article.platform in ("moments", "poster"):
        text = "使用前请注意：" + "；".join(c.rstrip("。") for c in cons) + "。"
    else:
        text = ("上面这些参数和说法都带使用条件，发布前请逐条对照：\n"
                + "\n".join(f"- {c.rstrip('。')}" for c in cons))
    ids = list(dict.fromkeys([fid for b in article.blocks for fid in b.fact_ids]))[:12]
    article.blocks.append(Block(id=f"b{len(article.blocks) + 1}", kind="callout",
                                text=text, fact_ids=ids, note="limits"))


def _disclaimers(task: TaskSpec, strategy: Strategy, evidence: EvidencePack, model) -> list[str]:
    date = _date_of(model.snapshot_date if model else "", *(f.verified_date for f in evidence.facts))
    out = []
    if date:
        out.append(f"资料基准日 {date}，产品信息来自华为官方公开资料整理，以官方当日页面为准。")
    out.append("本文不含测试数据与用户评价。")
    sc = P.get_scenario(task.scenario)
    for s in sc["taboo"][:1]:
        pass
    return out


# --------------------------------------------------------------------------
# 图片放置 / 引用清单
# --------------------------------------------------------------------------
def place_images(article: Article, strategy: Strategy, evidence: EvidencePack,
                 anchors: list[Optional[str]], anchor_pos: list[str],
                 llm_plan: Optional[list[dict]] = None) -> None:
    """把 evidence.images 依序放到锚点后，生成 image 块与 ImageRef。anchors[i] 为 None 表示正文最前。"""
    model = evidence.models[0] if evidence.models else None
    mname = model.short_name if model else ""
    imgs = {i.id: i for i in evidence.images}
    plan: list[tuple[ImageAsset, Optional[str], str, str]] = []
    if llm_plan is not None:
        for it in llm_plan:
            plan.append((imgs[it["image_id"]], it.get("after_block") or None, it.get("position", ""), it.get("reason", "")))
    else:
        slots = strategy.image_slots
        for i, img in enumerate(evidence.images):
            slot = slots[i] if i < len(slots) else None
            anchor = anchors[i] if i < len(anchors) else (anchors[-1] if anchors else None)
            pos = anchor_pos[i] if i < len(anchor_pos) else (slot.slot if slot else f"配图{i + 1}")
            reason = (slot.purpose if slot else "补充画面") + f"；画面：{img.caption}" if img.caption else (slot.purpose if slot else "补充画面")
            plan.append((img, anchor, pos, reason))
    # 插入（同一锚点多张按顺序）
    for n, (img, after, pos, reason) in enumerate(plan, 1):
        blk = Block(id=f"img{n}", kind="image", text=img.caption, image_id=img.id, note="image")
        if not after:
            idx = 0
        else:
            idx = next((j for j, bb in enumerate(article.blocks) if bb.id == after), len(article.blocks) - 1) + 1
            while idx < len(article.blocks) and article.blocks[idx].kind == "image":
                idx += 1
        article.blocks.insert(idx, blk)
        article.image_refs.append(ImageRef(
            image_id=img.id, file_name=img.id, model_id=img.model_id, model_name=mname or img.model_id,
            caption=img.caption, position=pos, after_block=after or "", source_url=img.source_url,
            page_url=img.page_url, kb_path=img.kb_path, origin=img.origin, reason=reason))


def refresh_article(article: Article, evidence: EvidencePack) -> None:
    """核验/合规改动 blocks 之后，让 image_refs、sources、used_* 与实际保留的内容保持一致。"""
    keep_imgs = {bl.image_id for bl in article.blocks if bl.kind == "image"}
    if article.poster and article.poster.get("image_id"):
        keep_imgs.add(article.poster["image_id"])
    article.image_refs = [r for r in article.image_refs if r.image_id in keep_imgs]
    ids = {bl.id for bl in article.blocks}
    for r in article.image_refs:
        if r.after_block and r.after_block not in ids:
            r.after_block = ""
    if not any(bl.note.startswith("price:") for bl in article.blocks):
        article.price_note = ""
    finalize_article(article, evidence)


def finalize_article(article: Article, evidence: EvidencePack) -> None:
    """生成 sources、回填 used_fact_ids / used_image_ids。"""
    fmap = {f.id: f for f in evidence.facts}
    mmap = {m.model_id: m for m in evidence.models}
    order: list[str] = []
    for bl in article.blocks:
        for fid in bl.fact_ids:
            if fid not in order:
                order.append(fid)
    if article.poster:
        for pt in article.poster.get("points", []):
            for fid in pt.get("fact_ids", []):
                if fid not in order:
                    order.append(fid)
    article.sources = []
    for n, fid in enumerate(order, 1):
        f = fmap.get(fid)
        if not f:
            continue
        m = mmap.get(f.model_id)
        article.sources.append(SourceItem(
            ref=f"F{n:02d}", fact_id=f.id, model_name=m.name if m else f.model_id, text=f.text,
            source_title=f.source_title, source_path=f.source_path, source_urls=list(f.source_urls),
            verified_date=f.verified_date))
    evidence.used_fact_ids = [s.fact_id for s in article.sources]
    evidence.used_image_ids = [r.image_id for r in article.image_refs]


# --------------------------------------------------------------------------
# LLM 路径
# --------------------------------------------------------------------------
class LLMOutputError(ValueError):
    pass


def article_from_llm(data: dict, task: TaskSpec, strategy: Strategy, evidence: EvidencePack) -> Article:
    platform = task.platform or P.DEFAULT_PLATFORM
    pf = P.get_platform(platform)
    fids = {f.id for f in evidence.facts}
    iids = {i.id for i in evidence.images}
    if not isinstance(data, dict):
        raise LLMOutputError("模型输出不是 JSON 对象")
    if str(data.get("stop_reason") or "").strip():
        raise LLMOutputError("模型要求停止：" + str(data["stop_reason"])[:120])
    titles = [str(t).strip() for t in (data.get("titles") or []) if str(t).strip()]
    if len(titles) < pf["titles_min"]:
        raise LLMOutputError(f"标题备选不足（需要 {pf['titles_min']} 个，得到 {len(titles)} 个）")
    raw_blocks = data.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise LLMOutputError("blocks 为空")
    b = _Builder()
    price_seen = False
    for rb in raw_blocks:
        if not isinstance(rb, dict):
            raise LLMOutputError("block 不是对象")
        kind = rb.get("kind", "para")
        if kind not in VALID_KINDS or kind == "image":
            raise LLMOutputError(f"不支持的 block kind：{kind}")
        text = str(rb.get("text", "")).strip()
        if not text:
            continue
        ids = [str(x) for x in (rb.get("fact_ids") or [])]
        bad = [x for x in ids if x not in fids]
        if bad:
            raise LLMOutputError("引用了清单外的 fact_id：" + "、".join(bad[:3]))
        note = str(rb.get("note", ""))
        if note.startswith("price"):
            price_seen = True
            continue                          # 价格块一律由我们按 PriceRecord 重写
        b.add(kind, text, ids, note)
    if not b.blocks:
        raise LLMOutputError("blocks 无有效内容")
    ids_img, plan, seen = set(), [], set()
    valid_after = {bb.id for bb in b.blocks}
    for it in (data.get("images") or []):
        if not isinstance(it, dict):
            continue
        iid = str(it.get("image_id", ""))
        if iid not in iids:
            raise LLMOutputError(f"引用了清单外的 image_id：{iid[:40]}")
        if iid in seen:
            raise LLMOutputError("同一张图片被重复使用")
        seen.add(iid)
        after = str(it.get("after_block", "") or "")
        if after and after not in valid_after:
            after = ""
        plan.append({"image_id": iid, "after_block": after, "position": str(it.get("position", "")) or "正文中",
                     "reason": str(it.get("reason", "")) or "配合正文"})
    max_imgs = pf["img_range"][1]
    plan = plan[:max_imgs]
    if len(evidence.images) and not plan:
        pass                                   # 允许零图，后续核验/评分会体现
    model = evidence.models[0] if evidence.models else None
    # 限制段保证存在
    model_id = model.model_id if model else ""
    if not any(bb.note == "limit" for bb in b.blocks):
        limits = _limit_facts(evidence, model_id)
        if limits:
            b.add("callout", "；".join(fact_sentence(f, with_constraints=False).rstrip("。") for f in limits) + "。下单前请自行核对。",
                  [f.id for f in limits], "limit")
    price_note = ""
    if task.want_price and evidence.prices:
        price_note = price_block(b, task, evidence, short=platform in ("moments", "poster"))
    cta = str(data.get("cta") or "").strip() or P.get_scenario(task.scenario)["cta"][platform]
    hashtags = [str(h) for h in (data.get("hashtags") or [])] if platform == "xiaohongshu" else []
    poster = None
    intro = str(data.get("intro") or "")
    if platform == "poster":
        pr = data.get("poster")
        if not isinstance(pr, dict):
            raise LLMOutputError("海报缺少 poster 对象")
        pts = pr.get("points") or []
        if not (1 <= len(pts) <= 3):
            raise LLMOutputError("海报卖点需为 1–3 条")
        clean = []
        for pt in pts:
            ids = [str(x) for x in (pt.get("fact_ids") or [])]
            if any(x not in fids for x in ids):
                raise LLMOutputError("海报卖点引用了清单外的 fact_id")
            clean.append({"label": str(pt.get("label", "")), "text": str(pt.get("text", "")), "fact_ids": ids})
        img_id = str(pr.get("image_id") or (plan[0]["image_id"] if plan else (evidence.images[0].id if evidence.images else "")))
        if img_id and img_id not in iids:
            raise LLMOutputError("海报主视觉不在清单内")
        poster = {"main_title": str(pr.get("main_title") or titles[0]), "sub_title": str(pr.get("sub_title", "")),
                  "points": clean, "event_note": str(pr.get("event_note", "")), "image_id": img_id,
                  "cta": str(pr.get("cta") or cta)}
        intro = poster["sub_title"]
        plan = [{"image_id": img_id, "after_block": "", "position": "海报主视觉", "reason": "海报主视觉，按原比例展示"}] if img_id else []
    art = Article(platform=platform, titles=titles, title=titles[0], intro=intro, blocks=b.blocks, cta=cta,
                  hashtags=hashtags, price_note=price_note, poster=poster,
                  disclaimers=_disclaimers(task, strategy, evidence, model))
    pend = [str(x) for x in (data.get("pending") or []) if str(x).strip()]
    art.disclaimers += ["待确认：" + p for p in pend[:5]]
    place_images(art, strategy, evidence, [], [], llm_plan=plan)
    finalize_article(art, evidence)
    return art


def compose(task: TaskSpec, strategy: Strategy, evidence: EvidencePack, llm=None) -> tuple[Article, EngineInfo]:
    info = dict(prompt_version=PROMPT_VERSION)
    if llm is not None:
        try:
            data = llm.chat_json(SYSTEM_PROMPT, build_user_message(task, strategy, evidence))
            art = article_from_llm(data, task, strategy, evidence)
            return art, EngineInfo(writer="llm", llm_model=getattr(llm, "model", ""), **info)
        except Exception as e:  # noqa: BLE001  任何失败都降级，并如实标注（异常文本不含 key）
            reason = f"{type(e).__name__}: {str(e)[:160]}"
            art = compose_with_composer(task, strategy, evidence)
            ei = EngineInfo(writer="composer", llm_model=getattr(llm, "model", ""),
                            note=f"LLM 路径失败，已自动降级到确定性 Composer（{reason}）", **info)
            return art, ei
    art = compose_with_composer(task, strategy, evidence)
    return art, EngineInfo(writer="composer", note="未配置 LLM，使用确定性 Composer", **info)
