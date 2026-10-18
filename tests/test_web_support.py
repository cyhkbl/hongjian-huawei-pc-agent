"""Fake backend for the web layer: lets server and UI be tested without the real
knowledge base or pipeline. Data here is invented test material, not KB content.

Run standalone (used by scripts/e2e_web.py):
    python -m tests.test_web_support --port 7861
"""
from __future__ import annotations

import io
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from app.models import (
    Article, Block, ClarifyOption, Clarification, ComplianceIssue, EngineInfo, EvidencePack,
    Fact, FactCheckItem, ImageAsset, ImageCheckItem, ImageRef, ImageSlot, KBStatus,
    ProductModel, ReviseRequest, RunRequest, RunResult, SellingPointPlan, SourceItem,
    StageLog, Strategy, TaskSpec, TraceEntry, Verification,
)

FAKE_CLIENT_ID = "fake-client-id-0123456789"
FAKE_API_KEY = "fake-api-key-SECRET-9876543210"
FAKE_LLM_KEY = "sk-fake-llm-key-ABCDEF123456"

STAGE_PLAN = [
    ("parse", "解析任务", "识别到型号、平台和场景"),
    ("strategy", "场景与平台策略", "选定切入点和卖点顺序"),
    ("retrieve", "知识库检索", "检索 3 次，命中 12 条资料"),
    ("extract", "事实提取", "选出 9 条可引用事实"),
    ("compose", "图文编排与生成", "按平台结构生成正文"),
    ("verify_fact", "事实核验", "逐句核对，1 句改写"),
    ("verify_image", "图片核验", "图片型号与来源通过"),
    ("compliance", "合规检查", "命中 1 处，已改写"),
    ("finalize", "整理与导出", "已落盘运行档案"),
]


def make_png(w: int = 640, h: int = 400, color=(199, 0, 11)) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, w - 10, h - 10], outline=(255, 255, 255), width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


MODELS = [
    ProductModel(model_id="pro-hm", name="HUAWEI MateBook Pro", short_name="MateBook Pro",
                 series="MateBook Pro", os_family="harmonyos", os_label="HarmonyOS 6",
                 aliases=["MateBook Pro"], confusable_with=["pros-hm"], snapshot_date="2026-10-17",
                 has_public_price=True),
    ProductModel(model_id="pros-hm", name="HUAWEI MateBook Pro S", short_name="MateBook Pro S",
                 series="MateBook Pro", os_family="harmonyos", os_label="HarmonyOS 6",
                 confusable_with=["pro-hm"]),
    ProductModel(model_id="mb14-hm", name="HUAWEI MateBook 14（鸿蒙版）", short_name="MateBook 14 鸿蒙版",
                 series="MateBook 14", os_family="harmonyos", os_label="HarmonyOS 6",
                 confusable_with=["mb14-ultra"]),
    ProductModel(model_id="mb14-ultra", name="HUAWEI MateBook 14 酷睿 Ultra", short_name="MateBook 14 酷睿 Ultra",
                 series="MateBook 14", os_family="windows", os_label="Windows 11",
                 confusable_with=["mb14-hm"]),
]

FACTS = {
    "pro-hm:card02:01": Fact(
        id="pro-hm:card02:01", model_id="pro-hm", kind="card", category="display",
        text="屏幕尺寸 14.2 英寸，3:2 比例触控屏。", constraints=["以官方商城页面标注为准"],
        tags=["display", "creative"], source_title="HUAWEI MateBook Pro｜02-屏幕与显示卡",
        source_path="P1-产品参数库/06-型号检索卡/HUAWEI MateBook Pro/02-屏幕与显示卡.md",
        source_urls=["https://consumer.huawei.com/cn/laptops/matebook-pro/"], verified_date="2026-10-17"),
    "pro-hm:card04:02": Fact(
        id="pro-hm:card04:02", model_id="pro-hm", kind="card", category="portable",
        text="机身厚度约 14.9 毫米，适合日常携带。", constraints=[], tags=["portable"],
        source_title="HUAWEI MateBook Pro｜04-便携续航接口卡",
        source_path="P1-产品参数库/06-型号检索卡/HUAWEI MateBook Pro/04-便携续航接口卡.md",
        source_urls=["https://consumer.huawei.com/cn/laptops/matebook-pro/specs/"], verified_date="2026-10-17"),
    "pro-hm:card04:05": Fact(
        id="pro-hm:card04:05", model_id="pro-hm", kind="selling", category="connect",
        text="配有雷电与 USB-C 接口，外接显示器和扩展坞方便。", constraints=["具体接口数量以实物为准"],
        tags=["ports", "office"], source_title="HUAWEI MateBook Pro｜04-便携续航接口卡",
        source_path="P1-产品参数库/06-型号检索卡/HUAWEI MateBook Pro/04-便携续航接口卡.md",
        source_urls=["https://consumer.huawei.com/cn/laptops/matebook-pro/specs/"], verified_date="2026-10-17"),
    "pro-hm:card05:01": Fact(
        id="pro-hm:card05:01", model_id="pro-hm", kind="card", category="ecosystem",
        text="支持与华为手机、平板多屏协同。", constraints=["需登录同一华为账号"], tags=["collab"],
        source_title="HUAWEI MateBook Pro｜05-系统协同与兼容卡",
        source_path="P1-产品参数库/06-型号检索卡/HUAWEI MateBook Pro/05-系统协同与兼容卡.md",
        source_urls=["https://consumer.huawei.com/cn/laptops/matebook-pro/"], verified_date="2026-10-17"),
}

