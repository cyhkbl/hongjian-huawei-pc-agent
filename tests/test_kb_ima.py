"""ima_client / ImaFS / store degrade logic, tested against an in-process fake ima server
(httpx.MockTransport). The fake serves the invented kb_mini fixture."""
from __future__ import annotations

import dataclasses
import json
import mimetypes
from pathlib import Path
from typing import Optional

import httpx
import pytest

from app.config import get_settings
from app.kb.ima_client import ImaClient, ImaError, pick_kb
from app.kb.store import KB
from app.kb.vfs import ImaFS

FIXTURE = Path(__file__).parent / "fixtures" / "kb_mini"
KB_NAME = "任德耀新建华为PC知识库"
CID, KEY = "cid_0123456789abcdef", "sk_secret_abcdefghijklmnop"
KB_ID = "kbid_SECRET_1234"
BASE = "https://ima.test"
DL = "https://cos.test/dl/"


class FakeIma:
    """Minimal ima OpenAPI. ``tree`` = {path: bytes | dict(children)}"""

    def __init__(self, tree: dict, *, kb_fields: str = "kb", page: int = 3, search_empty: bool = False,
                 rate_limit_first: int = 0, search_fail_code: Optional[int] = None,
                 deny: bool = False, folder_style: str = "folder_info"):
        self.kb_fields = kb_fields
        self.page = page
        self.search_empty = search_empty
        self.rate_limit_left = rate_limit_first
        self.search_fail_code = search_fail_code
        self.deny = deny
        self.folder_style = folder_style
        self.calls: list[tuple[str, dict, dict]] = []
        self.downloads: list[tuple[str, dict]] = []
        self.media: dict[str, bytes] = {}
        self.folders: dict[str, list[dict]] = {KB_ID: []}
        self._n = 0
        # 真实 ima 的根列表只有一项：与知识库同名的包装文件夹（media_type=99），
        # 真正的根 folder_id 是这个条目的 media_id。fixture 照这个结构搭。
        self.root_wrapper = "folder_root_ID"
        self.folders[self.root_wrapper] = []
        self.folders[KB_ID].append({"media_id": self.root_wrapper, "title": KB_NAME,
                                   "parent_folder_id": "root", "media_type": 99})
        self._build(tree, self.root_wrapper)

    # ---- tree
    def _new(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n:04d}_ID"

    def _build(self, node: dict, folder_id: str) -> None:
        for name, val in node.items():
            if isinstance(val, dict):
                fid = self._new("fld")
                self.folders[fid] = []
                item = {"media_id": fid, "title": name, "parent_folder_id": folder_id}
                if self.folder_style == "folder_info":
                    item["folder_info"] = {"folder_id": fid, "name": name, "file_number": 1, "folder_number": 0}
                self.folders[folder_id].append(item)
                self._build(val, fid)
            else:
                mid = self._new("med")
                self.media[mid] = val
                self.folders[folder_id].append({"media_id": mid, "title": name, "parent_folder_id": folder_id,
                                                "media_type": 7 if name.endswith((".md", ".csv")) else 9})

    # ---- transport
    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith(DL):
            self.downloads.append((url, dict(req.headers)))
            mid = url[len(DL):]
            if req.headers.get("x-dl-token") != "tok":
                return httpx.Response(403, text="no token")
            return httpx.Response(200, content=self.media[mid])
        assert url.startswith(BASE + "/openapi/wiki/v1/"), url
        api = url.rsplit("/", 1)[1]
        body = json.loads(req.content.decode("utf-8"))
        self.calls.append((api, body, dict(req.headers)))
        h = req.headers
        if h.get("ima-openapi-clientid") != CID or h.get("ima-openapi-apikey") != KEY:
            return self._j(110030, "凭证错误")
        if self.rate_limit_left > 0:
            self.rate_limit_left -= 1
            return self._j(110021, "请求频控")
        if self.deny:
            return self._j(110030, "无权限访问该知识库")
        fn = getattr(self, "api_" + api, None)
        if fn is None:
            return self._j(110012, "接口无效")
        return fn(body)

    @staticmethod
    def _j(code: int, msg: str = "success", data: Optional[dict] = None) -> httpx.Response:
        return httpx.Response(200, json={"code": code, "msg": msg, "data": data or {}})

    def api_search_knowledge_base(self, b: dict) -> httpx.Response:
        if self.search_fail_code:
            return self._j(self.search_fail_code, "boom")
        if self.search_empty:
            return self._j(0, data={"info_list": [], "is_end": True, "next_cursor": ""})
        rows = [{"kb_id": "other_kb", "kb_name": "别的库"}, {"kb_id": KB_ID, "kb_name": KB_NAME}] \
            if self.kb_fields == "kb" else [{"id": "other_kb", "name": "别的库"}, {"id": KB_ID, "name": KB_NAME}]
        if b["cursor"] == "":
            return self._j(0, data={"info_list": rows[:1], "is_end": False, "next_cursor": "c2"})
        return self._j(0, data={"info_list": rows[1:], "is_end": True, "next_cursor": ""})

    def api_get_addable_knowledge_base_list(self, b: dict) -> httpx.Response:
        return self._j(0, data={"addable_knowledge_base_list": [{"id": KB_ID, "name": KB_NAME}],
                                "is_end": True, "next_cursor": ""})

    def api_get_knowledge_list(self, b: dict) -> httpx.Response:
        assert 1 <= b["limit"] <= 50
        assert b["knowledge_base_id"] == KB_ID
        items = self.folders[b.get("folder_id") or KB_ID]
        start = int(b["cursor"] or 0)
        chunk = items[start:start + self.page]
        end = start + self.page >= len(items)
        return self._j(0, data={"knowledge_list": chunk, "is_end": end,
                                "next_cursor": "" if end else str(start + self.page)})

    def api_get_media_info(self, b: dict) -> httpx.Response:
        mid = b["media_id"]
        if mid not in self.media:
            return self._j(110001, "参数非法")
        return self._j(0, data={"media_type": 7, "url_info": {"url": DL + mid, "headers": {"x-dl-token": "tok"}}})

    def api_search_knowledge(self, b: dict) -> httpx.Response:
        files = [(m, it) for items in self.folders.values() for it in items for m in [it["media_id"]] if m in self.media]
        q = b["query"]
        hit = [{"media_id": m, "title": it["title"], "parent_folder_id": it["parent_folder_id"],
                "highlight_content": f"…{q}…"} for m, it in files if it["title"].endswith(".md")][:2]
        return self._j(0, data={"info_list": hit, "is_end": True, "next_cursor": ""})


