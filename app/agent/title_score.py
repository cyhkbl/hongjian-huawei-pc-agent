"""标题评分：告诉销售员哪个标题更吸引人，以及为什么。

不调模型，用可解释的特征打分。每条理由都能对应到标题里的具体片段，
销售员看完知道该往哪个方向改。
"""
from __future__ import annotations

import re
from typing import Optional

from app.agent import profiles as P
from app.models import PlatformId, TitleScore

# 特征词表：命中就加分，并在理由里指出命中位置
_HOOKS = {
    "数字": (r"\d", 8, "带具体数字的标题更容易被点开"),
    "人群指向": (r"大学生|新生|学弟|学妹|学生|家长|父母|爸妈|出差|职场|打工|行政|IT|设计师|剪辑|博主|老人", 10,
              "点名了具体人群，读者容易代入"),
    "痛点词": (r"累|卡|慢|麻烦|绕路|踩坑|纠结|焦虑|撑不住|不够用|变重|变色|背不动", 12,
             "点了读者真实的麻烦，比形容词有效"),
    "悬念": (r"为什么|居然|原来|才发现|之前|之后|先看|先说|秘密|真相", 8, "制造了一点悬念"),
    "季节节点": (r"开学|返校|双11|双十一|春节|中秋|国庆|618|新年|过节|节日|礼物|送礼", 10,
              "赶上节点，搜索和推荐都更有利"),
    "行动暗示": (r"先看|先问|先列|清单|功课|核对|对照|收藏", 7, "给了读者一个明确动作"),
    "口语化": (r"真的|绝了|姐妹们|兄弟|说实话|讲真|我感觉|我个人|一站式|抄作业", 6, "口语表达更接近小红书语感"),
}
_PENALTIES = {
    "绝对化": (r"最强|第一|唯一|全网|顶级|极致|完美|无敌|史上|秒杀|吊打", -18,
              "绝对化用语有合规风险，也会降低可信度"),
    "套话": (r"震撼|颠覆|重新定义|革新|引领|赋能|加持|巅峰|传奇", -12, "这类词信息量低，读者会跳过"),
    "过长": (None, -10, "标题偏长，手机上会被截断"),
}

_PLATFORM_BONUS = {
    "xiaohongshu": {"口语化": 1.4, "人群指向": 1.2, "痛点词": 1.3},
    "wechat_mp": {"行动暗示": 1.2, "季节节点": 1.1},
    "moments": {"痛点词": 1.2, "人群指向": 1.1},
    "poster": {"数字": 1.2, "人群指向": 1.2},
}


def score_title(title: str, platform: PlatformId, model_name: str = "") -> TitleScore:
    t = (title or "").strip()
    if not t:
        return TitleScore(title=title, score=0, reasons=["标题为空"], tags=[])

    score = 55.0                      # 基准分：一个中规中矩的标题
    reasons: list[str] = []
    tags: list[str] = []
    bonus = _PLATFORM_BONUS.get(platform, {})

    for name, (rx, pts, why) in _HOOKS.items():
        if not rx:
            continue
        m = re.search(rx, t)
        if m:
            w = bonus.get(name, 1.0)
            gain = pts * w
            score += gain
            tags.append(name)
            if w != 1.0:
                reasons.append(f"{why}（「{m.group(0)}」，{P.PLATFORM_LABELS.get(platform, platform)}更吃这一套，加权 {w:.1f}）")
            else:
                reasons.append(f"{why}（「{m.group(0)}」）")

    for name, (rx, pts, why) in _PENALTIES.items():
        if name == "过长":
            if len(t) > 22:
                score += pts
                reasons.append(f"{why}（当前 {len(t)} 字）")
            continue
        m = re.search(rx, t)
        if m:
            score += pts
            reasons.append(f"{why}（「{m.group(0)}」）")

    # 提到机型名是加分项：读者知道在说哪台
    if model_name and model_name in t:
        score += 6
        tags.append("点名机型")
        reasons.append(f"点名了「{model_name}」，读者不用猜")

    score = max(5, min(100, int(round(score))))
    if not reasons:
        reasons.append("标题中规中矩：没有明显亮点，也没有风险词。可以加入具体人群或痛点词。")
    return TitleScore(title=t, score=score, reasons=reasons[:6], tags=tags)


def score_titles(titles: list[str], platform: PlatformId, model_name: str = "") -> list[TitleScore]:
    out = [score_title(t, platform, model_name) for t in titles]
    out.sort(key=lambda s: -s.score)
    return out
