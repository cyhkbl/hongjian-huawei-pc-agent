"""Task understanding: deterministic, rule + vocabulary based (no LLM).

parse_task(req, kb) -> (TaskSpec, [Clarification])

Principles
- Never silently pick between look-alike models. A *literal* official name that
  maps to exactly one model is used as written, and the look-alike goes into
  ``confusion_notes``. A shared/series name ("MateBook 14") is asked back.
- Missing model / platform / scenario -> Clarification with options.
- Requests we must refuse or rewrite are recorded verbatim in
  ``TaskSpec.blocked_requests`` (see ``blocked_reason`` for the Chinese reason).
"""
from __future__ import annotations

import re
from typing import Optional

from app.agent.rules_common import dedupe, nfkc, squash
from app.kb.base import KnowledgeBase
from app.models import (
    Clarification, ClarifyOption, ProductModel, RunRequest, TaskSpec,
)

# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------
PLATFORM_LABELS = {
    "wechat_mp": "公众号",
    "xiaohongshu": "小红书",
    "moments": "门店朋友圈",
    "poster": "门店海报",
}
PLATFORM_HINTS = {
    "wechat_mp": "标题、导语、分节、结尾行动引导，配图 2–4 张",
    "xiaohongshu": "口语标题、短段落、话题标签，配图 3–6 张",
    "moments": "短文案，只讲 1 个核心卖点，配图 1–3 张",
    "poster": "主副标题、不超过 3 个卖点、活动说明，1 张主视觉",
}
SCENARIO_LABELS = {
    "back_to_school": "开学季",
    "office": "职场办公",
    "creator": "内容创作",
    "home_upgrade": "家庭换新",
    "enterprise_procurement": "企业采购",
    "store_visit": "门店到访",
    "new_launch": "新品首发",
    "festival": "节日营销",
}
SCENARIO_HINTS = {
    "back_to_school": "面向大学新生和返校学生",
    "office": "通勤、会议、出差等办公场景",
    "creator": "剪辑、设计、绘图等创作场景",
    "home_upgrade": "家用、给父母或孩子换电脑",
    "enterprise_procurement": "企业 IT 与批量采购",
    "store_visit": "邀请顾客到店体验",
    "new_launch": "新品首发与发布",
    "festival": "节日大促（不编造折扣和补贴）",
}

# --------------------------------------------------------------------------
# Platform / scenario vocabularies
# --------------------------------------------------------------------------
_PLATFORM_WORDS: dict[str, list[str]] = {
    "wechat_mp": ["微信公众号", "公众号", "微信文章", "公号", "推文", "微信推送"],
    "xiaohongshu": ["小红书", "红薯", "种草笔记", "xhs", "rednote"],
    "moments": ["门店朋友圈", "微信朋友圈", "朋友圈"],
    "poster": ["门店海报", "海报", "易拉宝", "kt板", "kt 板", "x展架", "展架", "展板"],
}

# explicit scenario words / audience-level words (second tier: add a note)
_SCENARIO_WORDS: dict[str, tuple[list[str], list[str]]] = {
    "back_to_school": (
        ["开学季", "开学", "返校", "入学季", "入学"],
        ["新生", "大学生", "学生党", "学生", "同学", "校园", "大学", "研究生"],
    ),
    "office": (
        ["职场办公", "办公", "职场", "通勤", "出差", "商务差旅", "会议"],
        ["上班族", "打工人", "白领", "职场人", "职场新人"],
    ),
    "creator": (
        ["内容创作", "视频剪辑", "剪辑", "设计创作", "创作", "绘图", "修图", "设计"],
        ["创作者", "设计师", "博主", "剪辑师", "摄影师", "插画师", "自媒体", "up主"],
    ),
    "home_upgrade": (
        ["家庭换新", "换新", "换机", "家用", "居家"],
        ["父母", "爸妈", "长辈", "家里人", "家庭", "家里", "孩子"],
    ),
    "enterprise_procurement": (
        ["企业采购", "批量采购", "采购", "集采", "批量", "团购", "政企"],
        ["企业", "公司", "it部门", "信息化", "行政"],
    ),
    "store_visit": (
        ["到店体验", "到店", "体验店", "线下体验", "店里", "门店", "探店"],
        ["到店顾客", "进店"],
    ),
    "new_launch": (
        ["新品首发", "新品", "首发", "发布会", "发布", "上市", "新款", "发售", "开售", "预售", "新机"],
        [],
    ),
    "festival": (
        ["双十一", "双11", "双十二", "双12", "春节", "新年", "年货", "中秋", "国庆", "618",
         "六一八", "元旦", "圣诞", "七夕", "情人节", "端午", "五一", "劳动节", "黑五", "年终",
         "大促", "节日", "节庆", "送礼"],
        [],
    ),
}
# "IT" needs ASCII word boundaries
_IT_RE = re.compile(r"(?<![A-Za-z])IT(?![A-Za-z])")
# platform phrases that contain 门店 but do not mean the 门店到访 scenario
_STORE_PLATFORM_RE = re.compile(r"门店(?:的)?(?:朋友圈|海报|易拉宝|kt\s*板|展架|展板)", re.I)

