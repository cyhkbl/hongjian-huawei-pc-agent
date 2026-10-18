# 鸿笺 Hongjian · 华为 PC 营销软文智能体 — 内部设计与分工契约

> 内部协作文档（teammates 必读）。对外 README / 作品说明书由 Lead 另写。
> 项目根：`D:\DeepSeekWorkSpace\hackathlon\hongjian`。Python：`.\.venv\Scripts\python.exe`（已装 fastapi uvicorn httpx pydantic pytest pytest-asyncio pillow）。如需新依赖，先告诉 Lead，固定版本。
> 本机 KB 副本（仅开发用，**不得拷进仓库**，主办方禁止对外传播）：
> `D:\DeepSeekWorkSpace\hackathlon\kb_raw\华为PC全板块深度知识库_v7\`（下文称 `$KB`）。

## 1. 赛题要点（初赛看完整性、方向、可用性、真实；复赛看 7 项打分）
自研 Agent；**ima 只是产品事实与图片的来源**，场景理解/平台规则/系统提示词/图文编排/事实核验/合规都在我们的 Agent 里。
主链路：场景解析 → 平台策略 → ima 资料与图片检索 → 事实点提取 → 图文编排 → 软文生成 → 事实与图片核验 → 合规检查 → 导出。

- 8 场景：开学季、职场办公、内容创作（不得编造软件测试结果）、家庭换新、企业采购（不得承诺 KB 外政策）、门店到访（单一卖点）、新品首发（价格/权益必须有出处）、节日营销（不得编造折扣/补贴/库存）。
- 4 平台：公众号（标题、导语、分节、结尾 CTA，2–4 图）、小红书（口语标题、短段、场景、话题标签，3–6 图，不得虚构亲身体验）、门店朋友圈（短文案、1 个核心卖点、CTA，1–3 图）、门店海报（主副标题、≤3 卖点、活动说明，1 张主视觉且不拉伸）。
- 8 个最小功能模块：①账号与知识库（显示当前账号、KB 名称、连接状态、接口返回，**绝不显示完整 key**）②任务输入（产品/人群/场景/渠道，缺信息要追问）③知识与图片检索（调 ima OpenAPI，留来源记录）④场景与平台策略（可解释，换场景/平台输出必须实质不同）⑤图文软文生成（标题、正文、CTA、图片引用与插入位置、避免套话）⑥事实核验（逐条核对，无依据删除或标注，机型混淆测试）⑦合规检查（绝对化、虚假承诺、价格误导、无依据对比、贬低竞品）⑧修改与导出（临时需求重生成，复制/导出，缩短/换渠道/换卖点）。
- 统一输出四段：一、场景判断（目标人群/使用场景、用户问题/内容目标/平台）二、知识库依据（型号/事实点/资料标题）三、图文软文（标题/导语/正文/行动引导；图片名称/来源/插入位置/图片说明）四、核验结果（产品事实/图片型号/合规/待确认信息）。
- 系统提示词必须含 8 模块：角色与任务、场景理解、平台规则、知识库约束、图片规则、生成要求（标题、导语、正文、配图方案、行动引导、平台标签）、核验规则（无法确认不得生成；资料冲突停止输出并提示人工确认）、合规规则。
- 红线：图片非 ima 或与型号不符 → 图片项 0 分；编造价格/补贴/销量/奖项/用户评价 → 该任务事实与合规 0 分。
- 评委统一测试：基础生成；换场景（切入点、卖点顺序、图片规划必须变）；换平台（结构、语气、图片数、CTA 必须变）；干扰与修改（相近机型、信息不全 → 追问；临时改稿 → 核验+合规+重生成）。参考难题：只说“想买轻薄本”要追问；相近机型混淆；要求写 KB 没有的价格/补贴要拒绝；跨平台改写。

## 2. 知识库（$KB）结构与解析要点
- `P1-产品参数库/` 事实源。10 个重点型号目录（每个含 `产品事实.md`、`卖点与限制.md`、`来源清单.csv`、`图片索引.csv`、`images/`）：
  - `01-鸿蒙电脑/`：`HUAWEI MateBook 14`（鸿蒙版，另有 `商城款式图片/` 15 张，索引列不同：文件名,画面说明,宽度,高度,原始图片URL,商品页URL,抓取日期）、`HUAWEI MateBook Fold 非凡大师`、`HUAWEI MateBook Pro`、`HUAWEI MateBook Pro S`
  - `02-MateBook-Windows/`：`MateBook 14 酷睿 Ultra`、`MateBook D 14`（2024）、`MateBook D 16`（2024）、`MateBook D 16 SE 版`、`MateBook GT 系列`（官方名 HUAWEI MateBook GT 14）、`MateBook X系列`（官方名 HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版）
  - **目录名 ≠ 官方名**，官方全称在各文档标题里（`# HUAWEI MateBook 14（鸿蒙版） - 产品事实`）。
  - `06-型号检索卡/<型号>/01..06-*.md`：6 张卡（身份/屏幕与显示/性能与存储/便携续航接口/系统协同与兼容/适用人群与限制），结构固定：`## 检索结论` `## 已确认事实`(bullets) `## 限定条件`(bullets) `## 适用任务` `## 不适用或需先验证的任务` `## 待核验项` `## 来源入口`(含官方 URL)；其后 `<!-- v6-expanded-lookup-card -->` 之后是长篇“字段解读”，**忽略**。
  - `卖点与限制.md`：`## 一句话定位`，`### 1..6` 六个角度，每个有“可用结论 / 支撑事实 / 表达边界”。
  - `产品事实.md`：官方规格摘录（`## 屏幕`、`## 处理器` 等二级标题，键值逐行），文末有“即将离开 consumer.huawei.com”噪声要去掉。
  - `00-全库横向索引/全部图片联合检索表.csv`：112 行（文件名,产品型号,画面说明,原始图片URL,页面来源,本地目录），**其中 59 行（MateBook 14 的 商城款式图片 + 部分）产品型号为空，要用 `本地目录` 判型号**。`全型号总览.md` 有每型号摘要。
  - `08-官方公开价格快照/官方价格快照.csv`：141 条（列：记录ID,规范产品名称,原始产品名称,分类,精确款式,型号或SKU,价格类型,页面金额（元）,参考或划线金额（元）,条件摘要,库存状态,地区上下文,登录状态,核验时间,来源标题,官方URL,取证方式,证据摘要,核验状态,映射备注,原始记录ID）。消费级 PC 里只有 MateBook 14（鸿蒙版，14 条）、Fold、Pro（鸿蒙版）、Pro S 有商城金额；酷睿 Ultra/D14/D16/D16 SE/GT/X Pro 均为“商城已下架/无当前公开商城价/仅官网参考起价”。规则见 `01-字段字典与调用规则.md`、`04-Agent价格问答测试集.md`（必读）。
  - `04-华为商城销售款式/`：`商城在售款式快照.md`、`MateBook 14 鸿蒙版销售配置.md`。
