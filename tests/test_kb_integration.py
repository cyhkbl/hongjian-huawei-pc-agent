"""Integration test against the organiser's KB copy. Runs only when KB_LOCAL_DIR is set
and points at a real directory (the KB is never shipped in the repo)."""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from app.config import get_settings

_DIR = os.environ.get("KB_LOCAL_DIR", "").strip()
pytestmark = pytest.mark.skipif(not (_DIR and Path(_DIR).is_dir()), reason="KB_LOCAL_DIR 未设置")

IDS = ["pro-hm", "pros-hm", "mb14-hm", "fold", "mb14-ultra", "d14", "d16", "d16se", "gt14", "xpro"]


@pytest.fixture(scope="module")
def kb():
    from app.kb import get_kb
    s = dataclasses.replace(get_settings(), kb_mode="local", kb_local_dir=_DIR,
                            ima_client_id="", ima_api_key="")
    return get_kb(s)


def test_protocol_and_status(kb):
    from app.kb.base import KnowledgeBase
    assert isinstance(kb, KnowledgeBase)
    st = kb.status()
    assert st.mode == "local_mirror" and st.connected
    assert st.models == 10 and st.facts > 300 and st.images >= 60 and st.prices == 141
    assert st.snapshot_date == "2026-10-17"
    assert not st.ima_configured and st.api_key_hint == ""


def test_ten_models(kb):
    assert [m.model_id for m in kb.models()] == IDS
    assert kb.get_model("pros-hm").name == "HUAWEI MateBook Pro S"
    assert kb.get_model("mb14-hm").name == "HUAWEI MateBook 14（鸿蒙版）"
    assert kb.get_model("mb14-ultra").name == "HUAWEI MateBook 14 酷睿 Ultra"
    assert "mb14-ultra" in kb.get_model("mb14-hm").confusable_with
    assert "d16se" in kb.get_model("d16").confusable_with
    assert all(m.official_urls for m in kb.models())


def test_facts_shape(kb):
    ids = set()
    for m in IDS:
        fs = kb.facts(m)
        assert len(fs) > 50
        kinds = {f.kind for f in fs}
        assert {"spec", "card", "selling"} <= kinds
        for f in fs:
            assert f.id.startswith(m + ":") and f.id not in ids
            ids.add(f.id)
            assert f.source_path and f.source_title and f.verified_date == "2026-10-17"
            assert "即将离开" not in f.text and "继续访问" not in f.text
            assert f.model_id == m
    assert len(ids) > 300
    assert kb.get_fact(next(iter(ids))) is not None


def test_spec_line_and_constraints(kb):
    texts = {f.text: f for f in kb.facts("pros-hm", kinds=["spec"])}
    assert "屏幕尺寸：14.2 英寸" in texts
    peak = next(f for f in texts.values() if f.text.startswith("峰值亮度"))
    assert peak.constraints, "亮度脚注应作为 constraints"
    card = [f for f in kb.facts("pros-hm", kinds=["card"]) if f.id.startswith("pros-hm:card02")]
    assert card and all(f.constraints for f in card)


def test_images(kb):
    total = 0
    for m in IDS:
        for im in kb.images(m):
            total += 1
            data, mime = kb.image_bytes(im.id)
            assert data and mime.startswith("image/")
            assert im.source_url and im.page_url and im.kb_path and im.caption
            assert im.width > 0 and im.height > 0
    assert total >= 60
    # Pro S pictures must never hang under Pro
    pro = {i.id for i in kb.images("pro-hm")}
    pros = {i.id for i in kb.images("pros-hm")}
    assert pros and pro and not (pro & pros)
    assert all("pro-s" in i or "pros" in i for i in pros)
    assert all("matebook-pro-s" not in i for i in pro)
    assert all(i.kb_path.count("MateBook Pro S") for i in kb.images("pros-hm"))
    # mall pictures belong to MateBook 14 鸿蒙版 only
    mall = [i for m in IDS for i in kb.images(m) if i.kind == "mall"]
    assert mall and {i.model_id for i in mall} == {"mb14-hm"}
    assert any(i.color == "原野绿" for i in kb.images("mb14-hm"))
    assert any(i.color == "仲夏紫" for i in kb.images("pros-hm"))
    with pytest.raises(KeyError):
        kb.image_bytes("nope.png")


def test_find_models(kb):
    def ids(t):
        return [(m.model_id, s) for m, s, _ in kb.find_models(t)]

    r = ids("MateBook 14")
    assert {m for m, _ in r} == {"mb14-hm", "mb14-ultra"} and len({s for _, s in r}) == 1 and r[0][1] < 0.7
    assert ids("给 D 16 SE 写一篇")[0][0] == "d16se"
    assert [m for m, _ in ids("D 16 SE")] == ["d16se"]
    assert ids("Pro S 开学季")[0][0] == "pros-hm"
    assert [m for m, _ in ids("MateBook Pro S")] == ["pros-hm"]
    assert ids("MateBook Pro 鸿蒙版")[0][0] == "pro-hm"
    assert ids("折叠本")[0][0] == "fold" and ids("非凡大师")[0][0] == "fold"
    assert ids("酷睿Ultra版14")[0][0] == "mb14-ultra"
    assert ids("鸿蒙版14")[0][0] == "mb14-hm"
    assert ids("X Pro")[0][0] == "xpro" and ids("D14")[0][0] == "d14"
    assert ids("MateBook GT 14")[0][0] == "gt14"
    assert ids("想买轻薄本") == []


def test_prices(kb):
    allp = [p for m in IDS for p in kb.prices(m)]
    assert len(allp) + sum(1 for p in kb._idx.prices if p.model_id is None) == 141
    assert any(p.amount for p in kb.prices("mb14-hm"))
    assert kb.get_model("mb14-hm").has_public_price
    assert all(p.amount is None for p in kb.prices("d16") if p.price_type != "官网参考起价")
    assert not kb.get_model("d16").has_public_price
    assert not kb.get_model("d16se").has_public_price
    assert kb.get_model("pros-hm").has_public_price
    assert all(p.model_id is None for p in kb._idx.prices if "擎云" in p.product_name)


def test_search_and_trace(kb):
    kb.drain_trace()
    hits = kb.search("续航 快充", model_id="pros-hm", limit=4)
    assert hits and all(h.model_id == "pros-hm" for h in hits)
    tr = kb.drain_trace()
    assert tr and tr[0].step == "local_index" and tr[0].origin == "local_mirror" and tr[0].code is None
    assert kb.drain_trace() == []