_AUDIENCE_WORDS = [
    "大学新生", "新生", "大学生", "学生党", "研究生", "学生", "上班族", "打工人", "职场新人", "白领",
    "设计师", "创作者", "剪辑师", "摄影师", "博主", "自媒体", "父母", "爸妈", "长辈", "孩子",
    "企业客户", "企业 IT", "IT 采购", "采购负责人", "到店顾客", "家庭用户",
]
_AUDIENCE_RES = [
    re.compile(r"(?:面向|针对|面对|写给|送给|目标人群(?:是|为)?|目标用户(?:是|为)?|受众(?:是|为)?|人群(?:是|为))[:：]?\s*"
               r"([^，。,.；;！!？?\s]{2,16}?)(?=的|[，。,.；;！!？?\s]|写|做|发|$)"),
]

_CATEGORY_RE = re.compile(
    r"轻薄本|轻薄笔记本|笔记本电脑|笔记本|手提电脑|电脑|本子|二合一|全能本|办公本|商务本|学生本|游戏本|"
    r"华为(?:电脑|笔记本)|\bpc\b|matebook(?!\s*[a-z0-9])", re.I)
_THIN_RE = re.compile(r"轻薄|便携|轻便|薄")

_SELLING_CUE = r"(?:主卖点|主打|突出|重点(?:写|讲|突出)?|强调|侧重|主推|聚焦|围绕|卖点(?:是|为|换成|改成|定为)?|换成|改成|着重)"
_SELLING_MAP: list[tuple[str, str]] = [
    ("续航", r"续航|电池|电量|充电"),
    ("屏幕", r"屏幕|显示|护眼|色彩|OLED|oled|触控屏"),
    ("轻薄便携", r"轻薄|便携|重量|轻便|随身"),
    ("接口扩展", r"接口|扩展|拓展|外接"),
    ("性能", r"性能|处理器|芯片|算力|跑得快|流畅"),
    ("多设备协同", r"协同|多设备|跨设备|超级终端|互联"),
    ("手写触控", r"手写|触控|笔"),
    ("影像音频", r"摄像头|影像|音频|扬声器|麦克风|通话"),
    ("AI 能力", r"\bAI\b|智能体|小艺"),
]

# --------------------------------------------------------------------------
# Blocked requests
# --------------------------------------------------------------------------
_COMPETITORS = (r"苹果|联想|戴尔|惠普|华硕|小米|荣耀|三星|宏碁|微软|雷蛇|机械革命|MacBook|Macbook|Mac|"
                r"ThinkPad|Surface|Dell|HP|Lenovo|Apple|小新|拯救者|\bMBA\b|\bMBP\b")
_NEG_BEFORE = re.compile(r"(?:不要|别|不写|不用|不提|不能|无需|禁止|勿|避免|去掉|删掉|删除|不得|不可|严禁|拒绝|杜绝|不含|不带|不放|不涉及|拿掉)[^，。,.；;！!？?]{0,6}$")
_VERB = r"(?:写|加|带|标|编|来|搞|提|放|附|注明|突出|强调|宣传|主打|用|整|配)"
_AMT_TAIL = r"(?:\s*\d+(?:\.\d+)?\s*(?:元|块|%|折)?)?"
_DYN_TERM = (r"国补|国家补贴|政府补贴|教育补贴|教育优惠|补贴|以旧换新补贴|立减|直降|直减|满减|减免|返现|优惠券|"
             r"限时(?:特价|优惠|折扣|秒杀)?|秒杀|赠品|送(?:鼠标|耳机|包|礼|好礼|大礼包)|分期免息|免息分期|0\s*元购|"
             r"库存(?:充足|紧张)?|现货|抢购|限量|折扣|打折|特价")

