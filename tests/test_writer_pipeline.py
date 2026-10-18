"""writer-dev 的单元/集成测试（FakeKB，不依赖真实 KB）。"""
from __future__ import annotations

import json
import re

import httpx
import pytest

from app.agent import profiles as P
from app.agent.compose import compose, compose_with_composer
from app.agent.export import export
from app.agent.llm import LLMClient, LLMError, _extract_json, get_llm
from app.agent.pipeline import parse_revision, revise, run
from app.agent.prompts import BANNED_WORDS, PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from app.agent.retrieve import gather
from app.agent.strategy import build_strategy
from app.config import Settings
from app.context import AppContext
from app.models import EngineInfo, ReviseRequest, RunRequest, TaskSpec
from tests.test_writer_support import FakeKB

SC = P.SCENARIO_ORDER
PL = P.PLATFORM_ORDER


def mk(kb, scenario="office", platform="wechat_mp", model="demo-h", **kw):
    t = TaskSpec(raw="x", model_ids=[model], platform=platform, scenario=scenario, **kw)
    s = build_strategy(t, [kb.get_model(model)], kb.facts(model))
    ev = gather(t, s, kb)
    return t, s, ev


@pytest.fixture
def kb():
    return FakeKB()


@pytest.fixture
def ctx(tmp_path, kb):
    st = Settings(ima_client_id="", ima_api_key="", ima_base_url="", ima_kb_name="", kb_mode="local", kb_local_dir="",
                  cache_dir=tmp_path / "c", llm_base_url="", llm_api_key="", llm_model="", llm_timeout=5.0,
                  host="127.0.0.1", port=1, runs_dir=tmp_path / "runs")
    return AppContext(settings=st, kb=kb, llm=None)


# ---------------- 策略 ----------------
def test_profiles_complete():
    assert set(P.SCENARIOS) == set(SC) and set(P.PLATFORMS) == set(PL)
    for sid, sc in P.SCENARIOS.items():
        for k in ("audience", "usage_scene", "stage", "pains", "goal", "weights", "hooks", "img_pref", "taboo", "cta", "titles"):
            assert sc[k], (sid, k)
        assert len(sc["hooks"]) >= 2
        for pl in PL:
            assert sc["cta"][pl], (sid, pl)


def test_deterministic(kb):
    t = TaskSpec(raw="x", model_ids=["demo-h"], platform="wechat_mp", scenario="office")
    a = build_strategy(t, [kb.get_model("demo-h")], kb.facts("demo-h"))
    b = build_strategy(t, [kb.get_model("demo-h")], kb.facts("demo-h"))
    assert a.model_dump() == b.model_dump()
    x, _ = compose(t, a, gather(t, a, kb), None)
    y, _ = compose(t, b, gather(t, b, kb), None)
    assert x.model_dump() == y.model_dump()


def test_scenario_changes_order_hook_and_images(kb):
    seen_rank, seen_hook, seen_img = set(), set(), set()
    for sc in SC:
        t, s, ev = mk(kb, scenario=sc)
        seen_rank.add(tuple(p.label.split("｜")[0] for p in s.selling_points))
        seen_hook.add(s.hook)
        seen_img.add(tuple(tuple(x.prefer_tags) for x in s.image_slots))
    assert len(seen_rank) >= 4 and len(seen_hook) >= 6 and len(seen_img) >= 3


def test_platform_changes_structure(kb):
    structs, counts, ctas = set(), set(), set()
    for pl in PL:
        t, s, ev = mk(kb, platform=pl)
        structs.add(tuple(s.structure)); counts.add(s.image_count); ctas.add(s.cta)
    assert len(structs) == 4 and len(ctas) == 4 and len(counts) >= 3


def test_user_selling_point_overrides_and_explains(kb):
    t, s, ev = mk(kb, scenario="creator", selling_point="续航")
    assert "续航" in s.selling_points[0].label
    assert any("用户指定" in r for r in s.rationale)
    assert all(re.search(r"demo-h:", r) for r in s.rationale if r.startswith("卖点排序"))


def test_store_visit_single_and_poster_max3(kb):
    assert len(mk(kb, scenario="store_visit")[1].selling_points) == 1
    assert len(mk(kb, platform="moments")[1].selling_points) == 1
    assert len(mk(kb, platform="poster")[1].selling_points) <= 3


