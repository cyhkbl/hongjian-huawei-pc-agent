"""对话式需求挖掘。

不用表单，改用「Agent 问、用户点」的多轮对话。每一轮问什么由当前已知信息动态决定：
缺机型先问机型，机型有歧义就出带差异说明的选项，机型定了再问场景，场景定了问渠道。

设计原则：
- 最多 4 轮，之后用合理默认值补齐，并把补了什么如实告诉用户。
- 每轮都是选择题（点一下即可），也允许自己输入，还允许"你帮我定"。
- 问句带 why：让用户明白为什么问这个，而不是被盘问。
"""
from __future__ import annotations

import time
from typing import Optional

from app.agent import profiles as P
from app.kb.base import KnowledgeBase
from app.models import (
    ChatChoice, ChatRequest, ChatState, ChatTurn, ClarifyOption, Clarification, TaskSpec,
)

MAX_TURNS = 4

# 问题顺序模板：(字段, 优先级)。前面的缺口没补上前面的不问。
_ORDER = ["model", "scenario", "platform", "audience", "selling_point"]

_SCENARIO_QUESTIONS = {
    "back_to_school": ("这台电脑给谁用？", ["即将入学或返校的大学生", "帮孩子挑电脑的家长", "研究生或博士生"]),
    "office": ("使用者平时的办公状态更接近哪种？", ["经常出差的移动办公", "固定在工位的文档处理", "频繁开会与多设备协同"]),
    "creator": ("创作类型更接近哪个？", ["视频剪辑与调色", "设计与摄影修图", "文案策划与素材整理"]),
    "home_upgrade": ("这台电脑主要给谁用？", ["全家共用的家庭主力机", "给父母替换旧电脑", "孩子学习与上网课"]),
    "enterprise_procurement": ("采购主要卡在哪一步？", ["批量部署与统一管理", "业务软件兼容验证", "售后与的服务条款"]),
    "store_visit": ("顾客到店最想知道的一点是什么？", ["这台机器轻不轻、好不好带", "屏幕看着舒不舒服", "接口够不够用、要不要转接"]),
    "new_launch": ("读者最关心新品的哪一面？", ["新品相比上一代变了什么", "新品适合什么样的人", "新品现在多少钱"]),
    "festival": ("这份礼物送给谁？", ["送给自己", "送给家人", "送给学生或刚工作的人"]),
}
_SCENARIO_HINTS = {
    "back_to_school": "场景定了，问句会跟着变——这是为了文案切入点对准读者。",
    "office": "同样问机型，问法不同，写出来的稿子也不同。",
    "creator": "创作场景要避开虚构测试结果，所以先确认创作类型。",
    "home_upgrade": "家庭换新重视易用性和数据迁移，先确认使用者。",
    "enterprise_procurement": "企业采购要承诺 KB 之外的政策，先确认卡点。",
    "store_visit": "门店到访只讲一个卖点，先确认顾客最想知道什么。",
    "new_launch": "新品首发涉及价格与权益，必须有资料依据。",
    "festival": "节日营销不得虚构优惠补贴库存，先确认送礼对象。",
}


def _model_choices(kb: KnowledgeBase) -> list[ChatChoice]:
    """十个重点型号，每个带一句差异说明。"""
    out: list[ChatChoice] = []
    for m in kb.models():
        os_label = m.os_label or m.os_family
        price = "有公开价" if m.has_public_price else "官方询价/未公开"
        hint = f"{os_label}｜{price}"
        if m.confusable_with:
            hint += "｜注意与相近型号区分"
        out.append(ChatChoice(value=m.model_id, label=m.short_name, hint=hint))
    return out


def _confusable_choices(kb: KnowledgeBase, model_id: str) -> list[ChatChoice]:
    """机型有歧义时，把相近型号并排给出，带差异说明。"""
    out: list[ChatChoice] = []
    m = kb.get_model(model_id)
    if m:
        out.append(ChatChoice(value=m.model_id, label=m.short_name + "（你提到的）",
                              hint=m.os_label or m.os_family))
    for cid in (m.confusable_with if m else []):
        c = kb.get_model(cid)
        if c:
            out.append(ChatChoice(value=c.model_id, label=c.short_name,
                                  hint=f"相近型号：{c.os_label or c.os_family}"))
    return out