IMAGES = {
    "hwpc_matebook-pro_front_01.png": ImageAsset(
        id="hwpc_matebook-pro_front_01.png", model_id="pro-hm", caption="MateBook Pro 正面，屏幕点亮",
        tags=["appearance", "display"], width=640, height=400,
        source_url="https://example.invalid/img/pro-front.png",
        page_url="https://consumer.huawei.com/cn/laptops/matebook-pro/",
        kb_path="P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro/images/hwpc_matebook-pro_front_01.png"),
    "hwpc_matebook-pro_ports_02.png": ImageAsset(
        id="hwpc_matebook-pro_ports_02.png", model_id="pro-hm", caption="MateBook Pro 侧面接口",
        tags=["ports"], width=400, height=640,
        source_url="https://example.invalid/img/pro-ports.png",
        page_url="https://consumer.huawei.com/cn/laptops/matebook-pro/",
        kb_path="P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro/images/hwpc_matebook-pro_ports_02.png"),
}
IMAGE_BYTES = {"hwpc_matebook-pro_front_01.png": make_png(640, 400),
               "hwpc_matebook-pro_ports_02.png": make_png(400, 640, (40, 40, 40))}


class FakeKB:
    def __init__(self):
        self.refreshed = 0

    def status(self) -> KBStatus:
        return KBStatus(
            mode="local_mirror", kb_name="任德耀新建华为PC知识库（本地镜像）", connected=True,
            detail="未配置 ima 凭证，当前读取本地镜像。", account_hint="fake****89",
            api_key_hint="****10", ima_configured=False, models=len(MODELS), facts=len(FACTS),
            images=len(IMAGES), prices=3, snapshot_date="2026-10-17",
            last_response={"code": 0, "msg": "local mirror", "endpoint": "local_index"},
            trace=[TraceEntry(step="local_index", request={"query": "MateBook Pro"}, count=12, ms=4)])

    def refresh(self):
        self.refreshed += 1

    def models(self):
        return MODELS

    def image_bytes(self, image_id: str):
        if image_id not in IMAGE_BYTES:
            raise KeyError(image_id)
        return IMAGE_BYTES[image_id], "image/png"


def _hook_for(scenario: str) -> str:
    return {"back_to_school": "新学期开箱前，先想清楚一台电脑要陪你走多远",
            "creator": "做图做剪辑的人，最先看的是屏幕"}.get(scenario, "先从你每天真正会做的事说起")