# ---------------- 取证 ----------------
def test_gather_trace_and_images(kb):
    t, s, ev = mk(kb, platform="xiaohongshu", scenario="creator")
    assert kb.search_calls and len(ev.trace) >= 2
    assert 8 <= len(ev.facts) <= 14
    assert all(f.model_id == "demo-h" for f in ev.facts)
    assert any(f.kind in ("unfit", "boundary") for f in ev.facts)
    ids = [i.id for i in ev.images]
    assert len(ids) == len(set(ids)) and all(i.model_id == "demo-h" for i in ev.images)
    colors = {i.color for i in ev.images if i.color}
    assert len(colors) <= 1


def test_gather_prices_only_citable_same_basis(kb):
    t, s, ev = mk(kb, want_price=True)
    assert ev.prices and {p.price_type for p in ev.prices} == {"官方商城页面价"}
    t2, s2, ev2 = mk(kb, model="demo-w", want_price=True)
    assert all(p.amount is None for p in ev2.prices)
    assert mk(kb)[2].prices == []


# ---------------- 生成 ----------------
@pytest.mark.parametrize("sc", SC)
@pytest.mark.parametrize("pl", PL)
def test_composer_all_combos(kb, sc, pl):
    t, s, ev = mk(kb, scenario=sc, platform=pl)
    art, eng = compose(t, s, ev, None)
    assert eng.writer == "composer" and eng.prompt_version == PROMPT_VERSION
    fids = {f.id for f in ev.facts}
    for b in art.blocks:
        assert all(i in fids for i in b.fact_ids)
        if b.kind in ("para", "list", "callout") and b.note not in ("scene", "limit", "poster-title") and not b.note.startswith("price") and b.text:
            assert b.fact_ids, (sc, pl, b.id, b.text[:30])
    for r in art.image_refs:
        assert r.model_id == "demo-h" and r.reason and r.position and (r.source_url or r.page_url)
    lo, hi = P.PLATFORMS[pl]["img_range"]
    assert lo <= len(art.image_refs) <= hi or len(ev.images) < lo
    assert any(b.note == "limit" for b in art.blocks)
    if pl in ("wechat_mp", "xiaohongshu", "poster"):
        assert len(art.titles) >= 3
    if pl == "poster":
        assert art.poster and len(art.poster["points"]) <= 3 and art.poster["image_id"]
    if pl == "xiaohongshu":
        assert 4 <= len(art.hashtags) <= 6
    assert not any(w in "".join(b.text for b in art.blocks) for w in ("震撼", "颠覆", "全能", "赋能", "重新定义"))
    assert not re.search(r"亲测|实测|我用了|亲身", "".join(b.text for b in art.blocks))


def test_scene_and_platform_texts_really_differ(kb):
    texts = {}
    for sc in SC:
        for pl in PL:
            t, s, ev = mk(kb, scenario=sc, platform=pl)
            art, _ = compose(t, s, ev, None)
            texts[(sc, pl)] = "".join(b.text for b in art.blocks if b.kind != "image")
    assert len(set(texts.values())) == 32
    assert len(texts[("office", "moments")]) < len(texts[("office", "wechat_mp")]) / 3


def test_constraints_travel_with_fact(kb):
    t, s, ev = mk(kb, scenario="creator")
    art, _ = compose(t, s, ev, None)
    body = "".join(b.text for b in art.blocks)
    assert "亮度与色域为典型值" in body


def test_price_written_only_when_wanted(kb):
    art, _ = compose(*mk(kb, want_price=True), None)
    assert art.price_note.count("\n") + 1 >= 1 and "金额：7999 元" in art.price_note and "官方链接" in art.price_note
    assert any(b.note.startswith("price:") for b in art.blocks)
    assert "10499" in art.price_note and "7000" not in art.price_note       # 预估到手价不混入
    art2, _ = compose(*mk(kb), None)
    assert art2.price_note == "" and not any(b.note.startswith("price") for b in art2.blocks)
    art3, _ = compose(*mk(kb, model="demo-w", want_price=True), None)
    assert "官方未公开当前金额" in art3.price_note and not re.search(r"\d{4} 元", art3.price_note)