# (category, regex)
BLOCK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("fabricated_price", re.compile(
        r"(?:(?:编|瞎编|杜撰|虚构|随便|随意|估|估算|拍脑袋|大概|假设|凑)[^，。,.；;！!？?]{0,6}(?:价格|价钱|金额|报价|售价|价)"
        r"|估\s*(?:一|个)*\s*个?价|按同档[^，。,.；;！!？?]{0,8}价"
        r"|(?:价格|售价|标价|定价|报价|到手价)(?:写成?|定为?|标为?|是|为)?\s*\d{3,6}\s*(?:元|块)?(?!\s*(?:以内|以下|左右|内))"
        r"|(?:写|标|定|卖)\s*(?:个|成)?\s*\d{3,6}\s*(?:元|块)(?!\s*(?:以内|以下|左右|内)))")),
    ("dynamic", re.compile(
        rf"(?:{_VERB}(?:个|上|一个|一下|入|进|出)?)?(?:(?:{_DYN_TERM}){_AMT_TAIL})+")),
    ("lowest_price", re.compile(
        r"全网最低(?:价)?|全国最低(?:价)?|史上最低(?:价)?|绝对最低(?:价)?|保证最低(?:价)?|价格最低|最低价|"
        r"永久保价|终身保价|保价(?:永久|终身)|最便宜|最划算|买到就是赚到|现在买一定最便宜|"
        r"全国(?:都|均)?有货|一定有货|保证有货")),
    ("fake_experience", re.compile(
        r"(?:编|杜撰|虚构|假装|伪造|模拟|瞎编)[^，。,.；;！!？?]{0,8}(?:体验|经历|感受|使用|评测|测评|心得|故事|用过)"
        r"|(?:我|本人|亲身|自己)\s*(?:亲测|实测|用过|用了|使用了|上手)[^，。,.；;！!？?]{0,10}"
        r"|(?:亲测|实测|亲身体验|亲身经历|真实体验)"
        r"|用了[一二两三四五六七八九十\d]+\s*(?:个)?\s*(?:天|周|星期|月|年)"
        r"|写[^，。,.；;！!？?]{0,4}(?:使用体验|上手体验|使用心得|上手感受|使用感受|用后感|测评|评测)")),
    ("competitor", re.compile(
        rf"比\s*(?:{_COMPETITORS})[^，。,.；;！!？?]{{0,6}}?(?:强|好|快|牛|厉害|香|优秀|领先|薄|轻|便宜|值)"
        rf"|(?:{_COMPETITORS})[^，。,.；;！!？?]{{0,6}}?(?:不如|不行|差|垃圾|弱|落后|被吊打)"
        rf"|(?:吊打|碾压|完爆|秒杀|踩|贬低|黑一下|diss|对标|PK|pk|对比|比较)[^，。,.；;！!？?]{{0,6}}(?:{_COMPETITORS})"
        rf"|(?:{_COMPETITORS})[^，。,.；;！!？?]{{0,4}}(?:对比|比较|PK|pk|VS|vs)"
        r"|贬低竞品|贬低友商|踩友商|吹爆[^，。,.；;！!？?]{0,4}碾压")),
    ("sales_award_review", re.compile(
        r"销量(?:第一|冠军|领先|top|TOP|\d+万)|销冠|(?:卖了?|热销|售出)\s*\d+\s*万|全网销量|口碑第一|好评率"
        r"|(?:荣获|获得|斩获|摘得)[^，。,.；;！!？?]{0,8}(?:奖|大奖|认证)|获奖|金奖|红点奖|红点|iF 奖|if 奖"
        r"|(?:用户|网友|客户|买家|顾客)[^，。,.；;！!？?]{0,3}(?:好评|评价|都说|夸|反馈|一致认可)|好评如潮|五星好评|晒单")),
    ("absolute", re.compile(
        r"(?:说|写成?|宣传|标榜|吹|强调|称|写它是|说它是)[^，。,.；;！!？?]{0,4}?"
        r"(?:行业第一|业界第一|市场第一|史上最[\u4e00-\u9fff]{1,4}|最强[\u4e00-\u9fff]{0,3}|最好[\u4e00-\u9fff]{0,3}"
        r"|唯一[\u4e00-\u9fff]{0,4}|第一[\u4e00-\u9fff]{0,3}|无敌|完美[\u4e00-\u9fff]{0,3}|零风险|100%[\u4e00-\u9fff]{0,4}"
        r"|百分百[\u4e00-\u9fff]{0,4}|终身[\u4e00-\u9fff]{0,4}|永久[\u4e00-\u9fff]{0,4}|绝对[\u4e00-\u9fff]{0,4})")),
    ("promise", re.compile(
        r"(?:保证|承诺)[^，。,.；;！!？?]{0,2}(?:买到|不卡|不坏|不会坏|不出问题|永不|不死机|不发热|无故障)"
        r"|终身免费|无条件退换|全国免费上门|永久免费|免费上门")),
]