def build_ok_run(req: RunRequest, platform: str = "xiaohongshu", scenario: str = "back_to_school",
                 selling_point: str = "", parent: str = "", note: str = "", short: bool = False) -> RunResult:
    first = "pro-hm:card02:01" if scenario != "back_to_school" else "pro-hm:card04:02"
    order = [first] + [k for k in FACTS if k not in (first, "pro-hm:card04:05")]
    if selling_point == "续航":
        order = ["pro-hm:card04:02", "pro-hm:card02:01"]
    image_n = {"xiaohongshu": 2, "wechat_mp": 2, "moments": 1, "poster": 1}[platform]
    imgs = list(IMAGES.values())[:image_n]

    blocks = [
        Block(id="b1", kind="para", text="周末去宿舍帮学弟搬电脑，才发现背包里的重量最容易被忽略。",
              note="场景引入，无产品断言"),
        Block(id="b2", kind="heading", text="屏幕是第一印象"),
        Block(id="b3", kind="para", text="屏幕尺寸 14.2 英寸，3:2 比例触控屏。改稿和看论文都不用频繁滚动。",
              fact_ids=["pro-hm:card02:01"]),
        Block(id="b4", kind="image", text=imgs[0].caption, image_id=imgs[0].id),
        Block(id="b5", kind="para", text="机身厚度约 14.9 毫米，适合日常携带。公认的全网最轻薄之一。",
              fact_ids=["pro-hm:card04:02"]),
    ]
    blocks[-1].text = "机身厚度约 14.9 毫米，适合日常携带。"
    if not short:
        blocks += [
            Block(id="b6", kind="list", text="配有雷电与 USB-C 接口。\n外接显示器和扩展坞方便。",
                  fact_ids=["pro-hm:card04:05"]),
            Block(id="b7", kind="para", text="支持与华为手机、平板多屏协同，需登录同一华为账号。",
                  fact_ids=["pro-hm:card05:01"]),
        ]
    refs = [ImageRef(image_id=im.id, file_name=im.id, model_id=im.model_id, model_name="HUAWEI MateBook Pro",
                     caption=im.caption, position="第 1 节标题下" if i == 0 else "结尾之前",
                     after_block="b3" if i == 0 else "b5", source_url=im.source_url, page_url=im.page_url,
                     kb_path=im.kb_path, reason="与该节讲的屏幕直接对应") for i, im in enumerate(imgs)]
    article = Article(
        platform=platform, titles=["开学前，我替你把电脑的几件事问清楚了", "新生选本：先看屏幕，再看重量", "一台本子，宿舍到教室"],
        title="开学前，我替你把电脑的几件事问清楚了", intro="新学期要带电脑的人，先看这三件事。", blocks=blocks,
        cta="想亲手试试屏幕和键盘，可以到华为授权门店体验。", hashtags=["#开学季", "#华为笔记本", "#MateBookPro"],
        image_refs=refs,
        sources=[SourceItem(ref=f"F{i + 1:02d}", fact_id=f.id, model_name="HUAWEI MateBook Pro", text=f.text,
                            source_title=f.source_title, source_path=f.source_path, source_urls=f.source_urls,
                            verified_date=f.verified_date) for i, f in enumerate(FACTS.values())],
        disclaimers=["配置与价格以华为官方渠道为准。"])
    if platform == "poster":
        article.poster = {"main_title": "开学，带一台好用的本子", "sub_title": "HUAWEI MateBook Pro",
                          "points": [{"label": "屏幕", "text": "14.2 英寸 3:2 触控屏", "fact_ids": ["pro-hm:card02:01"]},
                                     {"label": "便携", "text": "约 14.9 毫米机身", "fact_ids": ["pro-hm:card04:02"]},
                                     {"label": "协同", "text": "多屏协同", "fact_ids": ["pro-hm:card05:01"]}],
                          "event_note": "到店体验，具体活动以门店公示为准", "image_id": imgs[0].id,
                          "cta": "到店体验"}
    verification = Verification(
        facts=[FactCheckItem(block_id="b1", sentence="周末去宿舍帮学弟搬电脑，才发现背包里的重量最容易被忽略。",
                             status="pass", reason="纯场景句，无产品断言"),
               FactCheckItem(block_id="b3", sentence="屏幕尺寸 14.2 英寸，3:2 比例触控屏。", status="pass",
                             fact_ids=["pro-hm:card02:01"], reason="与事实原文一致"),
               FactCheckItem(block_id="b3", sentence="改稿和看论文都不用频繁滚动。", status="flag",
                             reason="属于使用感受推断，无事实依据，已标注"),
               FactCheckItem(block_id="b5", sentence="机身厚度约 14.9 毫米，适合日常携带。", status="pass",
                             fact_ids=["pro-hm:card04:02"]),
               FactCheckItem(block_id="b5", sentence="公认的全网最轻薄之一。", status="removed",
                             before="公认的全网最轻薄之一。", reason="无事实依据，且含绝对化表述")],
        images=[ImageCheckItem(image_id=im.id, model_ok=True, source_ok=True, file_ok=True, status="pass")
                for im in imgs],
        compliance=[ComplianceIssue(rule="absolute_wording", rule_label="绝对化用语", severity="block",
                                    text="全网最轻薄", suggestion="删除或改为有出处的具体参数", action="removed",
                                    where="b5")],
        pending=["未提供颜色款式，图片按官网默认色选取"], verdict="pass_with_flags",
        stats={"sentences": 6, "cited": 4, "removed": 1, "rewritten": 0, "flagged": 1, "images_ok": len(imgs),
               "compliance_blocks": 1})
    strategy = Strategy(
        scenario_label="开学季" if scenario == "back_to_school" else "内容创作",
        platform_label={"xiaohongshu": "小红书", "wechat_mp": "公众号", "moments": "门店朋友圈", "poster": "门店海报"}[platform],
        audience=req.audience or "大学新生", usage_scene="宿舍、教室、图书馆之间背着走",
        purchase_stage="比较", pain_points=["背着重", "屏幕小看论文累"],
        goal="让新生记住两个选择理由", hook=_hook_for(scenario),
        tone="口语、克制、不夸张", structure=["开头场景", "屏幕", "便携", "协同", "行动引导"] if platform != "moments" else ["一句话卖点", "行动引导"],
        length="600-900字" if platform == "xiaohongshu" else "1200-1800字", image_count=image_n,
        image_slots=[ImageSlot(slot="封面", purpose="吸引点击", prefer_tags=["appearance"]),
                     ImageSlot(slot="正文1", purpose="佐证屏幕", prefer_tags=["display"])][:image_n],
        cta="到店体验" if platform != "wechat_mp" else "点击阅读原文了解官方配置",
        selling_points=[SellingPointPlan(rank=i + 1, label=FACTS[f].text[:12], fact_ids=[f],
                                         why="开学季更看重携带" if i == 0 else "其次是看书写字的屏幕")
                        for i, f in enumerate(order[:3])],
        rationale=["切入点选“背包重量”，因为新生最先感受到的是携带负担。", "卖点顺序：便携 → 屏幕 → 协同。",
                   f"{image_n} 张图：封面 + 屏幕佐证。", "行动引导落在线下体验。"])
    return RunResult(
        run_id="r" + uuid.uuid4().hex[:10], created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        parent_run_id=parent, revision_note=note, status="ok",
        task=TaskSpec(raw=req.text, model_ids=["pro-hm"], platform=platform, scenario=scenario,
                      audience=req.audience or "大学新生", selling_point=selling_point,
                      confusion_notes=["MateBook Pro 与 Pro S 相近，已按“MateBook Pro”处理"]),
        strategy=strategy,
        evidence=EvidencePack(models=[MODELS[0]], facts=list(FACTS.values()), used_fact_ids=list(FACTS),
                              images=imgs and list(IMAGES.values()), used_image_ids=[i.id for i in imgs],
                              trace=[TraceEntry(step="local_index", request={"query": "MateBook Pro 屏幕"}, count=6, ms=3)]),
        article=article, verification=verification,
        engine=EngineInfo(writer="composer", kb_mode="local_mirror", prompt_version="test-1"),
        timeline=[StageLog(stage=s, label=l, ms=10 + i * 7, note=n) for i, (s, l, n) in enumerate(STAGE_PLAN)])