def fixture_tree() -> dict:
    root: dict = {}
    for p in sorted(FIXTURE.rglob("*")):
        if p.is_file():
            node = root
            parts = p.relative_to(FIXTURE).parts
            for d in parts[:-1]:
                node = node.setdefault(d, {})
            node[parts[-1]] = p.read_bytes()
    return root


def article_tree() -> dict:
    art = """# HUAWEI MateBook Pro - 示例文章

> 抓取日期：2026-10-17

## 屏幕
- 屏幕为 14 英寸示例 OLED，刷新率 120 Hz。
- 支持十点触控。

## 注意事项
- 实际表现以销售版本为准。

## 来源
- https://example.invalid/pro/
"""
    return {"P1-产品参数库": {"01-鸿蒙电脑": {"HUAWEI MateBook Pro": {"article.md": art.encode("utf-8")},
                                           "HUAWEI MateBook Pro S": {"article.md": art.replace("MateBook Pro", "MateBook Pro S").encode("utf-8")}}}}


def settings(**kw):
    base = dataclasses.replace(get_settings(), ima_client_id=CID, ima_api_key=KEY, ima_base_url=BASE,
                               ima_kb_name=KB_NAME, kb_mode="auto", kb_local_dir="")
    return dataclasses.replace(base, **kw)


