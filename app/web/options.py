"""Static option data for the UI: scenario / platform labels, examples, shortcuts.

Everything here is presentation data. Product facts never live here; the model
list comes from the knowledge base at request time.
"""
from __future__ import annotations

SCENARIOS = [
    {"id": "back_to_school", "label": "开学季",
     "desc": "面向新生和家长，从宿舍、课堂、社团和随身携带写起。"},
    {"id": "office", "label": "职场办公",
     "desc": "围绕通勤、会议、文档和多设备协同，语气偏稳。"},
    {"id": "creator", "label": "内容创作",
     "desc": "写剪辑、绘图、写作的屏幕和性能。不得编造软件测试结果。"},
    {"id": "home_upgrade", "label": "家庭换新",
     "desc": "旧电脑换新，兼顾家人共用、学习和娱乐。"},
    {"id": "enterprise_procurement", "label": "企业采购",
     "desc": "写配置、管理和售后能说清的部分。不承诺知识库以外的政策。"},
    {"id": "store_visit", "label": "门店到访",
     "desc": "邀请到店体验，只讲一个卖点。"},
    {"id": "new_launch", "label": "新品首发",
     "desc": "写新机的定位和变化。价格、权益必须有出处。"},
    {"id": "festival", "label": "节日营销",
     "desc": "借节日场景切入。不编折扣、补贴和库存。"},
]

PLATFORMS = [
    {"id": "wechat_mp", "label": "公众号",
     "desc": "标题、导语、分节正文、结尾行动引导，配图 2 到 4 张。", "images": "2-4"},
    {"id": "xiaohongshu", "label": "小红书",
     "desc": "口语标题、短段落、场景感、话题标签，配图 3 到 6 张。不虚构亲身体验。", "images": "3-6"},
    {"id": "moments", "label": "门店朋友圈",
     "desc": "短文案，只讲 1 个核心卖点，带行动引导，配图 1 到 3 张。", "images": "1-3"},
    {"id": "poster", "label": "门店海报",
     "desc": "主副标题、不超过 3 个卖点、活动说明，1 张主视觉，保持原比例。", "images": "1"},
]

AUDIENCES = ["大学新生", "研究生", "职场新人", "内容创作者", "家长", "企业 IT 采购", "到店顾客"]

SELLING_POINTS = ["续航", "屏幕", "接口", "AI 能力", "轻薄便携", "多设备协同", "性能", "做工与外观"]

EXAMPLES = [
    {"id": "ex-basic-xhs", "kind": "run", "category": "基础生成",
     "title": "MateBook Pro × 开学季 × 小红书",
     "text": "给 HUAWEI MateBook Pro 写一篇开学季的小红书笔记，面向大学新生。",
     "expect": "走完整条链路，输出四段结果"},
    {"id": "ex-basic-mp", "kind": "run", "category": "基础生成",
     "title": "MateBook GT 14 × 职场办公 × 公众号",
     "text": "为 HUAWEI MateBook GT 14 写一篇职场办公主题的公众号文章，卖点放在便携和续航。",
     "expect": "公众号结构：标题备选、导语、分节、结尾行动引导"},
    {"id": "ex-scene", "kind": "run", "category": "换场景",
     "title": "同一台机器换到内容创作",
     "text": "同样是 HUAWEI MateBook Pro 的小红书，这次换成内容创作场景，面向剪辑和绘图的人。",
     "expect": "切入点、卖点顺序、配图规划都应不同，可在“对比”里并排看"},
    {"id": "ex-platform-poster", "kind": "run", "category": "换平台",
     "title": "改成门店海报",
     "text": "给 HUAWEI MateBook Pro 做一张开学季门店海报，只保留三个卖点。",
     "expect": "海报成品在页面渲染，主视觉保持原比例，可导出 PNG"},
    {"id": "ex-platform-moments", "kind": "run", "category": "换平台",
     "title": "Fold 门店朋友圈",
     "text": "写一条门店朋友圈，主推 HUAWEI MateBook Fold 非凡大师的大屏，结尾邀请到店体验。",
     "expect": "短文案，只讲一个卖点"},
    {"id": "ex-clarify-category", "kind": "run", "category": "追问",
     "title": "只说想买轻薄本",
     "text": "想买个轻薄本，帮我写篇软文。",
     "expect": "只有品类，没有型号，会追问并给候选机型"},
    {"id": "ex-clarify-confusable", "kind": "run", "category": "追问",
     "title": "MateBook 14 有两个版本",
     "text": "给 MateBook 14 写一篇公众号文章。",
     "expect": "鸿蒙版与酷睿 Ultra 版不自动选择，带差异说明追问"},
    {"id": "ex-refuse-price", "kind": "run", "category": "拒绝",
     "title": "要求写国补和全网最低价",
     "text": "写一条 MateBook D 16 的朋友圈，写上国补立减 2000 元，再加一句全网最低价。",
     "expect": "知识库没有的价格和补贴不写，说明原因"},
    {"id": "ex-refuse-experience", "kind": "run", "category": "拒绝",
     "title": "要求编亲身体验",
     "text": "给 HUAWEI MateBook Pro 写小红书，开头写“我用了三个月，续航一天一充”。",
     "expect": "不虚构亲身体验，改写或拒绝"},
    {"id": "ex-revise-short", "kind": "revise", "category": "改稿",
     "title": "再短一点",
     "text": "再短一点，保留最重要的两个卖点。",
     "expect": "需要先有一篇稿件。改后重新核验并记入版本链"},
    {"id": "ex-revise-price", "kind": "revise", "category": "改稿",
     "title": "删掉价格，主卖点换续航",
     "text": "删掉价格相关的内容，把主卖点换成续航。",
     "expect": "需要先有一篇稿件。卖点顺序随之变化"},
    {"id": "ex-revise-platform", "kind": "revise", "category": "改稿",
     "title": "换成朋友圈",
     "text": "换成门店朋友圈，只留一个卖点。",
     "expect": "需要先有一篇稿件。结构、图数和行动引导都会变"},
]

REVISE_SHORTCUTS = [
    {"label": "再短一点", "instruction": "再短一点，保留最重要的卖点。"},
    {"label": "删掉价格", "instruction": "删掉价格相关的内容。"},
    {"label": "换成朋友圈", "instruction": "换成门店朋友圈。", "platform": "moments"},
    {"label": "换成小红书", "instruction": "换成小红书。", "platform": "xiaohongshu"},
    {"label": "换成公众号", "instruction": "换成公众号。", "platform": "wechat_mp"},
    {"label": "换成海报", "instruction": "换成门店海报。", "platform": "poster"},
    {"label": "主卖点：续航", "instruction": "把续航换成主卖点。", "selling_point": "续航"},
    {"label": "主卖点：屏幕", "instruction": "把屏幕换成主卖点。", "selling_point": "屏幕"},
    {"label": "主卖点：接口", "instruction": "把接口换成主卖点。", "selling_point": "接口"},
    {"label": "主卖点：AI", "instruction": "把 AI 能力换成主卖点。", "selling_point": "AI 能力"},
]

STAGES = [
    {"id": "parse", "label": "解析任务"},
    {"id": "strategy", "label": "场景与平台策略"},
    {"id": "retrieve", "label": "知识库检索"},
    {"id": "extract", "label": "事实提取"},
    {"id": "compose", "label": "图文编排与生成"},
    {"id": "verify_fact", "label": "事实核验"},
    {"id": "verify_image", "label": "图片核验"},
    {"id": "compliance", "label": "合规检查"},
    {"id": "finalize", "label": "整理与导出"},
]