def _scenario_choices(scenario: str) -> list[ChatChoice]:
    q = _SCENARIO_QUESTIONS.get(scenario)
    if not q:
        return []
    return [ChatChoice(value=v, label=v) for v in q[1]]


def _platform_choices() -> list[ChatChoice]:
    out = []
    for pid in ("wechat_mp", "xiaohongshu", "moments", "poster"):
        label = P.PLATFORM_LABELS.get(pid, pid)
        hint = P.PLATFORM_HINTS.get(pid, "")
        out.append(ChatChoice(value=pid, label=label, hint=hint))
    return out


def _audience_choices(scenario: str) -> list[ChatChoice]:
    q = _SCENARIO_QUESTIONS.get(scenario)
    if not q:
        return []
    return [ChatChoice(value=v, label=v) for v in q[1]]


def _selling_choices(kb: KnowledgeBase, model_id: str) -> list[ChatChoice]:
    """主卖点选项：从该机型有事实支撑的维度里取，不凭空给。"""
    from app.agent.strategy import _tag_candidates  # noqa: PLC0415
    facts = kb.facts(model_id)
    if not facts:
        return []
    cands = _tag_candidates(facts, P.DEFAULT_SCENARIO, P.DEFAULT_PLATFORM, model_id, None)
    out: list[ChatChoice] = []
    for score, tag, _fs in cands[:5]:
        label = P.TAG_LABEL.get(tag, tag)
        out.append(ChatChoice(value=tag, label=label, hint=f"该机型在这一项上有资料支撑（权重 {score:.2f}）"))
    return out


def _next_question(state: ChatState, kb: KnowledgeBase) -> Optional[ChatTurn]:
    """动态规划：按 _ORDER 找第一个还缺的字段，缺什么问什么。"""
    for field in _ORDER:
        if state.known.get(field):
            continue
        if field in state.asked and field != "model":
            continue
        state.asked.append(field)

        if field == "model":
            # 机型没定时，如果用户之前提过系列名，先做歧义确认
            return ChatTurn(
                question_id="q_model",
                question="想写哪台机器？",
                why="机型决定能引用哪些参数和图片，相近型号不能混用。",
                choices=_model_choices(kb),
                free_text_hint="也可以直接说型号，比如 MateBook 14 鸿蒙版",
            )
        if field == "scenario":
            return ChatTurn(
                question_id="q_scenario",
                question="这篇稿子发在什么场景下？",
                why="场景决定切入角度、卖点顺序和该避开的说法。",
                choices=[ChatChoice(value=k, label=P.SCENARIO_LABELS.get(k, k),
                                    hint=P.SCENARIO_HINTS.get(k, "")) for k in P.SCENARIOS],
                free_text_hint="比如开学季、职场办公、门店到访",
            )
        if field == "platform":
            return ChatTurn(
                question_id="q_platform",
                question="发在哪个渠道？",
                why="渠道决定标题风格、篇幅、结构、图片数量和行动引导。",
                choices=_platform_choices(),
                free_text_hint="公众号、小红书、门店朋友圈或门店海报",
            )
        if field == "audience":
            sc = state.known.get("scenario", "")
            ch = _audience_choices(sc)
            if not ch:
                state.known["audience"] = P.get_scenario(sc)["audience"] if sc else ""
                continue
            return ChatTurn(
                question_id="q_audience",
                question=_SCENARIO_QUESTIONS.get(sc, ("读者是哪类人？", []))[0],
                why=_SCENARIO_HINTS.get(sc, "人群决定语气和该讲的痛点。"),
                choices=ch,
                allow_skip=True,
                free_text_hint="也可以自己描述，比如刚入职的运营",
            )
        if field == "selling_point":
            mid = state.known.get("model", "")
            ch = _selling_choices(kb, mid)
            if not ch:
                state.known["selling_point"] = ""
                continue
            return ChatTurn(
                question_id="q_selling_point",
                question="最想突出哪个卖点？",
                why="指定主卖点会覆盖自动排序，并说明为什么这样排。",
                choices=ch,
                allow_skip=True,
                free_text_hint="也可以说「随便，你按场景排」",
            )
    return None