def make_client(fake: FakeIma, **kw) -> ImaClient:
    return ImaClient(CID, KEY, BASE, transport=httpx.MockTransport(fake.handler), sleep=lambda s: None, **kw)


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fields", ["kb", "id"])
def test_search_kb_both_field_styles_and_paging(fields):
    fake = FakeIma({}, kb_fields=fields)
    c = make_client(fake)
    kbs = c.search_knowledge_base(KB_NAME)
    assert [k["id"] for k in kbs] == ["other_kb", KB_ID]       # followed next_cursor
    assert pick_kb(kbs, KB_NAME)["id"] == KB_ID
    assert fake.calls[0][1] == {"query": KB_NAME, "cursor": "", "limit": 20}
    assert fake.calls[1][1]["cursor"] == "c2"


def test_headers_sent_and_codes():
    fake = FakeIma({})
    c = make_client(fake)
    c.search_knowledge_base("x")
    h = fake.calls[0][2]
    assert h["ima-openapi-clientid"] == CID and h["ima-openapi-apikey"] == KEY
    assert h["content-type"].startswith("application/json")
    bad = ImaClient("bad", "bad", BASE, transport=httpx.MockTransport(fake.handler), sleep=lambda s: None)
    with pytest.raises(ImaError) as ei:
        bad.search_knowledge_base("x")
    assert ei.value.code == 110030 and "凭证错误" in ei.value.msg


def test_rate_limit_backoff_then_success_and_exhaustion():
    sleeps: list[float] = []
    fake = FakeIma({}, rate_limit_first=2)
    c = ImaClient(CID, KEY, BASE, transport=httpx.MockTransport(fake.handler), sleep=sleeps.append,
                  backoff=1.0, min_interval=0.0)
    assert c.search_knowledge_base("x")
    # 110021 频控用线性等待（backoff*2*(n+1)），间隔为 [2.0, 4.0]
    assert sleeps == [2.0, 4.0]
    fake2 = FakeIma({}, rate_limit_first=99)
    c2 = ImaClient(CID, KEY, BASE, transport=httpx.MockTransport(fake2.handler), sleep=lambda s: None,
                   max_retries=2, min_interval=0.0)
    with pytest.raises(ImaError) as ei:
        c2.search_knowledge_base("x")
    assert ei.value.code == 110021 and "频控" in ei.value.msg
    assert len(fake2.calls) == 3


def test_network_error_wrapped():
    def boom(req):
        raise httpx.ConnectError("down")
    c = ImaClient(CID, KEY, BASE, transport=httpx.MockTransport(boom), sleep=lambda s: None, max_retries=1)
    with pytest.raises(ImaError) as ei:
        c.search_knowledge_base("x")
    assert ei.value.code == -100 and "无法连接" in ei.value.msg


def test_trace_is_sanitized():
    fake = FakeIma(fixture_tree())
    c = make_client(fake)
    c.search_knowledge_base(KB_NAME)
    fs = ImaFS(c, KB_ID, Path(__file__).parent / ".tmp_cache_unused", KB_NAME)
    try:
        fs.list_dir("")
        mid = next(m for items in fake.folders.values() for it in items for m in [it["media_id"]] if m in fake.media)
        c.get_media_info(mid, title="某文件.md")
        blob = json.dumps([e.model_dump() for e in c.history], ensure_ascii=False) + json.dumps(c.last_response)
        for secret in (CID, KEY, KB_ID, mid, "fld_0001_ID"):
            assert secret not in blob
        steps = {e.step for e in c.history}
        assert {"search_knowledge_base", "get_knowledge_list", "get_media_info"} <= steps
        assert all(e.origin == "ima" and e.code == 0 for e in c.history)
        assert c.last_response["endpoint"].endswith("get_media_info")
    finally:
        import shutil
        shutil.rmtree(Path(__file__).parent / ".tmp_cache_unused", ignore_errors=True)