BLOCK_REASONS = {
    "fabricated_price": "知识库没有这个金额，不估价、不编价。有公开金额的机型会写成带 SKU、口径、核验时间和官方链接的页面价；没有公开金额的只写“官方未公开当前金额”。",
    "dynamic": "国补、立减、赠品、分期、限时和库存都是动态信息，没有官方出处和核验时间，不写进稿件。需要时请提供渠道、地区、时间和适用 SKU，并以结算页为准。",
    "lowest_price": "“全网最低”“永久保价”“一定有货”没有证据支持，会改写成带核验时间的官方页面价，并说明库存和优惠以结算页为准。",
    "fake_experience": "没有经授权的真实使用记录，不虚构亲身体验。稿件改写成“如果你……”的场景设想，只陈述知识库里确认的事实。",
    "competitor": "没有固定日期、配置和任务的对比证据，不写“比某品牌强”，也不贬低竞品。稿件只写本机型已确认的事实。",
    "sales_award_review": "销量、获奖和用户好评没有可引用的官方出处，不写。",
    "absolute": "“第一、最强、唯一、零风险”等绝对化说法没有证据，会改成有依据的限定表述。",
    "promise": "“保证”“终身”“无条件”类承诺没有条件和政策原文，不写。服务以华为官方服务页面和检测结果为准。",
}


def classify_blocked(snippet: str) -> str:
    """Category of a recorded blocked request snippet ('' when unknown)."""
    s = nfkc(snippet)
    for cat, rx in BLOCK_PATTERNS:
        if rx.search(s):
            return cat
    return ""


def blocked_reason(snippet: str) -> str:
    cat = classify_blocked(snippet)
    return BLOCK_REASONS.get(cat, "这项要求没有知识库依据，或违反营销合规红线，不照写。")


def find_blocked_requests(text: str) -> list[str]:
    """User asks we must refuse or rewrite. Returns verbatim snippets."""
    t = nfkc(text or "")
    found: list[tuple[int, str]] = []
    for cat, rx in BLOCK_PATTERNS:
        for m in rx.finditer(t):
            snippet = m.group(0).strip()
            if not snippet or len(snippet) < 2:
                continue
            before = t[max(0, m.start() - 10):m.start()]
            clause_start = max(before.rfind(c) for c in "，,。.；;！!？?\n")
            if clause_start >= 0:
                before = before[clause_start + 1:]
            if _NEG_BEFORE.search(before):
                continue
            # a dynamic term that is only a part of "以旧换新" scenario text is fine
            if cat == "dynamic" and re.fullmatch(r"(?:优惠|折扣|打折|特价|限量|现货|库存)", snippet):
                # bare generic words are only blocked when the user asks to write them
                if not re.search(_VERB, before[-4:] or ""):
                    continue
            found.append((m.start(), snippet))
    found.sort()
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    for pos, sn in found:
        end = pos + len(sn)
        if any(pos >= a and end <= b for a, b in spans):
            continue
        spans.append((pos, end))
        out.append(sn)
    return dedupe(out)


# --------------------------------------------------------------------------
# Model matching
# --------------------------------------------------------------------------
_YEAR_RE = re.compile(r"20\d{2}\s*款?")


def _norm_model_text(s: str) -> str:
    return squash(_YEAR_RE.sub(" ", nfkc(s)))


def _model_keys(m: ProductModel) -> tuple[set[str], set[str], set[str]]:
    """(exact, loose, official) normalised keys of a model."""
    exact: set[str] = set()
    loose: set[str] = set()
    official: set[str] = set()

    def add(bucket: set[str], s: str, minlen: int = 2) -> str:
        k = _norm_model_text(s)
        if len(k) >= minlen:
            bucket.add(k)
        return k

    for idx, n in enumerate([m.name, m.short_name, *m.aliases]):
        if not n:
            continue
        k = add(exact, n)
        n2 = re.sub(r"(?i)huawei|华为", "", n)
        k2 = add(exact, n2)
        if idx < 2:
            official.update({k, k2})
        n3 = re.sub(r"[（(][^）)]*[）)]", "", n2)
        k3 = _norm_model_text(n3)
        if k3 != k2:
            add(loose, n3)
        n4 = re.sub(r"(?i)matebook", "", n2)
        k4 = _norm_model_text(n4)
        if len(k4) >= 3 and k4 != k2:
            if re.search(r"\d", k4) and re.search(r"[a-z\u4e00-\u9fff]", k4):
                add(exact, n4, 3)
            else:
                add(loose, n4, 3)
    if m.series:
        add(loose, m.series)
    loose -= exact
    return exact, loose, official