- `P6-营销素材库/02-平台模板/*.md`（公众号/小红书/朋友圈/门店海报等创作指南）、`08-合规/售后与促销表述红线.md`、`09-按型号平台/`、`11-完整软文成稿库/`（**仅参考表达结构，必须原创改写，禁止抄写**）。`P8-客户场景库/`、`P2-卖点话术库/`、`P7-常见问题库/`、`00-建库规范/06-智能体规则/`（检索顺序/拒答/引用/事实核验/图片核验规则）。`P4-价格政策库（机密）` 只有模板；`90-待审核`、`99-历史归档` 不得作为事实。
- **真实 ima 共享知识库**（“任德耀新建华为PC知识库”，接口返回 314 项）的目录**与上面的本地 zip 不完全相同**：按目录进入 `P1-产品参数库`，每个型号有 `article.md`。所以 ima 适配器必须能**遍历目录、读取任意 md/csv/图片**，解析器必须同时能吃本地 zip 布局和“只有 article.md 的布局”（对 article.md 用通用解析：按标题/列表拆成带来源的事实句）。ima 模式无法在本机联调（没有凭证），一定要用 mock 服务器写测试，并且在代码里严格按官方文档字段名。

## 3. ima OpenAPI（官方 skill v1.1.10，已核对）
- Base `https://ima.qq.com`，全部 `POST` JSON，路径 `/openapi/wiki/v1/<api>`；Header：`ima-openapi-clientid`、`ima-openapi-apikey`、`Content-Type: application/json`（官方脚本另带 `ima-openapi-ctx: skill_version=1.1.10`，可带）。环境变量：`IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`（也接受 `IMA_CLIENT_ID` / `IMA_API_KEY`）。
- 统一返回 `{code, msg, data}`；`code==0` 成功；`code!=0` 把 `msg` 原样展示。错误码：110021 频控（退避重试）、110010 下游网络（可重试）、110030 无权限。
- `search_knowledge_base` `{"query","cursor":"","limit":20}` → `data.info_list[]`（赛题手册说实际返回字段为 `kb_id`、`kb_name`；官方文档写 `id`、`name`；**两种都要兼容**），`is_end`，`next_cursor`。KB 名：`任德耀新建华为PC知识库`。**搜索无结果不等于无权限，必须回退到浏览**。
- `get_knowledge_list` `{"knowledge_base_id","cursor":"","limit":50,["folder_id"]}` → `data.knowledge_list[]`（`media_id,title,parent_folder_id`；文件夹条目另有 folder 信息，文件夹的 id 以返回的 `media_id` 为准），`is_end`，`next_cursor`，`current_path`。**限制 limit 1–50**。
- `search_knowledge` `{"query","cursor":"","knowledge_base_id"}` → `data.info_list[]`（`media_id,title,parent_folder_id,highlight_content`）。
- `get_media_info` `{"media_id"}` → `data.media_type`、`data.url_info{url,headers}`（有 headers 时请求 url 需带上）；无 `url_info` 表示不可访问；笔记类型走 `notebook_ext_info`。
- `get_knowledge_base` `{"ids":[...]}` → `data.infos{id:{id,name,cover_url,description,recommended_questions}}`。
- 展示给用户时**绝不暴露** `knowledge_base_id/media_id/folder_id`，只显示名称/标题；凭证只显示掩码（`app.config.mask`）。