# --------------------------------------------------------------------------
# ImaFS
# --------------------------------------------------------------------------
@pytest.mark.parametrize("style", ["folder_info", "guess"])
def test_imafs_walk_read_cache(tmp_path, style):
    fake = FakeIma(fixture_tree(), folder_style=style, page=2)
    c = make_client(fake)
    fs = ImaFS(c, KB_ID, tmp_path, KB_NAME)
    assert [e.name for e in fs.list_dir("") if e.is_dir] == ["P1-产品参数库"]
    names = [e.name for e in fs.list_dir("P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro")]
    assert {"产品事实.md", "卖点与限制.md", "images", "图片索引.csv"} <= set(names)       # paging joined
    assert fs.is_dir("P1-产品参数库/01-鸿蒙电脑") and not fs.exists("P1-产品参数库/nope")
    p = "P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook Pro/产品事实.md"
    t = fs.read_text(p)
    assert "示例" in t
    n = len(fake.downloads)
    assert fake.downloads[0][1]["x-dl-token"] == "tok"                  # headers forwarded
    assert fs.read_text(p) == t and len(fake.downloads) == n            # disk cache
    fs2 = ImaFS(make_client(fake), KB_ID, tmp_path, KB_NAME)             # fresh process, same cache dir
    assert fs2.read_text(p) == t and len(fake.downloads) == n
    with pytest.raises(FileNotFoundError):
        fs.read_bytes("P1-产品参数库/不存在.md")


# --------------------------------------------------------------------------
# KB in ima mode
# --------------------------------------------------------------------------
def test_ima_mode_end_to_end(tmp_path):
    fake = FakeIma(fixture_tree(), page=4)
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima"), ima_transport=httpx.MockTransport(fake.handler),
            sleep=lambda s: None)
    st = kb.status()
    assert st.mode == "ima" and st.connected and st.kb_name == KB_NAME
    assert "已连接 ima 共享知识库" in st.detail and KB_NAME in st.detail
    assert st.models == 2 and st.facts > 10 and st.images == 4 and st.prices == 5
    assert st.account_hint == "cid_****ef" and st.api_key_hint == "****op"
    assert KEY not in st.model_dump_json() and CID not in st.model_dump_json() and KB_ID not in st.model_dump_json()
    assert st.last_response["code"] == 0 and st.last_response["endpoint"]
    assert all(e.origin == "ima" for e in st.trace)
    f = kb.facts("pros-hm")[0]
    assert f.origin == "ima"
    # images via get_media_info (+ cache)
    img = kb.images("pros-hm")[0]
    data, mime = kb.image_bytes(img.id)
    assert mime == "image/png" and data[:4] == b"\x89PNG"
    kb.drain_trace()
    # search really calls search_knowledge
    hits = kb.search("屏幕", model_id=None, limit=5)
    assert hits and any(c[0] == "search_knowledge" for c in fake.calls)
    tr = kb.drain_trace()
    assert any(t.step == "search_knowledge" and t.origin == "ima" and t.code == 0 for t in tr)
    blob = json.dumps([t.model_dump() for t in tr + kb.status().trace], ensure_ascii=False)
    for secret in (CID, KEY, KB_ID):
        assert secret not in blob
    assert "med_0" not in blob and "fld_0" not in blob


def test_search_empty_falls_back_to_browse_for_kb(tmp_path):
    fake = FakeIma(fixture_tree(), search_empty=True)
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima"), ima_transport=httpx.MockTransport(fake.handler),
            sleep=lambda s: None)
    st = kb.status()
    assert st.mode == "ima" and st.connected
    apis = [c[0] for c in fake.calls]
    assert "search_knowledge_base" in apis and "get_addable_knowledge_base_list" in apis


def test_search_returning_nothing_falls_back_to_browse(tmp_path):
    fake = FakeIma(fixture_tree())
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima"), ima_transport=httpx.MockTransport(fake.handler),
            sleep=lambda s: None)
    fake.api_search_knowledge = lambda b: fake._j(0, data={"info_list": [], "is_end": True, "next_cursor": ""})
    kb.drain_trace()
    hits = kb.search("屏幕 刷新率", model_id="pros-hm", limit=3)
    assert hits and all(h.model_id == "pros-hm" for h in hits)
    steps = [t.step for t in kb.drain_trace()]
    assert steps == ["search_knowledge", "browse_fallback"]