class _KeyIndex:
    def __init__(self, models: list[ProductModel]):
        self.models = {m.model_id: m for m in models}
        self.exact: dict[str, set[str]] = {}
        self.loose: dict[str, set[str]] = {}
        self.official: dict[str, set[str]] = {}
        self.series: dict[str, set[str]] = {}
        for m in models:
            ex, lo, off = _model_keys(m)
            for k in ex:
                self.exact.setdefault(k, set()).add(m.model_id)
            for k in lo:
                self.loose.setdefault(k, set()).add(m.model_id)
            for k in off:
                self.official.setdefault(k, set()).add(m.model_id)
            if m.series:
                self.series.setdefault(_norm_model_text(m.series), set()).add(m.model_id)
        self.keys = sorted(set(self.exact) | set(self.loose), key=lambda k: (-len(k), k))


def _boundary_ok(t: str, start: int, end: int, key: str) -> bool:
    if end < len(t) and re.match(r"[a-z0-9]", key[-1]) and re.match(r"[a-z0-9]", t[end]):
        return False
    if start > 0 and re.match(r"[a-z0-9]", key[0]) and re.match(r"[a-z0-9]", t[start - 1]):
        if not key.startswith(("matebook", "huawei")):
            return False
    return True


_OS_WIN_RE = re.compile(r"酷睿|intel|英特尔|ultra|windows|win11|win10|微软系统", re.I)
_OS_HM_RE = re.compile(r"鸿蒙|harmonyos|麒麟|纯血|\bhm\b", re.I)


def _match_models(text: str, models: list[ProductModel]) -> tuple[list[str], list[list[str]], list[str]]:
    """Return (resolved model ids in text order, ambiguous groups, notes)."""
    idx = _KeyIndex(models)
    t = _norm_model_text(text)
    taken: list[tuple[int, int, str]] = []
    for key in idx.keys:
        pos = 0
        while True:
            i = t.find(key, pos)
            if i < 0:
                break
            j = i + len(key)
            pos = i + 1
            if not _boundary_ok(t, i, j, key):
                continue
            if any(i < b and j > a for a, b, _ in taken):
                continue
            taken.append((i, j, key))
    taken.sort()
    resolved: list[str] = []
    ambiguous: list[list[str]] = []
    notes: list[str] = []
    for (i, j, key) in taken:
        ex = sorted(idx.exact.get(key, set()))
        lo = sorted(idx.loose.get(key, set()))
        chosen: list[str] = []
        if len(ex) == 1:
            mid = ex[0]
            shared_series = key in idx.series and len(idx.series[key]) > 1
            is_official = mid in idx.official.get(key, set())
            if shared_series and not is_official:
                chosen = []
                group = sorted(set(ex) | set(lo) | idx.series[key])
            else:
                chosen = [mid]
        elif len(ex) >= 2:
            group = sorted(set(ex) | set(lo))
        elif len(lo) == 1:
            chosen = lo
        else:
            group = lo
        if chosen:
            if chosen[0] not in resolved:
                resolved.append(chosen[0])
            continue
        # try the system hint ("MateBook 14 酷睿" / "MateBook 14 鸿蒙")
        rest = t[j:j + 12] + t[max(0, i - 6):i]
        picked = None
        if _OS_WIN_RE.search(rest) and not _OS_HM_RE.search(rest):
            c = [g for g in group if idx.models[g].os_family == "windows"]
            picked = c[0] if len(c) == 1 else None
        elif _OS_HM_RE.search(rest) and not _OS_WIN_RE.search(rest):
            c = [g for g in group if idx.models[g].os_family == "harmonyos"]
            picked = c[0] if len(c) == 1 else None
        if picked:
            if picked not in resolved:
                resolved.append(picked)
            notes.append(f"「{idx.models[picked].series}」有多个同名机型，已按你写的系统倾向选择「{idx.models[picked].short_name}」。")
        else:
            ambiguous.append(group)
    return resolved, ambiguous, notes