## 4. 架构与模块契约

```
app/
  models.py            # 共享数据契约（已写好，Lead 维护；要改字段先告诉 Lead）
  config.py            # 环境变量/掩码（已写好）
  context.py           # AppContext：kb、settings、llm（Lead 写）
  kb/                  # [kb-dev] 知识层
    base.py            # KnowledgeBase Protocol（已写好）
    vfs.py             # 虚拟文件系统：LocalFS(KB_LOCAL_DIR) / ImaFS(遍历目录+get_media_info+磁盘缓存)
    ima_client.py      # 官方 OpenAPI 客户端（httpx，重试/退避/脱敏 trace）
    indexer.py         # 解析器：vfs -> ProductModel/Fact/ImageAsset/PriceRecord
    store.py           # KnowledgeBase 实现（内存索引 + 检索 + trace + status）
    __init__.py        # get_kb(settings) -> KnowledgeBase
  agent/
    understand.py      # [rules-dev] 任务解析/追问/拒绝/机型消歧
    compliance.py      # [rules-dev] 合规规则引擎（检测+改写+拦截）
    verify.py          # [rules-dev] 事实核验 + 图片核验
    selftest.py        # [rules-dev] 内置评测集（统一测试、参考难题）
    profiles.py        # [writer-dev] 8 场景 × 4 平台 的策略数据
    strategy.py        # [writer-dev] 生成 Strategy（可解释）
    retrieve.py        # [writer-dev] 依据策略选事实/图片，形成 EvidencePack
    prompts.py         # [writer-dev] 系统提示词（8 模块）+ 用户消息构造
    llm.py             # [writer-dev] OpenAI 兼容客户端（未配置则返回 None）
    compose.py         # [writer-dev] 生成：LLM 路径 + 确定性编排路径（Composer）
    pipeline.py        # [writer-dev] run()/revise() 串联全链路
    export.py          # [writer-dev] md/txt/html/docx/json 导出
  web/                 # [web-dev]
    server.py          # FastAPI（API + 静态资源 + SSE）
    static/            # 前端（无构建步骤：index.html + css + es modules）
  main.py              # [web-dev] uvicorn 入口，监听 0.0.0.0:7860
tests/                 # 各自写各自的 test_*.py
```

