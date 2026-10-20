"""今日推荐：告诉门店销售员「今天该写什么」。

评委 tip 里最实在的一句：操作要足够简单，让门店销售员减少工作量，他们才愿意去创作发表。
所以这个模块不追求"能写什么"，而是反过来——主动给出今天最值得写的几个选题，
每个都能一键生成，改几个字就能发。

选题来源（全部可解释，不拍脑袋）：
1. 日历：当前月份/距离哪个节点近，对应到赛题的 8 个场景。
2. 新品：知识库里有公开价、且价格记录核验时间最近的型号。
3. 缺口：这个型号还没写过哪个平台，补上。
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from app.agent import profiles as P
from app.kb.base import KnowledgeBase
from app.models import DailyIdea, PlatformId, ScenarioId

# 月份 → 场景。开学季（2-3 月、8-9 月）权重最高，节日营销按公历节日排。
_MONTH_SCENARIOS: dict[int, list[ScenarioId]] = {
    1: ["festival", "home_upgrade"],
    2: ["back_to_school", "festival"],
    3: ["back_to_school"],
    4: ["home_upgrade", "office"],
    5: ["festival", "office"],
    6: ["festival", "back_to_school"],
    7: ["back_to_school", "office"],
    8: ["back_to_school", "office"],
    9: ["back_to_school", "enterprise_procurement"],
    10: ["festival", "new_launch"],
    11: ["festival", "home_upgrade"],
    12: ["festival", "home_upgrade"],
}

_SEASON_NOTE = {
    "back_to_school": "开学前后是学生购机高峰",
    "festival": "节日节点送礼与家庭购机集中",
    "new_launch": "新品关注度高，适合首发内容",
    "office": "年初与年中是办公设备更新窗口",
    "home_upgrade": "长假前家庭换新需求上升",
    "enterprise_procurement": "年底预算与采购窗口",
    "creator": "内容创作者全年都有设备升级需求",
    "store_visit": "周末到店客流多，适合短平快的到店内容",
}

_IDEA_TEMPLATES: dict[str, list[str]] = {
    "back_to_school": [
        "新生选电脑，先看这几项",
        "开学前的电脑功课，一篇说清",
        "宿舍党选电脑，先列清单再下单",
    ],
    "office": [
        "出差党的电脑清单，重量和续航排前面",
        "工位效率：一台电脑要接几件事",
        "会议多的岗位，先看协同和接口",
    ],
    "creator": [
        "修图剪片，先看屏幕口径",
        "素材流转顺不顺，比参数更影响产出",
        "创作本的选购，别只看跑分",
    ],
    "home_upgrade": [
        "给爸妈换电脑，先问清三件事",
        "全家共用的一台，怎么挑不吵架",
        "旧机数据迁移，买之前先想好",
    ],
    "enterprise_procurement": [
        "批量换电脑，先试点再扩量",
        "采购评审前，把能确认的和要询价的分开",
        "IT 部署先看管理和兼容",
    ],
    "store_visit": [
        "到店三分钟，看明白一个卖点",
        "展台前先问自己要不要带出门",
        "试机时重点摸这两个地方",
    ],
    "new_launch": [
        "新品变化，一屏看清",
        "这台新品适合什么样的人",
        "新品首发，先看口径再看价格",
    ],
    "festival": [
        "送电脑之前，先想两步",
        "节日换电脑，我会先看这几项",
        "礼物选电脑，怎么不踩坑",
    ],
}


def _recent_price_model(kb: KnowledgeBase) -> Optional[str]:
    """挑一个价格记录核验时间较新的型号，用于「新品首发」选题。"""
    best: tuple[str, str] = ("", "")
    for m in kb.models():
        if not m.has_public_price:
            continue
        for p in kb.prices(m.model_id):
            if p.verified_at and p.verified_at > best[1]:
                best = (m.model_id, p.verified_at)
    return best[0] or None


def _covered_platforms(kb: KnowledgeBase, model_id: str) -> list[PlatformId]:
    """这个型号在四个平台里都还没被推荐过——用图片数和价格状态粗判覆盖度。"""
    # 简化：不依赖历史记录（无持久化时），按型号图片数判断能撑起几个平台
    n = len(kb.images(model_id))
    out: list[PlatformId] = []
    if n >= 1:
        out += ["poster", "moments"]
    if n >= 2:
        out += ["wechat_mp"]
    if n >= 3:
        out += ["xiaohongshu"]
    return out


def daily_ideas(kb: KnowledgeBase, today: Optional[dt.date] = None, limit: int = 4) -> list[DailyIdea]:
    today = today or dt.date.today()
    month = today.month
    scenarios = _MONTH_SCENARIOS.get(month, ["office"])
    ideas: list[DailyIdea] = []

    fresh = _recent_price_model(kb)
    ordered: list[ScenarioId] = list(scenarios)
    if fresh and "new_launch" not in ordered:
        ordered.insert(0, "new_launch")
    # 场景不够时，用全年都有需求的场景补足，保证每天都有得写
    for filler in ("store_visit", "office", "creator", "home_upgrade", "enterprise_procurement"):
        if len(ordered) >= limit:
            break
        if filler not in ordered:
            ordered.append(filler)

    used: set[str] = set()
    for sc in ordered:
        if len(ideas) >= limit:
            break
        # 每个场景挑该场景下最合身、且还没推荐过的型号
        mid = _best_model_for(kb, sc, exclude=used)
        if not mid:
            continue
        used.add(mid)
        m = kb.get_model(mid)
        if not m:
            continue
        avail = _covered_platforms(kb, mid)
        # 优先推荐该机型图片够用的平台；小红书最能吸引人，图片够就优先
        pf = "xiaohongshu" if "xiaohongshu" in avail else (avail[0] if avail else "moments")
        tpl = _IDEA_TEMPLATES.get(sc, [])
        title = tpl[0] if tpl else f"{P.SCENARIO_LABELS.get(sc, sc)}：{m.short_name}"
        reason = _SEASON_NOTE.get(sc, "")
        if sc == "new_launch":
            reason = f"{m.short_name} 有近期核验的官方价格记录，适合首发内容"
        ideas.append(DailyIdea(
            idea_id=f"{sc}-{mid}-{pf}",
            title=title,
            scenario=sc,
            platform=pf,
            model_id=mid,
            model_name=m.short_name,
            reason=reason,
            season_tag=P.SCENARIO_LABELS.get(sc, sc),
        ))
    return ideas[:limit]


def _best_model_for(kb: KnowledgeBase, scenario: str, exclude: Optional[set] = None) -> Optional[str]:
    """按场景权重挑一个卖点最足的型号；exclude 里的型号不再推荐。"""
    from app.agent.strategy import _tag_candidates  # noqa: PLC0415
    sc = P.get_scenario(scenario)
    exclude = exclude or set()
    best: tuple[float, str] = (-1.0, "")
    for m in kb.models():
        if m.model_id in exclude:
            continue
        facts = kb.facts(m.model_id)
        if not facts:
            continue
        cands = _tag_candidates(facts, scenario, P.DEFAULT_PLATFORM, m.model_id, None)
        if not cands:
            continue
        top_tag, top_score = cands[0][1], cands[0][0]
        fit = P.model_fit(m.model_id)
        score = top_score + fit.get("bonus", {}).get(top_tag, 0.0)
        if score > best[0]:
            best = (score, m.model_id)
    if best[1]:
        return best[1]
    for m in kb.models():
        if m.model_id not in exclude:
            return m.model_id
    return None