def test_rate_limited_during_init_still_connects(tmp_path):
    fake = FakeIma(fixture_tree(), rate_limit_first=2)
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima"), ima_transport=httpx.MockTransport(fake.handler),
            sleep=lambda s: None)
    assert kb.status().connected


def test_no_permission_degrades_to_local(tmp_path):
    fake = FakeIma(fixture_tree(), deny=True)
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima", kb_local_dir=str(FIXTURE)),
            ima_transport=httpx.MockTransport(fake.handler), sleep=lambda s: None)
    st = kb.status()
    assert st.mode == "local_mirror" and st.connected is False
    assert "ima 不可达" in st.detail and "已降级为本地镜像" in st.detail and "110030" in st.detail
    assert st.ima_configured and st.models == 2 and st.facts > 10
    assert st.last_response["code"] == 110030
    assert all(f.origin == "local_mirror" for f in kb.facts("pros-hm"))
    assert any(t.origin == "ima" and t.code == 110030 for t in st.trace)
    kb.drain_trace()
    kb.search("屏幕")
    assert [t.step for t in kb.drain_trace()] == ["local_index"]       # no fake ima calls


def test_network_down_without_local_gives_empty_kb(tmp_path):
    def boom(req):
        raise httpx.ConnectError("down")
    kb = KB(settings(cache_dir=tmp_path, kb_mode="auto"), ima_transport=httpx.MockTransport(boom),
            sleep=lambda s: None)
    st = kb.status()
    assert st.mode == "none" and not st.connected and st.models == 0
    assert "ima" in st.detail and "KB_LOCAL_DIR" in st.detail
    assert kb.models() == [] and kb.search("屏幕") == [] and kb.find_models("Pro") == []
    with pytest.raises(KeyError):
        kb.image_bytes("x.png")


def test_auto_without_credentials_uses_local():
    kb = KB(settings(ima_client_id="", ima_api_key="", kb_local_dir=str(FIXTURE)))
    st = kb.status()
    assert st.mode == "local_mirror" and st.connected and not st.ima_configured
    assert "ima" in st.detail and st.api_key_hint == "" and st.account_hint == ""


def test_none_when_nothing_configured():
    kb = KB(settings(ima_client_id="", ima_api_key="", kb_local_dir=""))
    st = kb.status()
    assert st.mode == "none" and "未配置 ima 凭证" in st.detail


def test_article_only_layout(tmp_path):
    fake = FakeIma(article_tree())
    kb = KB(settings(cache_dir=tmp_path, kb_mode="ima"), ima_transport=httpx.MockTransport(fake.handler),
            sleep=lambda s: None)
    st = kb.status()
    assert st.mode == "ima" and st.connected
    assert {m.model_id for m in kb.models()} == {"pro-hm", "pros-hm"}
    fs = kb.facts("pros-hm")
    assert fs and all(f.model_id == "pros-hm" and f.source_path.endswith("article.md") for f in fs)
    assert any("120 Hz" in f.text for f in fs)
    assert any(f.kind == "boundary" and "销售版本" in f.text for f in fs)
    assert not any("example.invalid" in f.text for f in fs)           # 来源 section skipped
    assert all(f.source_urls for f in fs)
    assert "未在知识库中找到型号" in st.detail and "未找到官方价格快照" in st.detail   # reported, not hidden
    assert kb.images("pros-hm") == [] and kb.prices("pros-hm") == []


def test_refresh_reconnects(tmp_path):
    fake = FakeIma(fixture_tree(), deny=True)
    kb = KB(settings(cache_dir=tmp_path, kb_mode="auto", kb_local_dir=str(FIXTURE)),
            ima_transport=httpx.MockTransport(fake.handler), sleep=lambda s: None)
    assert kb.status().mode == "local_mirror" and not kb.status().connected
    fake.deny = False
    kb.refresh()
    st = kb.status()
    assert st.mode == "ima" and st.connected and st.last_response["code"] == 0