### 4.1 AppContext（`app/context.py`，Lead 提供）
```python
@dataclass
class AppContext:
    settings: Settings
    kb: KnowledgeBase
    llm: Optional["LLMClient"]   # None => deterministic composer
def get_context() -> AppContext   # 进程内单例
```

### 4.2 rules-dev 的函数签名
```python
# understand.py
def parse_task(req: RunRequest, kb: KnowledgeBase) -> tuple[TaskSpec, list[Clarification]]
#  - 从 req.text + 结构化字段解析 model/platform/scenario/audience/selling_point/want_price
#  - 缺型号、缺平台、缺场景（可由受众推断时给默认并写进 confusion_notes）→ 返回 Clarification（选项来自 kb.models()，带 hint）
#  - “想买轻薄本”这种只有品类 → 追问用途/预算外的关键信息并给候选机型（hint 写一句话区别）
#  - 系列名有歧义（"MateBook 14"=鸿蒙版 vs 酷睿 Ultra；"D 16" vs "D 16 SE"；"Pro" vs "Pro S"）→ 追问，绝不自动选
#  - 请求里含违规要求（编价格/补贴/“全网最低”/编亲身体验/贬低竞品）→ 记入 TaskSpec.blocked_requests，由 pipeline 拒绝或改写
# compliance.py
def check_compliance(article: Article, task: TaskSpec, strategy: Strategy) -> tuple[Article, list[ComplianceIssue]]
#  - 规则：绝对化(第一/最/唯一/全网最低/100%/完美/零风险/永久/终身/绝对…)、虚假承诺(保证/一定/无条件/全国免费…)、价格误导(无 SKU/时间/类型的金额、国补/补贴/立减/限时/库存/赠品未出处)、无依据对比(碾压/吊打/领先同级/比XX强)、竞品贬低、虚构亲身体验(“我用了三个月”“实测”在无授权数据时)、平台硬规则(朋友圈 1 个卖点、海报 ≤3 卖点、小红书无亲身体验)
#  - 返回修订后的 Article（rewritten/removed 已生效）+ 逐条 ComplianceIssue（block 级无法安全改写时 action="blocked"）
# verify.py
def check_facts(article: Article, evidence: EvidencePack, kb: KnowledgeBase) -> tuple[Article, list[FactCheckItem], list[str]]
#  - 把每个 para/list/heading/callout 拆句；每句：无 fact_ids 的纯场景句 pass(note)；带数字/型号/参数/功能名的句子必须能在其引用 Fact 文本中找到支撑（数字、型号词、核心名词），否则 removed 或 rewritten(降级为 Fact 原文表述)；跨型号拼接→removed；Fact.constraints 缺失→flag 并补限定语
#  - 返回修订后的 Article、逐句记录、待确认信息(list[str])
def check_images(article: Article, kb: KnowledgeBase) -> tuple[Article, list[ImageCheckItem]]
#  - 每个 image_ref：KB 里存在、model_id == 文中所写机型、source_url/page_url 非空、文件可解码、颜色款与文中提到的颜色冲突、数量符合平台上限；不通过则移除并在 ImageCheckItem 里说明；海报主视觉宽高比不得被强制拉伸（只做 aspect 记录）
def build_verification(fact_items, image_items, issues, pending, article) -> Verification   # 算 verdict/stats
# selftest.py
def cases() -> list[dict]; def run_case(ctx, case_id) -> dict   # 评测集：统一测试 4 组 + 参考难题；每条有 input、期望断言(函数)、结果、证据
```