def _spec_snips(kb: KnowledgeBase, m: ProductModel, limit: int = 2) -> list[str]:
    try:
        facts = kb.facts(m.model_id, kinds=["spec"])
    except Exception:  # noqa: BLE001 - hint building must never break parsing
        return []
    out: list[str] = []
    for prefix in ("屏幕尺寸", "处理器", "重量"):
        for f in facts:
            if f.text.startswith(prefix):
                out.append(f.text.strip())
                break
        if len(out) >= limit:
            break
    return out


def _model_option(kb: KnowledgeBase, m: ProductModel, peers: list[ProductModel]) -> ClarifyOption:
    parts = [m.os_label]
    parts.extend(_spec_snips(kb, m))
    for p in peers:
        if p.model_id != m.model_id:
            parts.append(f"易与「{p.short_name}」混淆")
    return ClarifyOption(value=m.model_id, label=m.short_name or m.name, hint="｜".join(p for p in parts if p))


def _weight_grams(kb: KnowledgeBase, m: ProductModel) -> Optional[float]:
    try:
        facts = kb.facts(m.model_id, categories=["portable"])
    except Exception:  # noqa: BLE001
        return None
    best: Optional[float] = None
    for f in facts:
        if "重量" not in f.text:
            continue
        for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(kg|g|千克|克)", nfkc(f.text), flags=re.I):
            v = float(num) * (1000 if unit.lower() in ("kg", "千克") else 1)
            best = v if best is None else min(best, v)
    return best


# --------------------------------------------------------------------------
# Platform / scenario / other fields
# --------------------------------------------------------------------------
def detect_platform(text: str) -> tuple[Optional[str], list[str]]:
    t = nfkc(text or "").lower()
    hits: list[tuple[int, str]] = []
    for pid, words in _PLATFORM_WORDS.items():
        for w in words:
            for m in re.finditer(re.escape(w.lower()), t):
                hits.append((m.start(), pid))
    if not hits:
        return None, []
    hits.sort()
    first = hits[0][1]
    others = dedupe([p for _, p in hits if p != first])
    return first, others


def detect_scenario(text: str) -> tuple[Optional[str], str, list[str]]:
    """(scenario, tier, other scenarios). tier is 'explicit' | 'audience' | 'store' | ''."""
    t = nfkc(text or "")
    t = _STORE_PLATFORM_RE.sub(" ", t)
    tl = t.lower()
    explicit: list[tuple[int, str]] = []
    audience: list[tuple[int, str]] = []
    for sid, (ew, aw) in _SCENARIO_WORDS.items():
        for w in ew:
            for m in re.finditer(re.escape(w.lower()), tl):
                explicit.append((m.start(), sid))
        for w in aw:
            for m in re.finditer(re.escape(w.lower()), tl):
                audience.append((m.start(), sid))
    for m in _IT_RE.finditer(t):
        (explicit if re.search(r"采购|批量|企业", t) else audience).append((m.start(), "enterprise_procurement"))
    # "以旧换新" with a subsidy word is a dynamic claim, not the 家庭换新 scenario
    explicit = [(p, s) for p, s in explicit
                if not (s == "home_upgrade" and re.search(r"以旧换新", t) and re.search(r"补贴|国补|立减", t)
                        and not re.search(r"家庭换新|家用|父母|爸妈|长辈", t))]
    if explicit:
        explicit.sort()
        first = explicit[0][1]
        return first, "explicit", dedupe([s for _, s in explicit if s != first])
    if audience:
        audience.sort()
        first = audience[0][1]
        return first, "audience", dedupe([s for _, s in audience if s != first])
    if "门店" in nfkc(text or ""):
        return "store_visit", "store", []
    return None, "", []


def extract_audience(text: str) -> str:
    t = nfkc(text or "")
    for rx in _AUDIENCE_RES:
        m = rx.search(t)
        if m:
            return m.group(1).strip("，。,. ")
    for w in _AUDIENCE_WORDS:
        if w in t:
            return w
    return ""


def extract_selling_point(text: str) -> str:
    t = nfkc(text or "")
    for cue in re.finditer(_SELLING_CUE, t):
        window = t[cue.end():cue.end() + 14]
        window = re.split(r"[，。,.；;！!？?\n]", window)[0]
        for name, rx in _SELLING_MAP:
            if re.search(rx, window):
                return name
    return ""


_PRICE_WORDS = re.compile(r"价格|多少钱|售价|报价|定价|标价|几千|起售|起价|到手价|页面价|价位|什么价|[0-9]+\s*(?:元|块)")
_NO_PRICE = re.compile(r"(?:不要|别|不写|不用|删掉|去掉|不带|无需|不提|不放|删除|拿掉|不涉及)[^，。,.；;！!？?]{0,4}(?:价格|价|金额|报价|售价)")


