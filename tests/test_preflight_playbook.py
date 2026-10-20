"""预演与门店手册的单元测试：误报与漏报都要覆盖。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KB_MODE", "local")
os.environ.setdefault("KB_LOCAL_DIR", r"D:\DeepSeekWorkSpace\hackathlon\hongjian\kb_snapshot")

import pytest  # noqa: E402

from app.agent.playbook import build_playbook  # noqa: E402
from app.agent.preflight import build_preflight  # noqa: E402


def _run(blocks, title="x", price_note="", image_refs=None, selling_points=None):
    return {
        "task": {"platform": "xiaohongshu", "model_ids": ["pro-hm"], "scenario": "back_to_school"},
        "strategy": {"hook": "背包里的一天：开学第一周", "tone": "口语",
                     "selling_points": selling_points or []},
        "article": {"platform": "xiaohongshu", "title": title, "blocks": blocks,
                    "image_refs": image_refs or [], "price_note": price_note, "cta": "评论区见"},
    }


def _para(text):
    return {"kind": "para", "text": text, "fact_ids": []}


GOOD_PRICE = "- 口径：官方商城页面价；SKU：24GB/512GB；金额：6599 元；核验时间：2026-10-17 14:50；条件：无；https://x"


# ---------------------------------------------------------------- preflight
@pytest.mark.parametrize("text,label", [
    ("这是全网最轻的笔记本，性能第一。", "绝对化用语"),
    ("我们保证三年不卡，一定流畅。", "承诺性表述"),
    ("这个优惠永久有效，终身保修。", "时效承诺"),
])
def test_preflight_catches_risky(text, label):
    pf = build_preflight(_run([_para(text)]), None)
    assert any(i.kind == "risky" and i.where == "正文" for i in pf.items), pf.items
    assert not pf.ready_to_send


def test_preflight_catches_risky_title():
    pf = build_preflight(_run([_para("正常内容。")], title="史上最强办公本"), None)
    assert any(i.kind == "risky" and i.where == "标题" for i in pf.items)


def test_preflight_price_without_source():
    pf = build_preflight(_run([_para("现在只要 5899 元，很划算。")], price_note=""), None)
    assert any(i.where == "价格" for i in pf.items)
    assert not pf.ready_to_send


def test_preflight_price_missing_fields():
    pf = build_preflight(_run([_para("价格见下。")], price_note="- 口径：官方商城页面价；金额：5899 元"), None)
    item = next(i for i in pf.items if i.where == "价格")
    assert "SKU" in item.ask or "核验时间" in item.ask


def test_preflight_asks_about_unqualified_numbers():
    pf = build_preflight(_run([_para("机身宽 310.0 mm，重量 970 g。")],
                              price_note=GOOD_PRICE), None)
    asks = [i for i in pf.items if i.kind == "ask"]
    assert asks, "有数字没限定时应提醒会被追问"
    assert any("310.0 mm" in i.ask for i in asks)


def test_preflight_clean_article_passes():
    pf = build_preflight(_run([_para("官方口径的机身重量约 970 g，具体以官方页面为准。")],
                              price_note=GOOD_PRICE), None)
    assert pf.ready_to_send, pf.items
    assert pf.verdict == "ok"


def test_preflight_no_false_positive_on_negation():
    """「不能直接换算所有场景续航」是否定用法，不该判为全称判断。"""
    pf = build_preflight(_run([_para("电池容量不能直接换算所有场景续航。")],
                              price_note=GOOD_PRICE), None)
    assert not [i for i in pf.items if i.kind == "risky"], pf.items


def test_preflight_no_false_positive_on_listing():
    """「上面这些参数和说法都带使用条件」是说明性用法。"""
    pf = build_preflight(_run([_para("上面这些参数和说法都带使用条件，发布前请逐条对照。")],
                              price_note=GOOD_PRICE), None)
    assert not [i for i in pf.items if i.kind == "risky"], pf.items


def test_preflight_image_without_source():
    pf = build_preflight(_run(
        [_para("见图。")], price_note=GOOD_PRICE,
        image_refs=[{"image_id": "x.png", "source_url": "", "page_url": ""}]), None)
    assert any(i.where == "配图" for i in pf.items)


def test_preflight_dedupes_repeated_numbers():
    pf = build_preflight(_run([_para("970 g 与 70 Wh 配合；整机 970 g，电池 70 Wh。")],
                              price_note=GOOD_PRICE), None)
    nums = [i for i in pf.items if "970 g" in i.ask]
    assert len(nums) == 1, "同一数字只追问一次"


# ---------------------------------------------------------------- playbook
def test_playbook_has_say_do_care():
    sp = [{"label": "轻薄便携｜机身宽310.0 mm", "rank": 1, "fact_ids": ["f1"], "why": "w"}]
    pb = build_playbook(_run([_para("正文。")], selling_points=sp), None)
    assert pb.steps, "应有步骤"
    for s in pb.steps:
        assert s.say and s.do and s.care, s


def test_playbook_includes_limit_step():
    sp = [{"label": "轻薄便携｜x", "rank": 1, "fact_ids": [], "why": "w"}]
    run = _run([_para("正文。")], selling_points=sp)
    run["strategy"]["rationale"] = ["场景禁忌：不写教育优惠、国补、立减等未出现在 KB 的权益。"]
    pb = build_playbook(run, None)
    assert any(s.label == "必须如实说" for s in pb.steps)


def test_playbook_price_step_when_price_present():
    sp = [{"label": "轻薄便携｜x", "rank": 1, "fact_ids": [], "why": "w"}]
    pb = build_playbook(_run([_para("正文。")], selling_points=sp, price_note=GOOD_PRICE), None)
    assert any(s.label == "价格口径" for s in pb.steps)


def test_playbook_tag_matching_prefers_scene_words():
    """「学习场景」应命中 study，而不是被 AI 词典抢走。"""
    sp = [{"label": "学习场景｜特色应用包括小艺慧记", "rank": 1, "fact_ids": [], "why": "w"}]
    pb = build_playbook(_run([_para("正文。")], selling_points=sp), None)
    step = pb.steps[0]
    assert "软件" in step.do, f"应给出学习场景的动作，实际：{step.do}"


def test_playbook_platform_note():
    sp = [{"label": "轻薄便携｜x", "rank": 1, "fact_ids": [], "why": "w"}]
    pb = build_playbook(_run([_para("正文。")], selling_points=sp), None)
    assert pb.platform_note, "应给出该渠道的接待提示"