### 4.3 writer-dev 的函数签名
```python
# strategy.py
def build_strategy(task: TaskSpec, models: list[ProductModel], pool: list[Fact]) -> Strategy
# retrieve.py
def gather(task: TaskSpec, strategy: Strategy, kb: KnowledgeBase) -> EvidencePack
#  - 先 kb.search(...) 产生可见的 ima 检索 trace，再用结构化 facts/images 取证；事实按场景 tags 打分选 8–14 条；图片按 image_slots 的 prefer_tags 选候选（含同型号约束+颜色一致）；价格仅在 task.want_price 或场景=新品首发/节日营销等需要时带上 PriceRecord，且只带“可引用”的（有金额、有 SKU、有时间、有 URL）
# prompts.py
SYSTEM_PROMPT: str  (版本号 PROMPT_VERSION，八个模块逐一成节，赛题要求的模块一个不少)
def build_user_message(task, strategy, evidence) -> str
# llm.py
class LLMClient: def chat_json(system:str, user:str) -> dict   # OpenAI 兼容 /chat/completions，response_format json 失败则降级正则取 JSON
def get_llm(settings) -> Optional[LLMClient]
# compose.py
def compose(task, strategy, evidence, llm: Optional[LLMClient]) -> tuple[Article, EngineInfo]
#  - llm 不为 None：让模型只能用 evidence 里的 fact id / image id，输出 JSON(blocks…)；解析失败自动降级到 Composer 并在 EngineInfo/timeline 里如实标注
#  - Composer（确定性）：按 profile 的结构模板 + 事实句，场景不同切入点/卖点顺序不同，平台不同结构/语气/图数/CTA 不同；文案要像人写的（参考平台模板，原创，避免“震撼/颠覆/全能”等套话）；每个含产品断言的 Block 必须带 fact_ids
# pipeline.py
def run(req: RunRequest, ctx: AppContext, on_stage: Optional[Callable[[StageLog], None]] = None) -> RunResult
def revise(req: ReviseRequest, prev: RunResult, ctx: AppContext, on_stage=None) -> RunResult
#  - 流程：parse_task → (追问/拒绝 直接返回) → build_strategy → gather → compose → check_facts → check_images → check_compliance → (有 block 级问题则最多自动修复 1 轮再核验) → build_verification → 落盘 runs/<run_id>.json
#  - revise：把自然语言指令解析为对 task 的改动（换平台/换场景/换主卖点/删价格/缩短/删某节），然后重跑全链路，保留 parent_run_id 与 revision_note
# export.py
def export(run: RunResult, fmt: str, kb) -> tuple[bytes, str, str]   # (data, mime, filename)；docx 用 python-docx 需 Lead 确认依赖，先实现 md/txt/html/json
```

### 4.4 HTTP API（web-dev）
`GET /api/health` · `GET /api/kb/status`（KBStatus；`?refresh=1` 触发重新连接/同步）· `GET /api/options`（场景/平台中文名、示例任务、模型列表）· `POST /api/run`（RunRequest → RunResult）· `POST /api/run/stream`（SSE：`event: stage` 数据为 StageLog，最后 `event: result` 数据为 RunResult；错误 `event: error`）· `POST /api/revise`（+ `/api/revise/stream`）· `GET /api/runs`、`GET /api/runs/{id}` · `GET /api/image/{image_id}`（二进制，带正确 mime，缓存头；找不到 404）· `POST /api/export`（返回文件，Content-Disposition）· `GET /api/prompt`（系统提示词全文+版本）· `GET /api/selftest/cases`、`POST /api/selftest/run`。
鉴权：Space 公开演示不加登录，但**所有接口不得返回凭证原文**；`/api/kb/status` 只含掩码。

