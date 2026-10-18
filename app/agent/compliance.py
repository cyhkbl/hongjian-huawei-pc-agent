"""Compliance rule engine.

check_compliance(article, task, strategy) -> (revised Article, [ComplianceIssue])

Every rule has an id, a Chinese name, a severity, a detector and a default
rewrite strategy:

- "sub":  replace the hit (e.g. drop the "最" of "最轻薄"), action="rewritten"
- "drop": remove the clause that contains the hit (or the whole sentence when
          nothing meaningful is left), action="removed"
- "blocked": text cannot be repaired safely (title with nothing left, price
          block without a valid price_note). The text stays, the issue is
          reported with ``where`` = block id so the pipeline can delete it.

Specification limits ("最大 4K@60Hz", "最高 32GB", "最长 12 小时") are not
treated as absolute wording: the superlative must not be followed by a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.agent.rules_common import (
    AMOUNT_RE, dedupe, nfkc, segments, split_sentences,
)
from app.agent.understand import BLOCK_PATTERNS, blocked_reason, classify_blocked
from app.models import Article, Block, ComplianceIssue, Strategy, TaskSpec

DISCLAIMER_SETTLE = "价格、库存与优惠以华为官方商城结算页为准。"
SAFE_CTA = "想了解更多，请查看华为官方渠道的产品页面。"

# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------
_CLAUSE_SEPS = "，,；;、"
_OPEN = "（(【「『《"
_CLOSE = "）)】」』》"
_NEG_PRE = re.compile(r"(?:不|无|没|未|非|别|勿|莫|无法|并非|不是|不会|不能|不要|不得|不作|不做|难以|无从|不必|杜绝|严禁|禁止|避免)\s*$")
_HYPO_PRE = re.compile(r"(?:如果|假如|假设|设想|想象|要是|若是|倘若|比如|例如|就像|像是)[^，。；！？\n]{0,4}$")
_SAFE_CTX = re.compile(
    r"以[^，。；]{0,16}为准|请以|须以|需以|核验|复核|咨询|询问|如实告知|未公开|没有公开|不承诺|不保证|无法保证|不能保证|"
    r"不作保证|不写|不涉及|不含|不提供|不代表|并非|不等于|不构成|仅供参考|因[^，。；]{0,8}而异|取决于|受[^，。；]{0,10}影响|不制造")


def _alnum_len(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", s))


_segments = segments


_LEAD_CONJ = re.compile(r"^(?:并且|而且|并|且|也|还|又|同时|另外)")


def drop_clause(sent: str, pos: int) -> str:
    """Remove the clause containing character offset ``pos``. '' when nothing meaningful remains."""
    segs = _segments(sent)
    if len(segs) <= 1:
        return ""
    off = 0
    idx = 0
    for i, s in enumerate(segs):
        if off <= pos < off + len(s):
            idx = i
            break
        off += len(s)
    removed = segs[idx]
    rest = segs[:idx] + segs[idx + 1:]
    if idx == len(segs) - 1 and rest:
        tail = re.search(r"[。！？!?…]+[”’」』）)]*$", removed)
        prev = rest[-1]
        if prev and prev[-1] in _CLAUSE_SEPS:
            rest[-1] = prev[:-1] + (tail.group(0) if tail else "")
    out = "".join(rest)
    out = _LEAD_CONJ.sub("", out, count=1) if idx == 0 else out
    if _alnum_len(re.sub(r"[（(][^）)]*[）)]", "", out)) < 4:
        return ""
    if not re.search(r"[。！？!?…”’」』）)]$", out) and re.search(r"[。！？!?]$", sent):
        out = out.rstrip(_CLAUSE_SEPS) + sent[-1]
    return out


@dataclass
class Ctx:
    platform: str = ""
    task: Optional[TaskSpec] = None
    strategy: Optional[Strategy] = None
    price_note: str = ""
    price_amounts: set = field(default_factory=set)
    price_note_problems: list = field(default_factory=list)
    price_has_amount_lines: bool = False
    price_start_only: bool = False          # every amount line is a 官网参考起价
    price_text_squash: str = ""
    kind: str = ""
    note: str = ""

    @property
    def in_price_block(self) -> bool:
        return self.note.startswith("price:")

    @property
    def price_none_block(self) -> bool:
        return self.note.strip() == "price:none"


# --------------------------------------------------------------------------
# Price note parsing
# --------------------------------------------------------------------------
_KEY_ALIASES = {
    "口径": ("口径", "价格类型", "类型"),
    "SKU": ("SKU", "sku", "款式", "配置", "规格"),
    "金额": ("金额", "价格", "页面金额"),
    "核验时间": ("核验时间", "核验日期", "时间", "日期"),
    "条件": ("条件", "条件摘要"),
    "官方链接": ("官方链接", "链接", "URL", "url", "来源", "官方URL"),
    "机型": ("机型", "型号"),
    "状态": ("状态",),
    "说明": ("说明", "备注"),
}
_DATE_RE = re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}")


def _amount_value(a: str) -> Optional[float]:
    s = nfkc(a)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group(0).replace(",", ""))
    if "万" in s:
        v *= 10000
    return round(v, 2)


def parse_price_note(note: str) -> tuple[set, list[str], bool, bool]:
    """(valid amounts, problems, has_amount_lines, start_only)."""
    amounts: set = set()
    problems: list[str] = []
    has_amount = False
    start_only = True
    for raw in (note or "").splitlines():
        line = raw.strip().lstrip("-•· ").strip()
        if not line:
            continue
        kv: dict[str, str] = {}
        for part in re.split(r"[；;]", nfkc(line)):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            for canon, names in _KEY_ALIASES.items():
                if k in names:
                    kv[canon] = v
                    break
        amt_text = kv.get("金额", "")
        has_digit = bool(re.search(r"\d", amt_text))
        if has_digit:
            has_amount = True
            missing = [k for k in ("口径", "SKU", "金额", "核验时间", "官方链接") if not kv.get(k)]
            if kv.get("核验时间") and not _DATE_RE.search(kv["核验时间"]):
                missing.append("核验时间（日期格式）")
            if kv.get("官方链接") and not re.search(r"https?://", kv["官方链接"]):
                missing.append("官方链接（网址）")
            if missing:
                problems.append(f"价格说明缺少：{'、'.join(missing)}")
                continue
            if "起" not in kv.get("口径", ""):
                start_only = False
            v = _amount_value(amt_text)
            if v is not None:
                amounts.add(v)
        else:
            miss = [k for k in ("口径", "核验时间", "官方链接") if not kv.get(k)]
            if miss:
                problems.append(f"未公开金额的说明缺少：{'、'.join(miss)}")
    return amounts, problems, has_amount, start_only and has_amount


# --------------------------------------------------------------------------
# Rule model
# --------------------------------------------------------------------------
@dataclass
class Hit:
    start: int
    end: int
    repl: Optional[str] = None         # None => drop clause
    severity: Optional[str] = None
    note: str = ""


@dataclass
class Rule:
    id: str
    label: str
    severity: str
    suggestion: str
    strategy: str                      # human readable default strategy
    find: Callable[[str, Ctx], list]
    skip_in_limit: bool = True
    check_negation: bool = True
    check_safe_ctx: bool = False


def _rx(pattern: str, flags: int = re.I) -> re.Pattern:
    return re.compile(pattern, flags)


def _simple(rx: re.Pattern, repl: Optional[str] = None,
            guard: Optional[Callable[[str, re.Match, Ctx], bool]] = None,
            severity: Optional[str] = None) -> Callable[[str, Ctx], list]:
    def f(s: str, ctx: Ctx) -> list:
        out = []
        for m in rx.finditer(s):
            if guard and not guard(s, m, ctx):
                continue
            out.append(Hit(m.start(), m.end(), repl, severity))
        return out
    return f


def _join(*fs: Callable[[str, Ctx], list]) -> Callable[[str, Ctx], list]:
    def f(s: str, ctx: Ctx) -> list:
        out: list = []
        for fn in fs:
            out.extend(fn(s, ctx))
        return out
    return f


# ---- 1. absolute wording ---------------------------------------------------
_SUP_SPEC_ADJ = "大|小|高|低|长|宽|厚|薄|多|少|快|亮|轻"
_SUP_DROP_ADJ = "强大|强劲|强悍|强|好|佳|优秀|优|棒|牛|顶级|顶|先进|出色|可靠|安全|专业|完美|领先|懂你"
_SUP_KEEP_ADJ = "轻薄|便携|好用|实用|划算|值得|适合|推荐|清晰|流畅|耐用|省电|稳定|稳|静音|静|美|高端|新颖|受欢迎|热门"
_SUP_RX = re.compile(
    rf"最(?=(?:{_SUP_DROP_ADJ}|{_SUP_KEEP_ADJ}|{_SUP_SPEC_ADJ}))(?P<adj>{_SUP_DROP_ADJ}|{_SUP_KEEP_ADJ}|{_SUP_SPEC_ADJ})")
_SPEC_NUM_AFTER = re.compile(r"^[^，。；！？\n（(]{0,12}?\d")
_SPEC_LEAD_NOUN = re.compile(r"^(?:亮度|分辨率|刷新率|容量|支持|可达|可至|对外供电|供电|功率|输出|输入|传输|续航|播放|"
                             r"充电|读取|写入|速率|带宽|扩展|可选|可扩展|可升级|可连接|外接|同时)")


def _find_superlative(s: str, ctx: Ctx) -> list:
    out = []
    for m in _SUP_RX.finditer(s):
        adj = m.group("adj")
        after = s[m.end():]
        if adj in _SUP_SPEC_ADJ.split("|"):
            # spec ceiling/floor: "最大 4K@60Hz" "最高 32GB" "最多支持 10 点触控"
            if _SPEC_NUM_AFTER.match(after):
                continue
            if _SPEC_LEAD_NOUN.match(after) and re.search(r"\d", after[:16]):
                continue
        if adj in _SUP_DROP_ADJ.split("|") or adj in _SUP_SPEC_ADJ.split("|"):
            # "最大的优点"/"最薄" without a number is a marketing superlative; stripping "最" would leave a broken sentence
            out.append(Hit(m.start(), m.end(), None, "block"))
        else:
            out.append(Hit(m.start(), m.start() + 1, "", "warn"))
    return out


_FIRST_RX = re.compile(r"第一(?!代|次|步|天|周|眼|印象|节|章|个字|时间|学期|堂|课|年|批|感觉|反应|站|页|关|轮|季度|眼)")
_ABS_DROP_RX = re.compile(
    r"性价比(?:最高|之王|第一|天花板|无敌)|唯一|独一无二|独一份|无与伦比|无可替代|无可比拟|无出其右|绝无仅有|前所未有|史无前例|空前|万能|无所不能|无敌|"
    r"零风险|零故障|零延迟|零卡顿|百分百|绝对|永久|终身|永远|永不|一劳永逸|国家级|世界级|全球领先|业界领先|行业领先|"
    r"全面领先|遥遥领先|全球首发|全网首发|行业首发|业界首发|"
    r"(?:全球|全网|业界|行业|国内|同级|同类|行业内)?首(?:款|创|个|台)|行业标杆|业界标杆|天花板|巅峰之作|"
    r"(?:\d+|N)\s*倍(?:于|于同级)")
_ABS_MOD_RX = re.compile(r"完美|极致|顶级|顶尖|绝佳|一流|巅峰|全能|王者|极品|至尊|终极")
_HUNDRED_RX = re.compile(r"(?:(?<!\d)100|一百)\s*(?:%|％|百分)")
_HUNDRED_SPEC = re.compile(r"^\s*(?:的)?\s*(?:s?RGB|P3|DCI|NTSC|Adobe|色域|覆盖|屏占比|DisplayP3|Display P3)", re.I)
_HUNDRED_SPEC_PRE = re.compile(r"(?:s?RGB|P3|DCI|NTSC|Adobe|色域|覆盖|覆盖率|屏占比)\s*$", re.I)


def _find_hundred(s: str, ctx: Ctx) -> list:
    out = []
    for m in _HUNDRED_RX.finditer(s):
        if _HUNDRED_SPEC.match(s[m.end():m.end() + 14]) or _HUNDRED_SPEC_PRE.search(s[max(0, m.start() - 10):m.start()]):
            continue
        out.append(Hit(m.start(), m.end(), None, "block"))
    return out


R_ABSOLUTE = Rule(
    "absolute_wording", "绝对化用语", "block",
    "去掉绝对化用语，改成有依据的具体表述，例如直接写参数。",
    "“最+形容词”去掉“最”并记录；第一、唯一、永久、100% 等无法限定的说法删除所在分句。规格上限描述（最大、最高后接数字）不处理。",
    _join(_find_superlative,
          _simple(_FIRST_RX, None, severity="block"),
          _simple(_ABS_DROP_RX, None, severity="block"),
          _simple(_ABS_MOD_RX, "", severity="warn"),
          _find_hundred))

# ---- 2. false promise ------------------------------------------------------
_PROMISE_RX = re.compile(
    r"保证(?!金|书|单|期)|承诺(?!书)|无条件|全国(?:免费|包邮|联保|通用|上门|均可|都可|都能|都有|各地)|"
    r"免费(?:上门|换新|维修|送货|升级|更换)|包退包换|(?:7|七)\s*天无理由|全额退款|不满意(?:就)?退|"
    r"无忧|零担心|不用担心|不必担心|"
    r"(?:不会|永不|绝不|从不|一点都不|毫不)卡顿?|用(?:很多|好多|多)年(?:也)?不(?:会)?卡|"
    r"效率(?:翻倍|倍增)|效率提升\s*\d+\s*(?:%|倍)|翻倍")
_CERTAIN_RX = re.compile(r"(?:一定|必定|肯定|必然)(?=[能会可有])")

R_PROMISE = Rule(
    "false_promise", "虚假承诺", "block",
    "不作保证类承诺。服务、退换和维修以华为官方政策与检测结果为准。",
    "“保证、承诺、无条件、免费上门”等分句删除；“一定能/肯定会”改为“可能”。",
    _join(_simple(_PROMISE_RX, None, severity="block"),
          _simple(_CERTAIN_RX, "可能", severity="warn")),
    check_safe_ctx=True)

# ---- 3. price misleading (non-amount wording) -------------------------------
_PRICE_WORD_RX = re.compile(
    r"全网最低(?:价)?|全国最低|史上最低|史低|最低价|绝对低价|地板价|骨折价|白菜价|跳楼价|超低价|低价(?:入手|购)|"
    r"价格(?:最低|最优惠|最划算)|最便宜|最划算|最优惠|最实惠|永久保价|终身保价|保价|价保|买贵|买到就是赚到|不买亏|"
    r"现在买一定|错过(?:再)?等一年|不会再有这个价|性价比之王|低至\s*\d*|仅需|只需|仅售|一口价|内部价|员工价|"
    r"团购价|渠道价|学生价|教育价|专属价|特惠价|活动价|秒杀价|直播间价|白菜|跳水价")
_ALL_CONFIG_RX = re.compile(r"全系|所有配置|全系列|各配置|任意配置|所有款式|全部配置|所有版本")


def _find_amounts(s: str, ctx: Ctx) -> list:
    out = []
    for m in AMOUNT_RE.finditer(nfkc(s)):
        # offsets are identical for NFKC output of CJK/ASCII text; guard for length change
        if len(nfkc(s)) != len(s):
            break
        val = _amount_value(m.group(0))
        if ctx.price_none_block:
            out.append(Hit(m.start(), m.end(), None, "block", "该机型没有公开金额，不写金额。"))
            continue
        if not ctx.price_amounts:
            out.append(Hit(m.start(), m.end(), None, "block", "没有符合要求的价格说明（SKU、口径、核验时间、条件、官方链接），金额不写。"))
            continue
        if val not in ctx.price_amounts:
            out.append(Hit(m.start(), m.end(), None, "block", "这个金额不在价格说明里，不能写。"))
            continue
        if _ALL_CONFIG_RX.search(s):
            out.append(Hit(m.start(), m.end(), None, "block", "单个 SKU 的金额不能当作全系或所有配置的价格。"))
            continue
        if re.match(r"\s*起", s[m.end():m.end() + 2]) and not ctx.price_start_only:
            pos = m.end() + len(s[m.end():m.end() + 2]) - len(s[m.end():m.end() + 2].lstrip())
            out.append(Hit(pos, pos + 1, "", "warn", "页面价不是“起”价，已去掉“起”字。"))
        elif m.group(0).endswith("起") and not ctx.price_start_only:
            out.append(Hit(m.end() - 1, m.end(), "", "warn", "页面价不是“起”价，已去掉“起”字。"))
        if "到手" in s and not re.search(r"预估到手", s):
            out.append(Hit(m.start(), m.end(), None, "block", "“到手价”没有标明预估口径和条件。"))
    return out


R_PRICE = Rule(
    "price_misleading", "价格误导", "block",
    "金额只能以“SKU、口径、核验时间、条件、官方链接”整体出现，并提示以结算页为准。",
    "没有价格说明或与说明不一致的金额、“全网最低”“永久保价”等说法删除所在分句；页面价后多写的“起”去掉。",
    _join(_simple(_PRICE_WORD_RX, None, severity="block"), _find_amounts),
    skip_in_limit=False)

# ---- 4. unsupported comparison ---------------------------------------------
_CMP_RX = re.compile(
    r"碾压|吊打|完胜|完爆|秒杀(?!价)|甩开|甩[^，。；！？]{0,3}几条街|远超|远胜|大幅(?:领先|超越)|全面(?:领先|超越)|遥遥领先|"
    r"领先(?:同级|同类|同档|同行|行业|市场|对手|竞品|友商|其他|一代)|超越(?:同级|同类|同行|对手|竞品|友商|其他|上一代)|"
    r"优于|强于|胜过|胜于|好过|快过|轻过|薄过|不输|同级别?最|同档最|同类最|同价位最|无出其右|碾轧|"
    r"(?<![性价对相攀类无])比(?![较如例特赛分值率心方喻重])[^，。；！？\n]{1,8}?(?:更|还|要|得)?(?:强|好|快|薄|轻|大|高|亮|稳|省电|划算|便宜|厉害|耐用|流畅|清晰)")
R_COMPARE = Rule(
    "unsupported_comparison", "无依据对比", "block",
    "对比需要固定日期、配置和任务的证据，知识库里没有就不写。只写本机型已确认的事实。",
    "删除含对比的分句。",
    _simple(_CMP_RX, None, severity="block"),
    skip_in_limit=False)

# ---- 5. competitor disparagement -------------------------------------------
_COMP = (r"苹果|Apple|MacBook|Mac(?![a-z])|联想|Lenovo|ThinkPad|拯救者|小新|戴尔|Dell|惠普|华硕|ASUS|小米|荣耀|三星|"
         r"宏碁|Acer|Surface|雷蛇|机械革命|神舟|友商|竞品|竞争对手|对手|同行|其他品牌|其它品牌|别的品牌|别家|隔壁(?:家|品牌)|某品牌|某些品牌")
_NEG_WORDS = (r"不如|不行|差劲|太差|很差|垃圾|烂|拉胯|落后|过时|淘汰|劝退|避雷|坑|智商税|割韭菜|翻车|卡顿|死机|发烫|"
              r"噪音大|太贵|贵得|\blow\b|不好用|难用|被吊打|不堪|廉价|山寨|抄袭|模仿|套路|忽悠|黑心|不靠谱|弱")
_DISPARAGE_RX = re.compile(
    rf"(?:{_COMP})[^，。；！？\n]{{0,10}}?(?:{_NEG_WORDS})"
    rf"|(?:{_NEG_WORDS})[^，。；！？\n]{{0,6}}?(?:{_COMP})"
    rf"|(?:别的|其他|其它|别家|某些|有些|不少|很多)[^，。；！？\n]{{0,6}}?(?:电脑|笔记本|品牌|厂商|产品|机型)[^，。；！？\n]{{0,6}}?(?:{_NEG_WORDS})"
    r"|贬低|嘲讽|踩一脚|黑一下|diss", re.I)
R_COMPETITOR = Rule(
    "competitor_disparage", "贬低竞品", "block",
    "不提及或贬低其他品牌，只写本机型已确认的事实。",
    "删除贬低竞品的分句。",
    _simple(_DISPARAGE_RX, None, severity="block"),
    skip_in_limit=False, check_negation=False)

# ---- 6. fabricated experience ----------------------------------------------
# "软件性能必须在对应版本实测" is a requirement (typically quoted from the KB), not a first-person claim.
_REQUIREMENT_PRE = re.compile(r"(?:必须|需要|须|应当|应在|应先|建议|请先|请|务必|需在|须在|仍需|还需|另需)[^我]{0,16}$")


def _is_requirement(s: str, pos: int) -> bool:
    head = s[:pos]
    cut = max(head.rfind(c) for c in "，,。；;！？!?")
    clause = head[cut + 1:]
    return "我" not in clause and bool(_REQUIREMENT_PRE.search(clause))


_EXP_RX = re.compile(
    r"亲测|实测|亲身|亲眼|亲手|真实体验|真实使用|使用心得|使用感受|上手感受|用后感|开箱|晒单|测评|评测|笔者|本人"
    r"|(?:用|使用|入手|带着|陪着|陪我)了?\s*[\d一二两三四五六七八九十半几]+\s*(?:个)?\s*(?:天|周|星期|礼拜|月|年)"
    r"|我(?!们)[^，。；！？\n]{0,4}?(?:用了|用过|用下来|用着|入手|刚入手|到手|拿到|上手|体验了|体验过|试了|试过|测了|测过|"
    r"带着|背着|扛着|天天|每天|一直|已经|连续|买了|买过|剪了|写了|画了|跑了|办公|通勤|出差|觉得|发现|感觉|个人|自己)"
    r"|我的(?:体验|感受|使用|日常|电脑|本子|真实)")
R_EXPERIENCE = Rule(
    "fabricated_experience", "虚构亲身体验", "block",
    "没有经授权的真实使用记录，不写亲身体验。可以改成“如果你……”的场景设想。",
    "删除亲测、实测、“我用了三个月”等分句；“如果/假设”引导的设想不处理。",
    _simple(_EXP_RX, None, severity="block",
            guard=lambda s, m, c: not (_HYPO_PRE.search(s[max(0, m.start() - 8):m.start()])
                                       or _is_requirement(s, m.start()))),
    skip_in_limit=False)

# ---- 7. fabricated sales / awards / reviews ---------------------------------
_CLAIM_RX = re.compile(
    r"销量(?:第一|冠军|领先|top|\d+万)|销冠|热销|畅销|爆款|卖爆|卖出\s*\d|售出\s*\d|累计销售|全网销量|"
    r"用户好评|好评如潮|好评率|好评|口碑(?:爆棚|第一|炸裂)|五星|回购率|网友(?:都)?说|用户(?:都)?说|买家反馈|客户评价|真实评价|万千用户|百万用户|"
    r"荣获|斩获|摘得|获得[^，。；！？\n]{0,8}奖|获奖|大奖|金奖|红点|iF\s*设计|if\s*设计", re.I)
R_CLAIM = Rule(
    "fabricated_claim", "编造销量、奖项或评价", "block",
    "销量、奖项和用户评价需要官方出处，知识库里没有就不写。",
    "删除相关分句。",
    _simple(_CLAIM_RX, None, severity="block"),
    skip_in_limit=False)

# ---- 8. fake scarcity -------------------------------------------------------
_SCARCE_RX = re.compile(
    r"仅剩|只剩|所剩无几|最后\s*\d*\s*(?:天|小时|名|台|件|个|波|批|机会)|抢完即止|售完即止|手慢无|先到先得|名额有限|数量有限|"
    r"限量|限时|限购|错过(?:再)?等一年|错过(?:就)?没有|错过后悔|晚了就|再不买|马上(?:涨价|售罄|没货)|即将(?:涨价|售罄|下架|结束)|"
    r"倒计时|售罄|脱销|断货|秒光|抢光|抢购一空|爆单|仅限今天|仅限今日|仅此一天|今日截止|今晚截止|截止今天|火爆抢购|疯抢|抢购|不抢就")
R_SCARCITY = Rule(
    "fake_scarcity", "虚假稀缺", "block",
    "不制造稀缺感。库存和活动期限以官方页面为准。",
    "删除限量、限时、手慢无等分句。",
    _simple(_SCARCE_RX, None, severity="block"),
    skip_in_limit=False, check_safe_ctx=True)

# ---- 9. dynamic claims ------------------------------------------------------
_DYN_RX = re.compile(
    r"国补|国家补贴|政府补贴|以旧换新|教育优惠|学生优惠|校园优惠|开学优惠|补贴|立减|直降|直减|满减|减免|返现|红包|优惠券|领券|优惠|"
    r"折扣|打折|促销|特价|赠品|赠送|附赠|买一送|送(?:鼠标|耳机|包|礼|好礼|大礼包|配件|键盘|笔|音箱|电脑包)|礼包|分期|免息|"
    r"0\s*首付|库存|现货|有货|缺货|拼团|大促")


def _dyn_guard(s: str, m: re.Match, ctx: Ctx) -> bool:
    if ctx.in_price_block and nfkc(m.group(0)) in nfkc(ctx.price_note):
        return False
    return True


R_DYNAMIC = Rule(
    "dynamic_claim", "动态信息无出处", "block",
    "国补、优惠、赠品、分期和库存必须有官方出处、渠道、时间和适用 SKU，否则不写。",
    "没有出处的动态信息所在分句删除，并补一句“以结算页为准”。",
    _simple(_DYN_RX, None, severity="block", guard=_dyn_guard),
    skip_in_limit=False, check_safe_ctx=True)

RULES: list[Rule] = [
    R_PRICE, R_EXPERIENCE, R_COMPETITOR, R_CLAIM, R_COMPARE, R_PROMISE,
    R_SCARCITY, R_DYNAMIC, R_ABSOLUTE,
]


def rule_catalog() -> list[dict]:
    """Rule list for docs / the UI / tests."""
    cat = [{"id": r.id, "label": r.label, "severity": r.severity, "strategy": r.strategy} for r in RULES]
    cat.append({"id": "platform_rule", "label": "平台规则", "severity": "warn",
                "strategy": "朋友圈只保留 1 个核心卖点，海报最多 3 个卖点，小红书不写虚构的亲身体验。"})
    return cat


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------
def _scan_sentence(sent: str, where: str, ctx: Ctx, issues: list[ComplianceIssue],
                   limit_block: bool) -> str:
    cur = sent
    for _ in range(14):
        if not cur:
            return ""
        applied = False
        for rule in RULES:
            if limit_block and rule.skip_in_limit:
                continue
            if rule.check_safe_ctx and _SAFE_CTX.search(cur):
                continue
            hits = rule.find(cur, ctx)
            # text inside "（限定：…）" is quoted verbatim from Fact.constraints, never rewritten here
            spans = [(q.start(), q.end()) for q in re.finditer(r"[（(]\s*限定[^）)]*[）)]", cur)]
            if spans and rule.id not in ("price_misleading",):
                hits = [h for h in hits if not any(a <= h.start < b for a, b in spans)]
            hits = [h for h in hits if not (rule.check_negation and _NEG_PRE.search(cur[max(0, h.start - 4):h.start]))]
            if not hits:
                continue
            h = min(hits, key=lambda x: x.start)
            snippet = cur[h.start:h.end]
            sev = h.severity or rule.severity
            sugg = h.note or rule.suggestion
            if h.repl is None:
                new = drop_clause(cur, h.start)
                issues.append(ComplianceIssue(
                    rule=rule.id, rule_label=rule.label, severity=sev, text=snippet,
                    suggestion=sugg, action="removed", where=where))
            else:
                new = cur[:h.start] + h.repl + cur[h.end:]
                issues.append(ComplianceIssue(
                    rule=rule.id, rule_label=rule.label, severity=sev, text=snippet,
                    suggestion=sugg + f"（改写：{cur.strip()[:40]} → {new.strip()[:40]}）" if new else sugg,
                    action="rewritten", where=where))
            cur = new
            applied = True
            break
        if not applied:
            return cur
    return cur


def scan_text(text: str, where: str, ctx: Ctx, issues: list[ComplianceIssue]) -> str:
    """Scan multi-line text sentence by sentence. Returns the cleaned text."""
    limit_block = ctx.note.strip() == "limit"
    lines_out: list[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        kept = []
        for s in split_sentences(line):
            r = _scan_sentence(s, where, ctx, issues, limit_block)
            if r and r.strip():
                kept.append(r)
        joined = "".join(kept).strip()
        if joined:
            lines_out.append(joined)
    return "\n".join(lines_out)


# --------------------------------------------------------------------------
# Platform rules
# --------------------------------------------------------------------------
_SKIP_NOTES = ("scene", "limit", "honest-limit", "price")


def _is_selling_block(b: Block) -> bool:
    if b.kind not in ("para", "list", "callout", "quote"):
        return False
    n = (b.note or "").strip()
    if any(n == k or n.startswith(k) for k in _SKIP_NOTES):
        return False
    return bool(b.fact_ids)


def _moments_single_point(article: Article, task: Optional[TaskSpec], strategy: Optional[Strategy],
                          issues: list[ComplianceIssue]) -> None:
    if not strategy or not strategy.selling_points:
        return
    sps = strategy.selling_points
    block_rank: dict[str, set[int]] = {}
    for b in article.blocks:
        if not _is_selling_block(b):
            continue
        ranks = {sp.rank for sp in sps if set(sp.fact_ids) & set(b.fact_ids)}
        if ranks:
            block_rank[b.id] = ranks
    present = sorted({r for rs in block_rank.values() for r in rs})
    if len(present) <= 1:
        return
    chosen = present[0]
    want = (task.selling_point if task else "") or ""
    if want:
        for sp in sps:
            if sp.rank in present and (want in sp.label or sp.label in want):
                chosen = sp.rank
                break
    drop_ids = [bid for bid, rs in block_rank.items() if chosen not in rs]
    labels = {sp.rank: sp.label for sp in sps}
    for bid in drop_ids:
        b = next(x for x in article.blocks if x.id == bid)
        issues.append(ComplianceIssue(
            rule="platform_rule", rule_label="平台规则：朋友圈只讲 1 个核心卖点", severity="warn",
            text=(b.text.split("\n")[0])[:40],
            suggestion=f"朋友圈只保留「{labels.get(chosen, '核心卖点')}」，其余卖点删除。",
            action="removed", where=bid))
    article.blocks = [b for b in article.blocks if b.id not in set(drop_ids)]


def _poster_points(article: Article, issues: list[ComplianceIssue]) -> None:
    poster = article.poster
    if not isinstance(poster, dict):
        return
    points = poster.get("points")
    if not isinstance(points, list) or len(points) <= 3:
        return
    kept, dropped = points[:3], points[3:]
    kept_f = {f for p in kept for f in (p.get("fact_ids") or [])}
    for p in dropped:
        issues.append(ComplianceIssue(
            rule="platform_rule", rule_label="平台规则：海报最多 3 个卖点", severity="warn",
            text=str(p.get("label") or p.get("text") or "")[:40],
            suggestion="海报最多保留 3 个卖点，多出的已删除。", action="removed", where="poster"))
    poster["points"] = kept
    gone_f = {f for p in dropped for f in (p.get("fact_ids") or [])} - kept_f
    gone_t = [str(p.get("text") or "").strip() for p in dropped if str(p.get("text") or "").strip()]
    new_blocks = []
    for b in article.blocks:
        if b.kind == "list" and gone_t:
            items = [i for i in b.text.split("\n") if not any(t and (t in i or i in t) for t in gone_t)]
            if not items:
                continue
            b = b.model_copy(update={"text": "\n".join(items)})
        elif b.fact_ids and set(b.fact_ids) <= gone_f and _is_selling_block(b):
            continue
        new_blocks.append(b)
    article.blocks = new_blocks


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
_REQ_RULE = {
    "fabricated_price": "price_misleading", "dynamic": "dynamic_claim", "lowest_price": "price_misleading",
    "fake_experience": "fabricated_experience", "competitor": "competitor_disparage",
    "sales_award_review": "fabricated_claim", "absolute": "absolute_wording", "promise": "false_promise",
}
_RULE_LABEL = {r.id: r.label for r in RULES}


def _request_issues(task: Optional[TaskSpec]) -> list[ComplianceIssue]:
    out = []
    if not task:
        return out
    for snip in task.blocked_requests or []:
        cat = classify_blocked(snip)
        rid = _REQ_RULE.get(cat, "platform_rule")
        out.append(ComplianceIssue(
            rule=rid, rule_label=_RULE_LABEL.get(rid, "平台规则") + "（用户要求）", severity="block",
            text=snip, suggestion=blocked_reason(snip), action="removed", where="request"))
    return out


def check_compliance(article: Article, task: Optional[TaskSpec] = None,
                     strategy: Optional[Strategy] = None) -> tuple[Article, list[ComplianceIssue]]:
    art = article.model_copy(deep=True)
    issues: list[ComplianceIssue] = []
    amounts, problems, has_amt, start_only = parse_price_note(art.price_note)
    base = Ctx(platform=art.platform, task=task, strategy=strategy, price_note=art.price_note,
               price_amounts=amounts, price_note_problems=problems,
               price_has_amount_lines=has_amt, price_start_only=start_only)

    def ctx_for(kind: str = "", note: str = "") -> Ctx:
        c = Ctx(**{**base.__dict__})
        c.kind, c.note = kind, note
        return c

    # ---- price blocks that cannot stand (no usable price_note)
    price_issue_added = False
    if problems and (art.price_note or "").strip():
        issues.append(ComplianceIssue(
            rule="price_misleading", rule_label=R_PRICE.label, severity="block",
            text=problems[0][:60], suggestion="补全 SKU、口径、核验时间、条件和官方链接，否则金额不能写。",
            action="flagged", where="price_note"))
    kill_blocks: set[str] = set()
    for b in art.blocks:
        n = (b.note or "").strip()
        if n.startswith("price:") and n != "price:none" and re.search(AMOUNT_RE, nfkc(b.text)):
            if not amounts:
                issues.append(ComplianceIssue(
                    rule="price_misleading", rule_label=R_PRICE.label, severity="block",
                    text=b.text.split("\n")[0][:40],
                    suggestion="价格块缺少完整的价格说明（SKU、口径、核验时间、条件、官方链接），无法保留。",
                    action="blocked", where=b.id))
                kill_blocks.add(b.id)
                price_issue_added = True
                continue
            if not re.search(r"结算页", b.text) or not _DATE_RE.search(nfkc(b.text)):
                issues.append(ComplianceIssue(
                    rule="price_misleading", rule_label=R_PRICE.label, severity="warn",
                    text=b.text.split("\n")[0][:40],
                    suggestion="价格句需要带核验时间，并提示以结算页为准。", action="flagged", where=b.id))

    # ---- text units
    new_blocks: list[Block] = []
    for b in art.blocks:
        if b.id in kill_blocks:
            new_blocks.append(b)
            continue
        if b.kind == "image":
            c = ctx_for(b.kind, b.note)
            b = b.model_copy(update={"text": scan_text(b.text, b.id, c, issues)})
            new_blocks.append(b)
            continue
        c = ctx_for(b.kind, b.note)
        n_before = len(issues)
        t = scan_text(b.text, b.id, c, issues)
        if not t.strip():
            continue
        if c.in_price_block and any(i.rule == "price_misleading" and i.action == "removed"
                                    for i in issues[n_before:]):
            # a price block that lost its amount is meaningless; drop it entirely
            continue
        new_blocks.append(b.model_copy(update={"text": t}))
    art.blocks = new_blocks

    # titles
    c0 = ctx_for("title")
    cleaned_titles = []
    for t in art.titles:
        tmp: list[ComplianceIssue] = []
        r = scan_text(t, "title", c0, tmp)
        if r:
            cleaned_titles.append(r)
        if t == art.title or not art.title:
            issues.extend(tmp)
    title_tmp: list[ComplianceIssue] = []
    new_title = scan_text(art.title, "title", c0, title_tmp)
    if not new_title:
        alt = next((t for t in cleaned_titles if t.strip()), "")
        if alt:
            new_title = alt
            title_tmp.append(ComplianceIssue(
                rule="platform_rule", rule_label="标题改用备选", severity="warn", text=art.title[:40],
                suggestion="原标题含违规表述，已换用合规的备选标题。", action="rewritten", where="title"))
        else:
            new_title = art.title
            title_tmp.append(ComplianceIssue(
                rule="absolute_wording", rule_label="标题无法安全改写", severity="block", text=art.title[:40],
                suggestion="标题整体违规，需要重写。", action="blocked", where="title"))
    seen = {(i.rule, i.text, i.where) for i in issues}
    issues.extend(i for i in title_tmp if (i.rule, i.text, i.where) not in seen)
    art.title = new_title
    rest = [t for t in dedupe(cleaned_titles) if t != new_title]
    art.titles = [new_title] + rest

    # intro / cta / hashtags / disclaimers
    if art.intro:
        art.intro = scan_text(art.intro, "intro", ctx_for("intro"), issues)
    if art.cta:
        new_cta = scan_text(art.cta, "cta", ctx_for("cta"), issues)
        if not new_cta:
            new_cta = SAFE_CTA
            issues.append(ComplianceIssue(
                rule="platform_rule", rule_label="行动引导改写", severity="warn", text=art.cta[:40],
                suggestion="原行动引导含违规表述，已换成通用的官方渠道引导。", action="rewritten", where="cta"))
        art.cta = new_cta
    tags = []
    for h in art.hashtags:
        r = scan_text(h, "hashtag", ctx_for("hashtag"), issues)
        if r.strip("# ").strip():
            tags.append(r)
    art.hashtags = tags
    art.disclaimers = [d for d in (scan_text(d, "disclaimer", ctx_for("disclaimer"), issues) for d in art.disclaimers) if d]

    # poster fields
    if isinstance(art.poster, dict):
        p = dict(art.poster)
        for key in ("main_title", "sub_title", "event_note", "cta"):
            if isinstance(p.get(key), str) and p[key]:
                r = scan_text(p[key], "poster", ctx_for("poster"), issues)
                if not r and key == "main_title":
                    r = art.title
                elif not r and key == "cta":
                    r = SAFE_CTA
                p[key] = r
        pts = []
        for pt in p.get("points") or []:
            if not isinstance(pt, dict):
                continue
            q = dict(pt)
            for key in ("label", "text"):
                if isinstance(q.get(key), str):
                    q[key] = scan_text(q[key], "poster", ctx_for("poster"), issues)
            if (q.get("text") or q.get("label")):
                pts.append(q)
        p["points"] = pts
        art.poster = p

    # platform rules
    if art.platform == "moments":
        _moments_single_point(art, task, strategy, issues)
    elif art.platform == "poster":
        _poster_points(art, issues)

    # tidy: consecutive duplicates of the same issue
    uniq: list[ComplianceIssue] = []
    seen_k = set()
    for i in issues:
        k = (i.rule, i.text, i.where, i.action)
        if k in seen_k:
            continue
        seen_k.add(k)
        uniq.append(i)
    issues = uniq

    # user requests that were refused
    issues.extend(_request_issues(task))

    # settle-page note when price/dynamic wording was removed
    if any(i.rule in ("price_misleading", "dynamic_claim", "fake_scarcity") and i.action in ("removed", "rewritten")
           and i.where != "request" for i in issues) or \
       (task and any(classify_blocked(s) in ("lowest_price", "dynamic", "fabricated_price") for s in task.blocked_requests)):
        if not any("结算页" in d for d in art.disclaimers):
            art.disclaimers = [*art.disclaimers, DISCLAIMER_SETTLE]
    return art, issues
