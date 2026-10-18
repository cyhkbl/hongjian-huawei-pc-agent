"""Local-mirror parsing and matching tests on the invented kb_mini fixture."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.config import get_settings
from app.kb import get_kb
from app.kb.aliases import resolve_model
from app.kb.base import KnowledgeBase
from app.kb.indexer import parse_spec
from app.kb.vfs import LocalFS

FIXTURE = Path(__file__).parent / "fixtures" / "kb_mini"


@pytest.fixture(scope="module")
def kb():
    s = dataclasses.replace(get_settings(), kb_mode="local", kb_local_dir=str(FIXTURE),
                            ima_client_id="", ima_api_key="")
    return get_kb(s)


def test_protocol_and_status(kb):
    assert isinstance(kb, KnowledgeBase)
    st = kb.status()
    assert st.mode == "local_mirror" and st.connected
    assert (st.models, st.images, st.prices) == (2, 4, 5)
    assert st.snapshot_date == "2026-10-17"


def test_models_and_ids(kb):
    assert [m.model_id for m in kb.models()] == ["pro-hm", "pros-hm"]
    assert kb.get_model("pros-hm").confusable_with == ["pro-hm"]
    ids = [f.id for m in ("pro-hm", "pros-hm") for f in kb.facts(m)]
    assert len(ids) == len(set(ids))
    assert kb.get_fact(ids[0]).id == ids[0]


def test_cards_split_and_expanded_ignored(kb):
    cards = [f for f in kb.facts("pros-hm") if f.id.startswith("pros-hm:card01")]
    kinds = {f.kind for f in cards}
    assert {"card", "fit", "unfit", "boundary"} == kinds
    card = [f for f in cards if f.kind == "card"]
    assert len(card) == 2 and all(f.constraints == ["示例限定：以实际销售版本为准。"] for f in card)
    assert not any("必须被忽略" in f.text for f in kb.facts("pros-hm"))
    assert all(f.source_urls == ["https://example.invalid/matebook-pro-s/"] for f in cards)


def test_spec_parse_and_noise(kb):
    specs = {f.text: f for f in kb.facts("pro-hm", kinds=["spec"])}
    assert "屏幕尺寸：14.0 英寸" in specs and "刷新率：120 Hz" in specs
    assert "电池容量：50 Wh（额定容量）" in specs
    w = next(f for f in specs.values() if f.text.startswith("重量"))
    assert w.constraints == ["实际重量依配置不同可能有所差异。"]
    assert not any("即将离开" in t or "继续访问" in t for t in specs)
    iface = next(f for f in specs.values() if f.text.startswith("接口"))
    assert iface.category == "connect" and "ports" in iface.tags


def test_selling(kb):
    sell = [f for f in kb.facts("pros-hm") if f.id.startswith("pros-hm:sell")]
    assert {f.kind for f in sell} == {"selling", "boundary"}
    concl = [f for f in sell if f.kind == "selling" and "轻薄本" in f.text][0]
    assert concl.constraints == ["重量依配置而异。"]


def test_images_and_color(kb):
    ims = kb.images("pros-hm")
    assert len(ims) == 2 and all("Pro S" in i.kb_path for i in ims)
    assert {i.model_id for i in kb.images("pro-hm")}.isdisjoint({"pros-hm"})
    assert ims[0].color == "" and any("Pro S" in i.caption for i in ims)
    data, mime = kb.image_bytes(ims[0].id)
    assert mime == "image/png" and data[:4] == b"\x89PNG"
    with pytest.raises(KeyError):
        kb.image_bytes("missing.png")


def test_missing_image_file_is_skipped_and_reported(tmp_path):
    import shutil
    dst = tmp_path / "kb"
    shutil.copytree(FIXTURE, dst)
    (dst / "P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro/images/hwpc_matebook-pro_屏幕_02.png").unlink()
    s = dataclasses.replace(get_settings(), kb_mode="local", kb_local_dir=str(dst), ima_client_id="", ima_api_key="")
    kb2 = get_kb(s)
    assert len(kb2.images("pro-hm")) == 1
    assert any("hwpc_matebook-pro_屏幕_02.png" in a for a in kb2._idx.audit)
    assert "缺失" in kb2.status().detail or "没有可读文件" in " ".join(kb2._idx.notes)


def test_prices(kb):
    assert [p.amount for p in kb.prices("pro-hm")] == [5000.0, 4900.0]
    assert kb.get_model("pro-hm").has_public_price
    assert not kb.get_model("pros-hm").has_public_price      # 只有"官网参考起价"不算可引用金额
    assert all(p.amount is None or p.price_type == "官网参考起价" for p in kb.prices("pros-hm"))
    assert any(p.model_id is None for p in kb._idx.prices)


def test_find_models(kb):
    r = kb.find_models("给 Pro S 写一篇")
    assert [m.model_id for m, _, _ in r] == ["pros-hm"]
    r = kb.find_models("MateBook Pro 开学季")
    assert [m.model_id for m, _, _ in r] == ["pro-hm"]
    r = kb.find_models("Pro S 和 Pro 比较")
    assert [m.model_id for m, _, _ in r] == ["pros-hm", "pro-hm"]
    assert kb.find_models("") == [] and kb.find_models("轻薄本") == []


def test_search_and_trace(kb):
    kb.drain_trace()
    hits = kb.search("刷新率", limit=3)
    assert hits and hits[0].path
    tr = kb.drain_trace()
    assert len(tr) == 1 and tr[0].step == "local_index" and tr[0].origin == "local_mirror" and tr[0].count == len(hits)
    assert kb.search("刷新率", model_id="pros-hm") and all(
        h.model_id == "pros-hm" for h in kb.search("刷新率", model_id="pros-hm"))
    assert kb.search("zzzzzzqq") == []


def test_resolve_model_names():
    cases = {
        "HUAWEI MateBook 14（鸿蒙版）": "mb14-hm", "HUAWEI MateBook 14 酷睿 Ultra": "mb14-ultra",
        "HUAWEI MateBook D 16 SE 版 2024": "d16se", "HUAWEI MateBook D 16 2024": "d16",
        "HUAWEI MateBook D 14 2024": "d14", "HUAWEI MateBook GT 14": "gt14",
        "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版": "xpro", "HUAWEI MateBook Pro（鸿蒙版）": "pro-hm",
        "HUAWEI MateBook Pro S": "pros-hm", "HUAWEI MateBook Fold 非凡大师": "fold",
        "HUAWEI MateBook Fold 企业版": None, "HUAWEI MateDock 2": None, "华为擎云 HM740": None,
    }
    for k, v in cases.items():
        assert resolve_model(k) == v, k


def test_parse_spec_multivalue():
    t = "# X - 产品事实\n\n## 来源\n\n- https://a.b/c\n\n## 官方规格摘录\n\n## 处理器\n\nCPU A\n\nCPU B\n\n## 屏幕\n\n亮度\n\n标准版：\n\n300 nits\n\n柔光版：\n\n450 尼特\n"
    items, urls = parse_spec(t)
    d = {i["label"]: i["text"] for i in items}
    assert d["处理器"] == "处理器：CPU A；CPU B"
    assert d["亮度"] == "亮度：标准版：300 nits；柔光版：450 尼特"
    assert urls == ["https://a.b/c"]


def test_localfs_rejects_traversal_and_missing(tmp_path):
    fs = LocalFS(FIXTURE)
    with pytest.raises(ValueError):
        fs.read_bytes("../x")
    with pytest.raises(FileNotFoundError):
        LocalFS(tmp_path / "nope")