## 5. 差异化亮点（要做出来，不是写在 PPT 里）
1. **证据溯源阅读器**：软文每句可悬停/点击，右侧显示对应 KB 事实、资料标题、KB 路径、官方 URL、核验日期。
2. **图—型号一致性闸门**：每张图展示“型号✓ 来源✓ 文件✓”徽章，图片名/来源/插入位置/说明一应俱全，原比例展示不拉伸。
3. **机型混淆守卫 + 追问**：相近型号（MateBook 14 鸿蒙/酷睿 Ultra，D 16 / D 16 SE，Pro / Pro S）不自动选择，以带差异 hint 的选项追问。
4. **价格守卫**：金额只会以“SKU+口径+核验时间+条件+官方链接”整体出现；被问到 KB 没有的价格/补贴/库存 → 明确拒绝并说明原因。
5. **可解释策略面板**：切入点、卖点排序理由、配图计划、CTA 理由，换场景/平台后并排对比（Diff 视图）。
6. **合规红线扫描**：高亮命中词、规则名、改写前后，block 级自动拦截。
7. **自然语言修改**：“删掉价格 / 换成朋友圈 / 主卖点换成续航 / 再短一点”，改完重新核验，记录版本链。
8. **运行档案**：每次运行完整 JSON（任务→策略→证据→稿件→核验→ima 调用 trace），可下载复核，里面没有任何凭证。
9. **Agent 自测台**：内置评测集（统一测试 + 参考难题），一键跑并显示通过/失败与证据。
10. **海报成品**：门店海报直接在页面渲染并可导出 PNG（前端 canvas，使用原比例主视觉）。

## 6. 硬约束（违反即严重缺陷）
- 产品参数/功能/价格/卖点只能来自 KB 的 Fact/PriceRecord；LLM 或 Composer 不得自带知识。写文案时每个产品断言必须有 `fact_ids`。
- 图片只能来自 KB 图片库，并且 `ImageAsset.model_id` 必须等于文中所写机型；任何时候都不能引用别的机型的图。
- 价格相关：不同口径（页面价/预估到手价/搭配价/官网起价/询价）不混；没有金额的机型不得写金额；“下架”要如实说；动态信息（库存/补贴/赠品/活动）默认不写，除非 KB 有记录并带条件和时间。
- 不虚构亲身体验、用户评价、销量、奖项；不抄 P6 成稿库原文。
- 仓库内**不得**出现任何密钥；不得提交 KB 原始内容（`kb_local/`、`.kb_cache/`、`runs/` 已在 .gitignore）；测试夹具只能用自造的最小样例。
- 任何环节失败都要给出可读的错误/降级说明，不能静默。ima 未配置时，状态面板如实显示“本地镜像模式”，**不得伪造 ima 返回**。

## 7. 写入范围（互不重叠）
- kb-dev：`app/kb/**`、`tests/test_kb_*.py`、`tests/fixtures/kb_mini/**`、`scripts/kb_*.py`
- rules-dev：`app/agent/understand.py compliance.py verify.py selftest.py`、`tests/test_rules_*.py`
- writer-dev：`app/agent/profiles.py strategy.py retrieve.py prompts.py llm.py compose.py pipeline.py export.py`、`tests/test_writer_*.py`
- web-dev：`app/web/**`、`app/main.py`、`tests/test_web_*.py`
- Lead：`app/models.py app/config.py app/context.py`、README、docs、部署文件。
如需改别人的文件，**发消息给对方 owner**；如需改 models.py，发消息给 Lead。

## 8. 开发环境
- 设置 `KB_LOCAL_DIR=D:\DeepSeekWorkSpace\hackathlon\kb_raw\华为PC全板块深度知识库_v7` 后 `KB_MODE=local` 走本地镜像。
- 运行：`.\.venv\Scripts\python.exe -m app.main`；测试：`.\.venv\Scripts\python.exe -m pytest -q`。
- 先让“垂直切片”跑通（一条 MateBook Pro × 小红书 × 开学季的完整链路），再扩全 8 场景×4 平台。