def _want_price(text: str, cleaned_text: str) -> bool:
    t = nfkc(text or "")
    if _NO_PRICE.search(t):
        return False
    return bool(_PRICE_WORDS.search(cleaned_text))


def _length_hint(text: str) -> str:
    t = nfkc(text or "")
    if re.search(r"短一点|简短|精简|简洁|短文|写短|少写|别太长|不要太长|一百字|200\s*字以内|150\s*字|100\s*字", t):
        return "短"
    if re.search(r"写长|长文|详细|深度|展开|篇幅长|长一点|丰富", t):
        return "长"
    return ""


_EXTRA_CUE = re.compile(r"语气|风格|口吻|调性|字数|不要|别|避免|必须|务必|多用|少用|加上|带上|配图|标签|话题|表情|emoji|口语|正式|活泼")


def _extras(text: str, blocked: list[str]) -> list[str]:
    out: list[str] = []
    for clause in re.split(r"[，,。；;\n]", nfkc(text or "")):
        c = clause.strip()
        if len(c) < 3 or not _EXTRA_CUE.search(c):
            continue
        if any(b and b in c for b in blocked):
            continue
        if _NO_PRICE.search(c) or re.search(r"短一点|简短|精简", c):
            # price/length already have dedicated fields, but keep for traceability
            pass
        out.append(c)
    return dedupe(out)[:5]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _clar_platform() -> Clarification:
    return Clarification(
        field="platform",
        question="这篇稿子发在哪个渠道？",
        reason="不同渠道的结构、语气、配图数量和行动引导都不一样，需要先确定渠道。",
        options=[ClarifyOption(value=k, label=PLATFORM_LABELS[k], hint=PLATFORM_HINTS[k]) for k in PLATFORM_LABELS],
    )


def _clar_scenario() -> Clarification:
    return Clarification(
        field="scenario",
        question="面向哪种场景来写？",
        reason="场景决定切入点、卖点顺序和配图方向。",
        options=[ClarifyOption(value=k, label=SCENARIO_LABELS[k], hint=SCENARIO_HINTS[k]) for k in SCENARIO_LABELS],
    )


def _clar_model_all(kb: KnowledgeBase, models: list[ProductModel], question: str, reason: str) -> Clarification:
    return Clarification(
        field="model",
        question=question,
        reason=reason,
        options=[_model_option(kb, m, [p for p in models if p.model_id in m.confusable_with]) for m in models],
    )