def build_clarify(req: RunRequest) -> RunResult:
    return RunResult(
        run_id="r" + uuid.uuid4().hex[:10], created_at=time.strftime("%Y-%m-%dT%H:%M:%S"), parent_run_id=req.parent_run_id,
        status="needs_clarification", task=TaskSpec(raw=req.text, missing=["model"]),
        clarifications=[Clarification(
            field="model", question="MateBook 14 有两个版本，要写哪一个？",
            reason="两个版本系统和处理器平台不同，混写会出错。",
            options=[ClarifyOption(value="mb14-hm", label="MateBook 14 鸿蒙版", hint="HarmonyOS，适合想用鸿蒙生态的人"),
                     ClarifyOption(value="mb14-ultra", label="MateBook 14 酷睿 Ultra", hint="Windows 11，需要运行 Windows 软件")])],
        timeline=[StageLog(stage="parse", label="解析任务", ms=5, note="型号有歧义"),
                  StageLog(stage="clarify", label="生成追问", ms=2, note="1 个问题")])


def build_refused(req: RunRequest) -> RunResult:
    return RunResult(
        run_id="r" + uuid.uuid4().hex[:10], created_at=time.strftime("%Y-%m-%dT%H:%M:%S"), status="refused",
        refusal="知识库里没有这款机型的国补金额，也没有“全网最低价”的出处，不能写进文案。",
        task=TaskSpec(raw=req.text, blocked_requests=["写国补立减2000", "全网最低价"]),
        timeline=[StageLog(stage="parse", label="解析任务", ms=5, note="发现 2 处不能写的要求")])