def test_windows_vs_harmony_limit_text(kb):
    a, _ = compose(*mk(kb), None)
    w, _ = compose(*mk(kb, model="demo-w"), None)
    lim = lambda art: next(b.text for b in art.blocks if b.note == "limit")
    assert "前置条件" in lim(a)
    assert "前置条件" not in lim(w)


# ---------------- LLM ----------------
def _llm(content, status=200, seen=None):
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        if seen is not None:
            seen.append((req.headers.get("authorization"), body))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "bad"}})
        if "response_format" in body and content == "NO_RF":
            return httpx.Response(400, json={"error": {"message": "unsupported response_format"}})
        c = content if content != "NO_RF" else '```json\n{"ok": 1}\n```'
        return httpx.Response(200, json={"choices": [{"message": {"content": c}}]})
    return LLMClient("https://x.invalid/v1", "sk-SECRET-123", "m", 5, transport=httpx.MockTransport(handler))


def test_llm_json_fallback_and_no_key_leak():
    seen = []
    c = _llm("NO_RF", seen=seen)
    assert c.chat_json("s", "u") == {"ok": 1} and c.last_mode == "plain"
    assert "response_format" in seen[0][1] and "response_format" not in seen[1][1]
    assert "SECRET" not in repr(c)
    with pytest.raises(LLMError) as e:
        _llm("{}", status=401).chat_json("s", "u")
    assert "SECRET" not in str(e.value)
    assert get_llm(Settings(**_empty_settings())) is None


def _empty_settings():
    from pathlib import Path
    return dict(ima_client_id="", ima_api_key="", ima_base_url="", ima_kb_name="", kb_mode="local", kb_local_dir="",
                cache_dir=Path("."), llm_base_url="", llm_api_key="", llm_model="", llm_timeout=5.0, host="", port=1,
                runs_dir=Path("."))


def test_extract_json_variants():
    assert _extract_json('前言 {"a": {"b": "}"}} 后记') == {"a": {"b": "}"}}
    with pytest.raises(LLMError):
        _extract_json("没有 json")


def _good_llm_json(ev):
    f = [x.id for x in ev.facts if x.kind not in ("unfit", "boundary")][:2]
    lim = [x.id for x in ev.facts if x.kind in ("unfit", "boundary")][:1]
    return {"titles": ["标题一", "标题二", "标题三"], "intro": "导语",
            "blocks": [{"kind": "para", "text": "设想一个周一。", "fact_ids": [], "note": "scene"},
                       {"kind": "para", "text": "事实句。", "fact_ids": f},
                       {"kind": "callout", "text": "限制。", "fact_ids": lim, "note": "limit"}],
            "images": [{"image_id": ev.images[0].id, "after_block": "b1", "position": "导语之后", "reason": "示意"}],
            "cta": "去核对", "hashtags": [], "pending": ["待确认A"]}


def test_compose_llm_ok_and_invalid_id_falls_back(kb):
    t, s, ev = mk(kb)
    good = _good_llm_json(ev)
    art, eng = compose(t, s, ev, _llm(json.dumps(good)))
    assert eng.writer == "llm" and art.title == "标题一" and art.image_refs[0].image_id == ev.images[0].id
    bad = json.loads(json.dumps(good)); bad["blocks"][1]["fact_ids"] = ["nope:1"]
    art, eng = compose(t, s, ev, _llm(json.dumps(bad)))
    assert eng.writer == "composer" and "清单外" in eng.note and "SECRET" not in eng.note
    bad2 = json.loads(json.dumps(good)); bad2["images"][0]["image_id"] = "other.png"
    assert compose(t, s, ev, _llm(json.dumps(bad2)))[1].writer == "composer"
    art, eng = compose(t, s, ev, _llm("不是json"))
    assert eng.writer == "composer" and eng.note


def test_compose_llm_price_block_rewritten_from_records(kb):
    t, s, ev = mk(kb, want_price=True)
    good = _good_llm_json(ev)
    good["blocks"].append({"kind": "callout", "text": "只要 1 元！", "fact_ids": [], "note": "price:x"})
    art, eng = compose(t, s, ev, _llm(json.dumps(good)))
    assert eng.writer == "llm" and "1 元" not in "".join(b.text for b in art.blocks) and "7999" in art.price_note


