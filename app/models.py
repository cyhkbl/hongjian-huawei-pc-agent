"""Shared data contract for 鸿笺 (Hongjian) - Huawei PC marketing-copy agent.

Every module (kb / agent / web) depends on these models. Change with care and
tell the Lead when a field is added or renamed.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Enumerations (plain string literals so JSON stays readable)
# --------------------------------------------------------------------------
PlatformId = Literal["wechat_mp", "xiaohongshu", "moments", "poster"]
ScenarioId = Literal[
    "back_to_school",        # 开学季
    "office",                # 职场办公
    "creator",               # 内容创作
    "home_upgrade",          # 家庭换新
    "enterprise_procurement",  # 企业采购
    "store_visit",           # 门店到访
    "new_launch",            # 新品首发
    "festival",              # 节日营销
]
FactKind = Literal["spec", "card", "selling", "boundary", "fit", "unfit", "faq"]
FactCategory = Literal[
    "identity", "display", "performance", "portable", "connect",
    "ecosystem", "audience", "limit", "other",
]
Origin = Literal["local_mirror", "ima"]


# --------------------------------------------------------------------------
# Knowledge layer
# --------------------------------------------------------------------------
class ProductModel(BaseModel):
    model_id: str                      # slug, e.g. "mb14-hm", "pro-hm", "pros-hm", "fold", "mb14-ultra", "d14", "d16", "d16se", "gt14", "xpro"
    name: str                          # full official name, e.g. "HUAWEI MateBook 14（鸿蒙版）"
    short_name: str                    # e.g. "MateBook 14 鸿蒙版"
    series: str                        # e.g. "MateBook 14"
    os_family: Literal["harmonyos", "windows"]
    os_label: str                      # e.g. "HarmonyOS 6" / "Windows 11 家庭版"
    aliases: list[str] = Field(default_factory=list)  # user-facing names used for matching
    confusable_with: list[str] = Field(default_factory=list)  # model_ids easily mixed up
    official_urls: list[str] = Field(default_factory=list)
    snapshot_date: str = ""            # KB fact baseline date, e.g. "2026-10-17"
    has_public_price: bool = False     # at least one price record with an amount


class Fact(BaseModel):
    """One atomic, citable product statement."""
    id: str                            # stable global id, e.g. "pro-hm:card02:03"
    model_id: str
    kind: FactKind
    category: FactCategory
    text: str                          # the statement itself, verbatim from KB (may be a spec line "屏幕尺寸：14.2 英寸")
    constraints: list[str] = Field(default_factory=list)  # 限定条件 that MUST travel with the fact
    tags: list[str] = Field(default_factory=list)         # scenario matching tags, e.g. ["portable","battery","ports","display","ai","collab","creative","office","study","travel"]
    source_title: str                  # KB document title, e.g. "HUAWEI MateBook Pro｜02-屏幕与显示卡"
    source_path: str                   # KB-relative path, e.g. "P1-产品参数库/06-型号检索卡/HUAWEI MateBook Pro/02-屏幕与显示卡.md"
    source_urls: list[str] = Field(default_factory=list)  # official URLs listed in that doc
    verified_date: str = ""            # e.g. "2026-10-17"
    origin: Origin = "local_mirror"


class ImageAsset(BaseModel):
    id: str                            # file name, unique, e.g. "hwpc_matebook-pro-s_精致产品细节_01_9e99c213.jpg"
    model_id: str                      # which product the picture shows (decided from its KB directory / index)
    caption: str                       # 官网图片说明 / 画面说明
    kind: Literal["official", "mall"] = "official"
    tags: list[str] = Field(default_factory=list)  # derived from caption: ["appearance","display","ports","performance","collab","scene","color","detail"]
    color: str = ""                    # colour variant if caption names one ("原野绿" ...), else ""
    width: int = 0
    height: int = 0
    source_url: str = ""               # 原始图片URL
    page_url: str = ""                 # 页面来源 / 商品页URL
    kb_path: str = ""                  # KB-relative path of the image file
    usage_note: str = ""               # 建议用途 / 使用边界 from the index
    origin: Origin = "local_mirror"


class PriceRecord(BaseModel):
    record_id: str
    model_id: Optional[str] = None     # None when record belongs to an accessory/extended product
    product_name: str
    category: str = ""
    spec: str = ""                     # 精确款式
    price_type: str                    # 官方商城页面价 / 预估到手价 / 官网参考起价 / 官方询价 / 未公开金额 / 当前商城状态 ...
    amount: Optional[float] = None     # 页面金额（元）
    ref_amount: Optional[float] = None
    conditions: str = ""
    stock: str = ""
    verified_at: str = ""
    url: str = ""
    status: str = ""                   # 核验状态
    origin: Origin = "local_mirror"


class SearchHit(BaseModel):
    title: str
    path: str = ""
    snippet: str = ""
    model_id: Optional[str] = None


class TraceEntry(BaseModel):
    """One KB / ima call, shown in the UI as retrieval record."""
    step: str                          # "search_knowledge_base" | "get_knowledge_list" | "search_knowledge" | "get_media_info" | "local_index" ...
    request: dict = Field(default_factory=dict)   # sanitized; NEVER contains keys
    code: Optional[int] = None         # ima response code, None for local
    msg: str = ""
    count: Optional[int] = None
    ms: int = 0
    origin: Origin = "local_mirror"


class KBStatus(BaseModel):
    mode: Literal["ima", "local_mirror", "none"]
    kb_name: str = ""
    connected: bool = False
    detail: str = ""                   # human sentence, e.g. "已连接 ima 共享知识库「任德耀新建华为PC知识库」"
    account_hint: str = ""             # masked client id, e.g. "a1b2****9f"; "" when not configured
    api_key_hint: str = ""             # masked api key, e.g. "****" + last 2 chars; NEVER the full key
    ima_configured: bool = False
    models: int = 0
    facts: int = 0
    images: int = 0
    prices: int = 0
    snapshot_date: str = ""
    last_response: dict = Field(default_factory=dict)   # {"code":0,"msg":"success","endpoint":"..."} of the last ima call
    trace: list[TraceEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Task understanding
# --------------------------------------------------------------------------
class ClarifyOption(BaseModel):
    value: str
    label: str
    hint: str = ""


class Clarification(BaseModel):
    field: Literal["model", "platform", "scenario", "audience", "config", "price_sku", "other"]
    question: str
    reason: str = ""
    options: list[ClarifyOption] = Field(default_factory=list)
    allow_free_text: bool = False


# --------------------------------------------------------------------------
# 对话式需求挖掘（Converse）
# --------------------------------------------------------------------------
class ChatChoice(BaseModel):
    """对话里的一个可点选项。"""
    value: str
    label: str
    hint: str = ""


class ChatTurn(BaseModel):
    """Agent 发起的一轮提问。"""
    question_id: str
    question: str
    why: str = ""
    choices: list[ChatChoice] = Field(default_factory=list)
    multi: bool = False
    allow_skip: bool = True
    free_text_hint: str = ""


class ChatState(BaseModel):
    """多轮对话进度：已知什么、还缺什么、问过什么。"""
    session_id: str = ""
    turns_used: int = 0
    max_turns: int = 4
    known: dict = Field(default_factory=dict)
    asked: list[str] = Field(default_factory=list)
    pending: Optional[ChatTurn] = None
    ready: bool = False
    defaults_applied: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str = ""
    text: str = ""
    choice_value: str = ""
    skip: bool = False


class TaskSpec(BaseModel):
    raw: str = ""
    model_ids: list[str] = Field(default_factory=list)   # usually 1; >1 only for an explicit comparison task
    platform: Optional[PlatformId] = None
    scenario: Optional[ScenarioId] = None
    audience: str = ""
    selling_point: str = ""            # user-requested focus, e.g. "续航" ; "" if none
    length_hint: str = ""              # "短" / "长" / ""
    want_price: bool = False
    extras: list[str] = Field(default_factory=list)      # raw extra instructions
    missing: list[str] = Field(default_factory=list)
    blocked_requests: list[str] = Field(default_factory=list)  # user asks we must refuse, e.g. "写国补立减2000" / "写全网最低价" / "编一段亲身体验"
    confusion_notes: list[str] = Field(default_factory=list)   # e.g. "MateBook 14 同名：鸿蒙版 vs 酷睿 Ultra，已按用户指定的鸿蒙版"


# --------------------------------------------------------------------------
# Strategy
# --------------------------------------------------------------------------
class SellingPointPlan(BaseModel):
    rank: int
    label: str                         # e.g. "3:2 OLED 触控屏"
    fact_ids: list[str]
    why: str                           # explainable reason for this ranking under this scenario


class ImageSlot(BaseModel):
    slot: str                          # "封面" / "正文1" / "主视觉" ...
    purpose: str
    prefer_tags: list[str] = Field(default_factory=list)


class Strategy(BaseModel):
    scenario_label: str
    platform_label: str
    audience: str
    usage_scene: str
    purchase_stage: str                # 认知/比较/决策/到店 ...
    pain_points: list[str]
    goal: str
    hook: str                          # opening angle in one sentence (no product facts invented)
    tone: str
    structure: list[str]               # ordered section names
    length: str                        # "1200-1800字" ...
    image_count: int
    image_slots: list[ImageSlot]
    cta: str
    selling_points: list[SellingPointPlan]
    rationale: list[str]               # bullet explanations: why this hook / order / image plan / CTA


# --------------------------------------------------------------------------
# Article
# --------------------------------------------------------------------------
class Block(BaseModel):
    id: str                            # "b1", "b2" ...
    kind: Literal["heading", "para", "list", "image", "quote", "callout"]
    text: str = ""                     # for heading/para/list ("\n"-separated items)/callout; for image: caption
    fact_ids: list[str] = Field(default_factory=list)   # facts this block's claims rely on ([] only for pure scene/transition text)
    image_id: str = ""                 # for kind == "image"
    note: str = ""                     # e.g. 'scene-setting, no product claim'


class ImageRef(BaseModel):
    image_id: str
    file_name: str
    model_id: str
    model_name: str
    caption: str
    position: str                      # "导语之后" / "第2节标题下" / "海报主视觉" ...
    after_block: str = ""              # block id the image follows
    source_url: str = ""
    page_url: str = ""
    kb_path: str = ""
    origin: Origin = "local_mirror"
    reason: str = ""                   # why this image fits that spot


class SourceItem(BaseModel):
    ref: str                           # "F03"
    fact_id: str
    model_name: str
    text: str
    source_title: str
    source_path: str
    source_urls: list[str] = Field(default_factory=list)
    verified_date: str = ""


class Article(BaseModel):
    platform: PlatformId
    titles: list[str]                  # alternatives; titles[0] is the chosen one
    title: str
    intro: str = ""                    # 导语 (poster: sub-title)
    blocks: list[Block]
    cta: str
    hashtags: list[str] = Field(default_factory=list)
    image_refs: list[ImageRef] = Field(default_factory=list)
    sources: list[SourceItem] = Field(default_factory=list)
    price_note: str = ""               # non-empty only when a price is written; contains SKU/type/time/conditions/URL
    disclaimers: list[str] = Field(default_factory=list)
    poster: Optional[dict] = None      # poster only: {"main_title","sub_title","points":[{"label","text","fact_ids"}],"event_note","image_id","cta"}


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
class FactCheckItem(BaseModel):
    block_id: str
    sentence: str
    status: Literal["pass", "flag", "removed", "rewritten"]
    fact_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    before: str = ""                   # original text when removed/rewritten


class ImageCheckItem(BaseModel):
    image_id: str
    model_ok: bool
    source_ok: bool                    # exists in KB index with source url/page
    file_ok: bool                      # file readable & decodable
    aspect_ok: bool = True             # not stretched: render uses original aspect
    status: Literal["pass", "fail"]
    reason: str = ""


class ComplianceIssue(BaseModel):
    rule: str                          # "absolute_wording" | "false_promise" | "price_misleading" | "unsupported_comparison" | "competitor_disparage" | "fabricated_experience" | "dynamic_claim" | "fake_scarcity" | "platform_rule"
    rule_label: str
    severity: Literal["block", "warn"]
    text: str                          # offending snippet
    suggestion: str
    action: Literal["removed", "rewritten", "flagged", "blocked"]
    where: str = ""                    # block id / "title" / "cta"


class Verification(BaseModel):
    facts: list[FactCheckItem]
    images: list[ImageCheckItem]
    compliance: list[ComplianceIssue]
    pending: list[str]
    verdict: Literal["pass", "pass_with_flags", "blocked"]
    stats: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------
# 一稿四发 / 标题评分 / 今日推荐 / 新品事实卡 / 一题三解
# --------------------------------------------------------------------------
class TitleScore(BaseModel):
    title: str
    score: int
    reasons: list[str]
    tags: list[str]


class DailyIdea(BaseModel):
    """给门店销售员的「今天该写什么」。"""
    idea_id: str
    title: str
    scenario: str
    platform: str
    model_id: str
    model_name: str
    reason: str
    season_tag: str = ""
    effort: str = "一键生成"


class FactGroup(BaseModel):
    label: str
    facts: list[str]
    fact_ids: list[str] = Field(default_factory=list)


class PlaybookStep(BaseModel):
    """门店实战手册的一步：说一句、做一个动作、守一条边界。"""
    label: str
    fact_ids: list[str] = Field(default_factory=list)
    say: str                           # 顾客能感知的一句话
    do: str                            # 现场可做的动作
    care: str                          # 必须守住的口径/限制


class Playbook(BaseModel):
    """把软文变成到店接待脚本。"""
    title: str
    platform: str
    platform_note: str = ""
    steps: list[PlaybookStep] = Field(default_factory=list)
    cta: str = ""
    closing: str = ""


class PreflightItem(BaseModel):
    """发布前预演发现的一条：读者会追问或可能被卡的表述。"""
    kind: str                          # ask（会被追问） | risky（有风险）
    where: str                         # 标题 / 正文 / 价格 / 配图 / 全文
    text: str
    ask: str                           # 读者会怎么问
    prep: str                          # 提前准备什么


class Preflight(BaseModel):
    """发布前预演：站在读者视角挑刺。"""
    title: str
    platform: str
    verdict: str                       # ok | check | risky
    note: str = ""
    ready_to_send: bool = False
    items: list[PreflightItem] = Field(default_factory=list)


class FactCard(BaseModel):
    """新品事实卡：生成前先讲清这台机器能说什么、不能说什么。"""
    model_id: str
    model_name: str
    ok: bool = True
    os_label: str = ""
    snapshot_date: str = ""
    groups: list[FactGroup] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    limit_fact_ids: list[str] = Field(default_factory=list)
    unconfirmed: list[str] = Field(default_factory=list)
    price_lines: list[str] = Field(default_factory=list)
    note: str = ""


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
class EvidencePack(BaseModel):
    models: list[ProductModel]
    facts: list[Fact]                  # the facts offered to the writer for this run
    used_fact_ids: list[str] = Field(default_factory=list)
    images: list[ImageAsset]
    used_image_ids: list[str] = Field(default_factory=list)
    prices: list[PriceRecord] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)


class StageLog(BaseModel):
    stage: str                         # parse | clarify | strategy | retrieve | extract | compose | verify_fact | verify_image | compliance | finalize
    label: str
    ms: int = 0
    note: str = ""


class EngineInfo(BaseModel):
    writer: Literal["llm", "composer"]
    llm_model: str = ""
    kb_mode: str = ""
    prompt_version: str = ""
    note: str = ""                     # e.g. "LLM 调用失败，已降级为确定性编排：<原因>"


class RunResult(BaseModel):
    run_id: str
    created_at: str
    parent_run_id: str = ""
    revision_note: str = ""
    status: Literal["ok", "needs_clarification", "blocked", "refused"]
    refusal: str = ""                  # when status == refused: why (e.g. fabricate price)
    task: TaskSpec
    clarifications: list[Clarification] = Field(default_factory=list)
    strategy: Optional[Strategy] = None
    evidence: Optional[EvidencePack] = None
    article: Optional[Article] = None
    verification: Optional[Verification] = None
    engine: Optional[EngineInfo] = None
    timeline: list[StageLog] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------
class RunRequest(BaseModel):
    text: str = ""                     # free-form task, e.g. "给 MateBook Pro 写一篇开学季小红书"
    model_ids: list[str] = Field(default_factory=list)   # structured override (from clarification chips / form)
    platform: Optional[PlatformId] = None
    scenario: Optional[ScenarioId] = None
    audience: str = ""
    selling_point: str = ""
    want_price: bool = False
    parent_run_id: str = ""            # when answering a clarification, link to the previous run
    extras: list[str] = Field(default_factory=list)      # extra style instructions (persona prompts)
    persona: str = ""                  # persona key: counter / senior / neighbor / buyer


class PersonaRunRequest(BaseModel):
    """一题三解：同一任务用不同人设各写一篇。"""
    text: str = ""
    model_ids: list[str] = Field(default_factory=list)
    scenario: Optional[ScenarioId] = None
    platform: Optional[PlatformId] = None
    audience: str = ""
    selling_point: str = ""
    personas: list[str] = Field(default_factory=list)


class PersonaRunResult(BaseModel):
    persona_set_id: str
    created_at: str
    scenario: str
    platform: str
    personas: list[dict]
    runs: list[RunResult]
    diff: dict = Field(default_factory=dict)


class BatchRunRequest(BaseModel):
    """一稿四发：同一任务跑多个平台。"""
    text: str = ""
    model_ids: list[str] = Field(default_factory=list)
    scenario: Optional[ScenarioId] = None
    audience: str = ""
    selling_point: str = ""
    platforms: list[PlatformId] = Field(default_factory=list)
    parent_run_id: str = ""


class BatchRunResult(BaseModel):
    batch_id: str
    created_at: str
    task: TaskSpec
    runs: list[RunResult]
    diff: dict = Field(default_factory=dict)


class TitleScoreRequest(BaseModel):
    titles: list[str]
    platform: PlatformId
    model_name: str = ""


class ReviseRequest(BaseModel):
    run_id: str
    instruction: str                   # "删掉价格" / "换成朋友圈" / "把续航换成主卖点" / "再短一点"
    platform: Optional[PlatformId] = None
    scenario: Optional[ScenarioId] = None
    selling_point: str = ""


class ExportRequest(BaseModel):
    run_id: str
    format: Literal["md", "txt", "html", "docx", "json", "png"] = "md"