class FakeServices:
    """Same surface as app.web.services.Services."""

    def __init__(self, runs_dir: Optional[Path] = None, delay: float = 0.0, fail_with: Optional[Exception] = None):
        self.kb_ = FakeKB()
        self._runs_dir = runs_dir
        self.delay = delay
        self.fail_with = fail_with
        self.calls: list[tuple] = []
        self.lock = threading.Lock()

    # ---- context
    def settings(self):
        class S:  # noqa: D401
            ima_client_id = FAKE_CLIENT_ID
            ima_api_key = FAKE_API_KEY
            llm_api_key = FAKE_LLM_KEY
        return S()

    def kb(self):
        return self.kb_

    def secrets(self):
        return [FAKE_CLIENT_ID, FAKE_API_KEY, FAKE_LLM_KEY]

    def runs_dir(self):
        return self._runs_dir

    def warm(self):
        pass

    # ---- pipeline
    def _emit(self, on_stage: Optional[Callable], stages):
        for s, l, n in stages:
            if self.delay:
                time.sleep(self.delay)
            if on_stage:
                on_stage(StageLog(stage=s, label=l, ms=12, note=n))

    def _save(self, run: RunResult) -> RunResult:
        if self._runs_dir:
            self._runs_dir.mkdir(parents=True, exist_ok=True)
            (self._runs_dir / f"{run.run_id}.json").write_text(run.model_dump_json(), encoding="utf-8")
        return run

    def run(self, req: RunRequest, on_stage=None) -> RunResult:
        self.calls.append(("run", req))
        if self.fail_with:
            raise self.fail_with
        text = req.text
        if not req.model_ids and ("轻薄本" in text or "MateBook 14" in text):
            self._emit(on_stage, STAGE_PLAN[:1])
            return self._save(build_clarify(req))
        if "国补" in text or "全网最低" in text:
            self._emit(on_stage, STAGE_PLAN[:1])
            return self._save(build_refused(req))
        self._emit(on_stage, STAGE_PLAN)
        platform = req.platform or ("poster" if "海报" in text else "moments" if "朋友圈" in text else "xiaohongshu")
        scenario = req.scenario or ("creator" if "创作" in text else "back_to_school")
        return self._save(build_ok_run(req, platform, scenario, req.selling_point, parent=req.parent_run_id))

    def revise(self, req: ReviseRequest, prev: RunResult, on_stage=None) -> RunResult:
        self.calls.append(("revise", req))
        if self.fail_with:
            raise self.fail_with
        self._emit(on_stage, STAGE_PLAN[:1] + STAGE_PLAN[4:])
        platform = req.platform or (prev.article.platform if prev.article else "xiaohongshu")
        short = "短" in req.instruction
        run = build_ok_run(RunRequest(text=prev.task.raw), platform, req.scenario or prev.task.scenario or "back_to_school",
                           req.selling_point, parent=prev.run_id, note=req.instruction, short=short)
        return self._save(run)

    def export(self, run: RunResult, fmt: str):
        if fmt == "md":
            return (f"# {run.article.title}\n\n密钥测试 {FAKE_API_KEY}\n").encode("utf-8"), "text/markdown; charset=utf-8", f"{run.run_id}.md"
        if fmt == "json":
            return run.model_dump_json().encode("utf-8"), "application/json", f"{run.run_id}.json"
        if fmt == "docx":
            raise ImportError("python-docx")
        raise ValueError(fmt)

    def prompt(self):
        return "# 一、角色与任务\n你是鸿笺。\n# 二、场景理解\n...\n# 三、平台规则\n...", "test-1"

    # ---- selftest
    def selftest_cases(self):
        return [{"id": "t1", "group": "统一测试", "title": "基础生成", "input": "给 MateBook Pro 写开学季小红书",
                 "expect": "状态 ok"},
                {"id": "t2", "group": "参考难题", "title": "只说想买轻薄本", "input": "想买个轻薄本", "expect": "追问"}]

    def selftest_run(self, case_id: str):
        if case_id not in ("t1", "t2"):
            raise KeyError(case_id)
        return {"id": case_id, "title": "x", "group": "统一测试", "passed": case_id == "t1",
                "checks": [{"name": "状态", "passed": case_id == "t1", "detail": "status=ok"}],
                "evidence": "run_id=rtest", "ms": 12}

    # ---- kb
    def kb_status(self, refresh=False):
        if refresh:
            self.kb_.refresh()
        return self.kb_.status()


# ---------------------------------------------------------------------------
# standalone server for browser tests
# ---------------------------------------------------------------------------
def serve(port: int = 7861, delay: float = 0.25) -> None:  # pragma: no cover
    import tempfile
    import uvicorn
    from app.web.server import create_app
    runs = Path(tempfile.mkdtemp(prefix="hj_runs_"))
    uvicorn.run(create_app(FakeServices(runs_dir=runs, delay=delay)), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--delay", type=float, default=0.25)
    a = ap.parse_args()
    serve(a.port, a.delay)