def _apply_defaults(state: ChatState, kb: KnowledgeBase) -> None:
    """超过轮次上限后补默认值，并如实记录补了什么。"""
    if not state.known.get("model"):
        state.known["model"] = kb.models()[0].model_id if kb.models() else ""
        state.defaults_applied.append("机型未指定，已按资料里最常见的重点型号处理")
    if not state.known.get("scenario"):
        state.known["scenario"] = P.DEFAULT_SCENARIO
        state.defaults_applied.append(f"场景未指定，已默认{P.SCENARIO_LABELS.get(P.DEFAULT_SCENARIO, '')}")
    if not state.known.get("platform"):
        state.known["platform"] = P.DEFAULT_PLATFORM
        state.defaults_applied.append(f"渠道未指定，已默认{P.PLATFORM_LABELS.get(P.DEFAULT_PLATFORM, '')}")
    if not state.known.get("audience"):
        sc = P.get_scenario(state.known.get("scenario", P.DEFAULT_SCENARIO))
        state.known["audience"] = sc["audience"]
        state.defaults_applied.append("人群未指定，已按场景的默认人群处理")
    state.ready = True


def _to_task(state: ChatState) -> TaskSpec:
    k = state.known
    return TaskSpec(
        raw=" / ".join(f"{a}={b}" for a, b in k.items() if b),
        model_ids=[k["model"]] if k.get("model") else [],
        platform=k.get("platform") or None,
        scenario=k.get("scenario") or None,
        audience=k.get("audience", ""),
        selling_point=k.get("selling_point", ""),
        missing=[] if state.ready else list(_ORDER),
    )


def start_session(kb: KnowledgeBase, session_id: str = "") -> ChatState:
    state = ChatState(session_id=session_id or f"chat-{int(time.time()*1000)}")
    state.pending = _next_question(state, kb)
    if state.pending is None:
        _apply_defaults(state, kb)
    return state


def chat(req: ChatRequest, kb: KnowledgeBase, state: Optional[ChatState] = None) -> tuple[ChatState, TaskSpec]:
    """处理一轮对话。返回更新后的状态和当前已能拼出的 TaskSpec。"""
    state = state or start_session(kb, req.session_id)

    # 用户的回答
    if req.skip:
        # "你帮我定"：当前这个字段留空，靠默认值补
        if state.pending:
            state.known[state.pending.question_id[2:]] = ""
    elif req.choice_value and state.pending:
        state.known[state.pending.question_id[2:]] = req.choice_value
    elif req.text.strip():
        # 自然语言回答：先用 understand 解析，解析不出就当自由文本
        from app.agent.understand import parse_task  # noqa: PLC0415
        from app.models import RunRequest  # noqa: PLC0415
        parsed, _ = parse_task(RunRequest(text=req.text), kb)
        field = state.pending.question_id[2:] if state.pending else None
        if field == "model" and parsed.model_ids:
            state.known["model"] = parsed.model_ids[0]
        elif field == "platform" and parsed.platform:
            state.known["platform"] = parsed.platform
        elif field == "scenario" and parsed.scenario:
            state.known["scenario"] = parsed.scenario
        elif field == "audience" and parsed.audience:
            state.known["audience"] = parsed.audience
        elif field == "selling_point" and parsed.selling_point:
            state.known["selling_point"] = parsed.selling_point
        else:
            # 解析不出来，按自由文本收下
            state.known[field or "extras"] = req.text.strip()

    state.turns_used += 1

    if state.turns_used >= MAX_TURNS:
        _apply_defaults(state, kb)
        state.pending = None
    else:
        state.pending = _next_question(state, kb)
        if state.pending is None:
            _apply_defaults(state, kb)

    return state, _to_task(state)


def clarify_from_chat(state: ChatState) -> list[Clarification]:
    """把对话状态翻成旧的 Clarification 结构，兼容现有前端与自测。"""
    if not state.pending:
        return []
    t = state.pending
    field = t.question_id[2:]
    return [Clarification(
        field=field if field in ("model", "platform", "scenario", "audience", "config", "price_sku", "other") else "other",
        question=t.question, reason=t.why,
        options=[ClarifyOption(value=c.value, label=c.label, hint=c.hint) for c in t.choices],
        allow_free_text=bool(t.free_text_hint),
    )]