# ---------------- 提示词 ----------------
def test_prompt_has_8_modules_and_schema():
    for h in ("角色与任务", "场景理解", "平台规则", "知识库约束", "图片规则", "生成要求", "核验规则", "合规规则"):
        assert h in SYSTEM_PROMPT
    assert "fact_ids" in SYSTEM_PROMPT and "stop_reason" in SYSTEM_PROMPT and "反套话" in SYSTEM_PROMPT
    assert all(w in SYSTEM_PROMPT for w in ("震撼", "颠覆", "全能", "赋能", "重新定义"))
    assert PROMPT_VERSION in SYSTEM_PROMPT


def test_user_message_closed_list(kb):
    t, s, ev = mk(kb)
    msg = build_user_message(t, s, ev)
    data = json.loads(msg[msg.index("{"):])
    assert {f["fact_id"] for f in data["evidence"]["facts"]} == {f.id for f in ev.facts}


# ---------------- 流水线 / 修改 / 导出 ----------------
def test_run_ok_persists_and_timeline(ctx):
    logs = []
    req = RunRequest(text="x", model_ids=["demo-h"], platform="xiaohongshu", scenario="back_to_school", want_price=True)
    res = run(req, ctx, logs.append)
    assert res.status == "ok" and res.article and res.verification and res.engine.writer == "composer"
    stages = [l.stage for l in logs]
    for st in ("parse", "clarify", "strategy", "retrieve", "extract", "compose", "verify_fact", "verify_image", "compliance", "finalize"):
        assert st in stages
    f = ctx.settings.runs_dir / f"{res.run_id}.json"
    assert f.exists()
    from app.models import RunResult
    assert RunResult.model_validate_json(f.read_text(encoding="utf-8")).run_id == res.run_id
    assert "sk-" not in f.read_text(encoding="utf-8")


def test_run_clarify_when_no_model(ctx):
    res = run(RunRequest(text="想买轻薄本"), ctx)
    assert res.status == "needs_clarification" and res.clarifications and res.article is None


def test_revise_instructions():
    t = TaskSpec(model_ids=["m"], platform="wechat_mp", scenario="office", want_price=True)
    n, ch = parse_revision("换成小红书，再短一点，删掉价格", t)
    assert n.platform == "xiaohongshu" and n.length_hint == "短" and not n.want_price
    n, ch = parse_revision("把续航换成主卖点", t)
    assert n.selling_point == "续航"
    n, ch = parse_revision("改成开学季", t)
    assert n.scenario == "back_to_school"
    n, ch = parse_revision("删掉核对清单", t)
    assert "drop:checklist" in n.extras
    n, ch = parse_revision("加一节限制说明", t)
    assert "add:limit" in n.extras


def test_revise_chain(ctx):
    r1 = run(RunRequest(text="x", model_ids=["demo-h"], platform="wechat_mp", scenario="office", want_price=True), ctx)
    r2 = revise(ReviseRequest(run_id=r1.run_id, instruction="换成朋友圈，删掉价格"), r1, ctx)
    assert r2.parent_run_id == r1.run_id and r2.task.platform == "moments" and not r2.task.want_price
    assert r2.article.price_note == "" and "朋友圈" in r2.revision_note
    r3 = revise(ReviseRequest(run_id=r1.run_id, instruction="把AI换成主卖点"), r1, ctx)
    assert "AI" in r3.strategy.selling_points[0].label


@pytest.mark.parametrize("fmt", ["md", "txt", "html", "json", "docx"])
def test_export_formats(ctx, fmt):
    r = run(RunRequest(text="x", model_ids=["demo-h"], platform="wechat_mp", scenario="office", want_price=True), ctx)
    data, mime, name = export(r, fmt, ctx.kb)
    assert data and name.endswith("." + fmt)
    if fmt in ("md", "txt", "html"):
        s = data.decode("utf-8")
        for k in ("场景判断", "知识库依据", "图文软文", "核验结果"):
            assert k in s
    if fmt == "html":
        assert "data:image/png;base64," in s and "<script" not in s
    if fmt == "docx":
        assert data[:2] == b"PK"


def test_export_unsupported(ctx):
    r = run(RunRequest(text="x", model_ids=["demo-h"], platform="moments", scenario="office"), ctx)
    with pytest.raises(ValueError):
        export(r, "png", ctx.kb)