def parse_task(req: RunRequest, kb: KnowledgeBase) -> tuple[TaskSpec, list[Clarification]]:
    raw = (req.text or "").strip()
    text = nfkc(raw)
    models = list(kb.models())
    by_id = {m.model_id: m for m in models}

    blocked = find_blocked_requests(raw)
    notes: list[str] = []
    clars: list[Clarification] = []

    # text without blocked fragments, so "写国补" cannot create a scenario/price
    cleaned = text
    for b in sorted(blocked, key=len, reverse=True):
        cleaned = cleaned.replace(nfkc(b), " ")

    # ---- models -------------------------------------------------------
    model_ids: list[str] = []
    ambiguous: list[list[str]] = []
    if req.model_ids:
        for mid in req.model_ids:
            if mid in by_id and mid not in model_ids:
                model_ids.append(mid)
            elif mid not in by_id:
                notes.append(f"请求里的机型编号「{mid}」不在知识库中，已忽略。")
    if not model_ids:
        model_ids, ambiguous, os_notes = _match_models(cleaned, models)
        notes.extend(os_notes)
        if not model_ids and not ambiguous:
            try:
                hits = kb.find_models(cleaned)
            except Exception:  # noqa: BLE001
                hits = []
            hits = [h for h in hits if h[1] >= 0.5 and (not h[2] or _norm_model_text(h[2]) in _norm_model_text(cleaned))]
            if hits:
                top = hits[0][1]
                group = [h[0].model_id for h in hits if abs(h[1] - top) < 1e-6]
                if len(group) == 1:
                    model_ids = group
                else:
                    ambiguous = [group]

    category_only = False
    if not model_ids and not ambiguous:
        category_only = bool(_CATEGORY_RE.search(cleaned))

    # ---- platform / scenario -----------------------------------------
    platform = req.platform
    if platform is None:
        platform, other_p = detect_platform(cleaned)
        if platform and other_p:
            labels = "、".join(PLATFORM_LABELS[p] for p in other_p)
            notes.append(f"同时提到了{labels}，一次只生成一个渠道，先按「{PLATFORM_LABELS[platform]}」处理，其余可以之后换渠道改稿。")
    scenario = req.scenario
    if scenario is None:
        scenario, tier, other_s = detect_scenario(cleaned)
        if scenario and tier == "audience":
            notes.append(f"没有写明场景，按受众线索推断为「{SCENARIO_LABELS[scenario]}」。")
        elif scenario and tier == "store":
            notes.append("文字里提到了门店，已推断为「门店到访」场景。")
        if scenario and other_s:
            labels = "、".join(SCENARIO_LABELS[s] for s in other_s)
            notes.append(f"同时提到了{labels}，先按「{SCENARIO_LABELS[scenario]}」设计切入点。")

    audience = (req.audience or "").strip() or extract_audience(cleaned)
    selling_point = (req.selling_point or "").strip() or extract_selling_point(cleaned)
    want_price = bool(req.want_price) or _want_price(text, cleaned)
    length_hint = _length_hint(text)

    # ---- notes on look-alike models ----------------------------------
    for mid in model_ids:
        m = by_id[mid]
        peers = [by_id[p] for p in m.confusable_with if p in by_id]
        if peers:
            lst = "、".join(f"「{p.short_name}」（{p.os_label}）" for p in peers)
            notes.append(f"已按字面选择「{m.short_name}」（{m.os_label}）。相近型号 {lst} 是另一款，稿件不会混用它们的参数和图片。")

    # ---- clarifications ------------------------------------------------
    missing: list[str] = []
    if len(model_ids) > 1:
        picked = [by_id[i] for i in model_ids]
        clars.append(Clarification(
            field="model",
            question="软文建议只聚焦一款机型。这次写哪一款？",
            reason="多款机型放在同一篇稿子里，参数和图片容易混用；对比类内容需要同日期、同配置的证据，知识库只能逐款核对。",
            options=[_model_option(kb, m, [p for p in picked if p.model_id != m.model_id]) for m in picked],
        ))
        missing.append("model")
    elif ambiguous:
        group_ids = dedupe([g for grp in ambiguous for g in grp] + model_ids)
        cand = [by_id[g] for g in group_ids if g in by_id and g not in model_ids]
        if cand:
            clars.append(Clarification(
                field="model",
                question="这个名称对应不止一款机型，你指的是哪一款？",
                reason="名称相近的机型系统、处理器和屏幕不同，不能自动替你选。",
                options=[_model_option(kb, m, cand) for m in cand],
            ))
            missing.append("model")
    elif not model_ids:
        missing.append("model")
        if category_only:
            thin = bool(_THIN_RE.search(cleaned))
            ranked = list(models)
            if thin:
                weights = {m.model_id: _weight_grams(kb, m) for m in models}
                ranked.sort(key=lambda m: (weights[m.model_id] is None, weights[m.model_id] or 0))
            top = ranked[:4]
            clars.append(Clarification(
                field="other",
                question="先确认一下最看重什么？",
                reason="只说“轻薄本”还不够选型，用途不同，推荐的机型也不同。",
                options=[
                    ClarifyOption(value="portable", label="便携出差", hint="重量、厚度、续航"),
                    ClarifyOption(value="display", label="屏幕与创作", hint="屏幕尺寸、分辨率、色彩"),
                    ClarifyOption(value="office", label="办公学习", hint="性能、接口、多设备协同"),
                    ClarifyOption(value="ports", label="外接扩展", hint="接口与外接显示"),
                ],
                allow_free_text=True,
            ))
            clars.append(Clarification(
                field="model",
                question="可以先从这几款里选一款来写：",
                reason="软文需要对应到一款具体机型，事实和图片才能核对。",
                options=[_model_option(kb, m, [p for p in models if p.model_id in m.confusable_with]) for m in top],
            ))
        else:
            clars.append(_clar_model_all(
                kb, models, "这篇软文写哪一款机型？",
                "需要先确定具体机型，参数、卖点和图片才能从知识库里对应取用。"))
    if not platform:
        missing.append("platform")
        clars.append(_clar_platform())
    if not scenario:
        missing.append("scenario")
        clars.append(_clar_scenario())

    task = TaskSpec(
        raw=raw,
        model_ids=model_ids,
        platform=platform,
        scenario=scenario,
        audience=audience,
        selling_point=selling_point,
        length_hint=length_hint,
        want_price=want_price,
        extras=_extras(cleaned, blocked),
        missing=missing,
        blocked_requests=blocked,
        confusion_notes=dedupe(notes),
    )
    return task, clars
