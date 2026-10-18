"""KnowledgeBase implementation: in-memory index + search + trace + status.

Modes
-----
* ``ima``          connected to the ima OpenAPI (content read through ImaFS)
* ``local_mirror`` organiser's KB copy (also used as the degraded fallback when ima is unreachable)
* ``none``         nothing usable: empty KB, status explains why

Nothing here ever fabricates an ima response: when ima fails we say so in ``status().detail``.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

from app.config import Settings, mask
from app.kb.aliases import AliasMatcher, resolve_any, resolve_path
from app.kb.ima_client import ImaClient, ImaError, pick_kb
from app.kb.indexer import KBIndex, build_index
from app.kb.textutil import tokens
from app.kb.vfs import VFS, ImaFS, LocalFS
from app.models import (
    Fact, ImageAsset, KBStatus, PriceRecord, ProductModel, SearchHit, TraceEntry,
)

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".gif": "image/gif"}


def sniff_mime(data: bytes, name: str = "") -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    low = name.lower()
    for ext, m in _MIME.items():
        if low.endswith(ext):
            return m
    return "application/octet-stream"


def _hint_id(cid: str) -> str:
    if not cid:
        return ""
    if len(cid) >= 8:
        return cid[:4] + "****" + cid[-2:]
    return mask(cid)


class KB:
    """Concrete :class:`app.kb.base.KnowledgeBase`."""

    def __init__(self, settings: Settings, *, ima_transport=None, sleep=time.sleep):
        self.settings = settings
        self._ima_transport = ima_transport
        self._sleep = sleep
        self._lock = threading.RLock()
        self._pending: list[TraceEntry] = []
        self._history: deque[TraceEntry] = deque(maxlen=40)
        self._reset_state()
        self.refresh()

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _reset_state(self) -> None:
        self._idx = KBIndex()
        self._mode = "none"
        self._connected = False
        self._detail = ""
        self._kb_name = ""
        self._vfs: Optional[VFS] = None
        self._client: Optional[ImaClient] = None
        self._kb_id = ""
        self._last_response: dict = {}
        self._build_maps()

    def _build_maps(self) -> None:
        idx = self._idx
        self._models = {m.model_id: m for m in idx.models}
        self._facts_by_id = {f.id: f for f in idx.facts}
        self._facts_by_model: dict[str, list[Fact]] = {}
        for f in idx.facts:
            self._facts_by_model.setdefault(f.model_id, []).append(f)
        self._images_by_id = {i.id: i for i in idx.images}
        self._images_by_model: dict[str, list[ImageAsset]] = {}
        for i in idx.images:
            self._images_by_model.setdefault(i.model_id, []).append(i)
        self._prices_by_model: dict[str, list[PriceRecord]] = {}
        for p in idx.prices:
            if p.model_id:
                self._prices_by_model.setdefault(p.model_id, []).append(p)
        self._matcher = AliasMatcher(idx.models)
        # search structures
        self._docs: list[tuple[str, str, str, Optional[str], set[str]]] = []
        self._fact_tokens: dict[str, set[str]] = {}
        df: dict[str, int] = {}
        for f in idx.facts:
            ts = set(tokens(f"{f.text} {' '.join(f.constraints)} {' '.join(f.tags)} {f.source_title}"))
            self._fact_tokens[f.id] = ts
            for t in ts:
                df[t] = df.get(t, 0) + 1
        for d in idx.docs:
            ts = set(tokens(f"{d.title} {d.text}"))
            self._docs.append((d.title, d.path, d.text, d.model_id or None, ts))
            for t in ts:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(idx.facts) + len(idx.docs))
        self._idf = {t: math.log(1 + n / (1 + c)) for t, c in df.items()}
        self._n = n

    # ------------------------------------------------------------------
    # connect / refresh
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """(Re)connect and rebuild the index. Never raises."""
        with self._lock:
            try:
                self._connect()
            except Exception as e:                       # noqa: BLE001 - last line of defence
                self._reset_state()
                self._detail = f"知识库初始化出错：{type(e).__name__}"
            self._collect()
            self._pending.clear()                         # init chatter is not part of any run

    def _local_dir_ok(self) -> bool:
        d = (self.settings.kb_local_dir or "").strip()
        if not d:
            return False
        try:
            LocalFS(d)
            return True
        except (FileNotFoundError, OSError):
            return False

    def _connect(self) -> None:
        s = self.settings
        want = (s.kb_mode or "auto").lower()
        ima_reason = ""
        if want in ("ima", "auto"):
            if s.ima_configured:
                ok, ima_reason = self._try_ima()
                if ok:
                    return
            else:
                ima_reason = "未配置 ima 凭证（IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY）"
        elif want not in ("local", "local_mirror"):
            ima_reason = f"未知的 KB_MODE「{want}」"
        failed_resp = dict(self._client.last_response) if self._client else {}
        degraded = bool(ima_reason) and s.ima_configured
        # ---- local
        if self._local_dir_ok():
            self._load_local()
            if degraded:
                self._detail = f"ima 不可达（{ima_reason}），已降级为本地镜像。" + self._detail
                self._connected = False
                self._last_response = failed_resp
            elif ima_reason:
                self._detail = f"本地镜像模式（{ima_reason}）。" + self._detail
            return
        # ---- nothing usable
        self._reset_state()
        reasons = []
        if ima_reason:
            reasons.append(f"ima：{ima_reason}")
        if (s.kb_local_dir or "").strip():
            reasons.append("本地镜像：KB_LOCAL_DIR 指向的目录不存在或不可读")
        else:
            reasons.append("本地镜像：未设置 KB_LOCAL_DIR")
        self._mode = "none"
        self._connected = False
        self._detail = "知识库不可用，当前为空库。" + "；".join(reasons)
        self._last_response = failed_resp
    # ---- local ----------------------------------------------------------
    def _load_local(self) -> None:
        t0 = time.perf_counter()
        fs = LocalFS(self.settings.kb_local_dir)
        idx = build_index(fs)
        self._set_index(idx)
        self._vfs = fs
        self._mode = "local_mirror"
        self._connected = True
        self._kb_name = fs.name
        if self._client is not None:
            self._client.close()
        self._client = None
        self._kb_id = ""
        self._last_response = {}
        self._detail = self._summary(idx, "已载入本地镜像「" + fs.name + "」")
        self._add_trace(TraceEntry(step="local_index", request={"action": "build_index"}, code=None,
                                   msg=f"载入 {len(idx.models)} 个型号、{len(idx.facts)} 条事实",
                                   count=len(idx.facts), ms=int((time.perf_counter() - t0) * 1000),
                                   origin="local_mirror"), pending=False)

    def _summary(self, idx: KBIndex, head: str) -> str:
        s = f"{head}：{len(idx.models)} 个型号、{len(idx.facts)} 条事实、{len(idx.images)} 张图片、{len(idx.prices)} 条价格记录。"
        if idx.notes:
            skipped = [n for n in idx.notes if not n.startswith("扫描了")]
            if skipped:
                s += "未解析部分：" + "；".join(skipped[:6]) + ("…" if len(skipped) > 6 else "") + "。"
        return s

    def _set_index(self, idx: KBIndex, origin: str = "local_mirror") -> None:
        for f in idx.facts:
            f.origin = origin  # type: ignore[assignment]
        for i in idx.images:
            i.origin = origin  # type: ignore[assignment]
        for p in idx.prices:
            p.origin = origin  # type: ignore[assignment]
        self._idx = idx
        self._build_maps()

    # ---- ima ------------------------------------------------------------
    def _try_ima(self) -> tuple[bool, str]:
        s = self.settings
        client = ImaClient(s.ima_client_id, s.ima_api_key, s.ima_base_url, transport=self._ima_transport,
                           sleep=self._sleep)
        self._client = client
        try:
            kb_id, kb_name = self._locate_kb(client)
            fs = ImaFS(client, kb_id, s.cache_dir, kb_name)
            idx = build_index(fs)
            if not idx.models:
                self._collect()
                return False, f"已连上知识库「{kb_name}」，但没有解析出任何型号资料"
            self._set_index(idx, origin="ima")
            self._vfs = fs
            self._kb_id = kb_id
            self._kb_name = kb_name
            self._mode = "ima"
            self._connected = True
            self._detail = self._summary(idx, f"已连接 ima 共享知识库「{kb_name}」") \
                + f"目录 {fs.stats['folders']} 个、文件 {fs.stats['files']} 个。"
            self._last_response = dict(client.last_response)
            self._collect()
            return True, ""
        except ImaError as e:
            self._last_response = dict(client.last_response)
            self._collect()
            self._client_failed = e
            return False, e.human()
        except Exception as e:                           # noqa: BLE001
            self._collect()
            return False, f"{type(e).__name__}"

    def _locate_kb(self, client: ImaClient) -> tuple[str, str]:
        import os
        name = self.settings.ima_kb_name
        forced = os.environ.get("IMA_KB_ID", "").strip()
        if forced:
            client.register_ids(forced)
            return forced, name
        cands = client.search_knowledge_base(name)
        hit = pick_kb(cands, name)
        if hit is None:
            # search is fuzzy / may be empty: broaden, then browse the account's KB list
            for q in (name[:6], ""):
                if hit is not None:
                    break
                try:
                    hit = pick_kb(client.search_knowledge_base(q), name)
                except ImaError:
                    continue
        if hit is None:
            try:
                hit = pick_kb(client.get_addable_knowledge_base_list(), name)
            except ImaError:
                hit = None
        if hit is None:
            raise ImaError(0, f"账号下没有找到名为「{name}」的知识库（搜索为空且浏览也未命中，"
                              f"请确认已加入该共享知识库）")
        return hit["id"], hit.get("name") or name

    # ------------------------------------------------------------------
    # trace
    # ------------------------------------------------------------------
    def _add_trace(self, e: TraceEntry, pending: bool = True) -> None:
        with self._lock:
            self._history.append(e)
            if pending:
                self._pending.append(e)

    def _collect(self, pending: bool = True) -> None:
        if self._client is None:
            return
        for e in self._client.drain_trace():
            self._add_trace(e, pending)
        if self._client.last_response:
            self._last_response = dict(self._client.last_response)

    def drain_trace(self) -> list[TraceEntry]:
        with self._lock:
            self._collect()
            out, self._pending = self._pending, []
            return out

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def status(self) -> KBStatus:
        with self._lock:
            self._collect(pending=False)
            s = self.settings
            return KBStatus(
                mode=self._mode,  # type: ignore[arg-type]
                kb_name=self._kb_name, connected=self._connected, detail=self._detail,
                account_hint=_hint_id(s.ima_client_id), api_key_hint=mask(s.ima_api_key),
                ima_configured=s.ima_configured, models=len(self._idx.models), facts=len(self._idx.facts),
                images=len(self._idx.images), prices=len(self._idx.prices),
                snapshot_date=self._idx.snapshot_date if self._idx.models else "",
                last_response=dict(self._last_response), trace=list(self._history)[-30:])

    # ------------------------------------------------------------------
    # structured access
    # ------------------------------------------------------------------
    def models(self) -> list[ProductModel]:
        return list(self._idx.models)

    def get_model(self, model_id: str) -> Optional[ProductModel]:
        return self._models.get(model_id)

    def find_models(self, text: str) -> list[tuple[ProductModel, float, str]]:
        return self._matcher.match(text)

    def facts(self, model_id: str, kinds: Optional[list[str]] = None,
              categories: Optional[list[str]] = None, tags: Optional[list[str]] = None) -> list[Fact]:
        out = self._facts_by_model.get(model_id, [])
        if kinds:
            out = [f for f in out if f.kind in kinds]
        if categories:
            out = [f for f in out if f.category in categories]
        if tags:
            out = [f for f in out if set(tags) & set(f.tags)]
        return list(out)

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        return self._facts_by_id.get(fact_id)

    def images(self, model_id: str, tags: Optional[list[str]] = None) -> list[ImageAsset]:
        out = self._images_by_model.get(model_id, [])
        if tags:
            out = [i for i in out if set(tags) & set(i.tags)]
        return list(out)

    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return self._images_by_id.get(image_id)

    def image_bytes(self, image_id: str) -> tuple[bytes, str]:
        img = self._images_by_id.get(image_id)
        if img is None:
            raise KeyError(image_id)
        if self._vfs is None:
            raise FileNotFoundError(image_id)
        try:
            data = self._vfs.read_bytes(img.kb_path)
        finally:
            with self._lock:
                self._collect()
        return data, sniff_mime(data, img.id)

    def prices(self, model_id: str) -> list[PriceRecord]:
        return list(self._prices_by_model.get(model_id, []))

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def _score(self, query: str, model_id: Optional[str], limit: int) -> list[SearchHit]:
        q = tokens(query)
        if not q:
            return []
        qs = set(q)
        boost: set[str] = set()
        if model_id is None:
            boost = {m.model_id for m, sc, _ in self._matcher.match(query) if sc >= 0.7}
        scored: list[tuple[float, SearchHit]] = []
        for f in self._idx.facts:
            if model_id and f.model_id != model_id:
                continue
            ts = self._fact_tokens.get(f.id, set())
            hit = qs & ts
            if not hit:
                continue
            sc = sum(self._idf.get(t, 1.0) for t in hit) / (1 + 0.15 * math.log(1 + len(ts)))
            sc += 0.6 * sum(self._idf.get(t, 1.0) for t in qs & set(tokens(f.source_title)))
            if f.kind in ("card", "spec", "selling"):
                sc *= 1.05
            if f.model_id in boost:
                sc *= 1.5
            scored.append((sc, SearchHit(title=f.source_title, path=f.source_path,
                                         snippet=f.text[:140], model_id=f.model_id)))
        for title, path, text, mid, ts in self._docs:
            if model_id and mid != model_id:
                continue
            tt = set(tokens(title))
            hit = qs & tt
            if not hit:
                continue
            sc = 1.2 * sum(self._idf.get(t, 1.0) for t in hit)
            if mid in boost:
                sc *= 1.5
            scored.append((sc, SearchHit(title=title, path=path, snippet=text[:140].replace("\n", " "),
                                         model_id=mid)))
        scored.sort(key=lambda x: -x[0])
        out: list[SearchHit] = []
        per_path: dict[str, int] = {}
        for _sc, h in scored:
            if per_path.get(h.path, 0) >= 2:
                continue
            per_path[h.path] = per_path.get(h.path, 0) + 1
            out.append(h)
            if len(out) >= limit:
                break
        return out

    def search(self, query: str, model_id: Optional[str] = None, limit: int = 8) -> list[SearchHit]:
        limit = max(1, min(int(limit or 8), 30))
        t0 = time.perf_counter()
        if self._mode == "ima" and self._client is not None and self._kb_id:
            return self._search_ima(query, model_id, limit, t0)
        hits = self._score(query, model_id, limit)
        req = {"query": query, "limit": limit}
        if model_id:
            req["model"] = self._models[model_id].short_name if model_id in self._models else model_id
        self._add_trace(TraceEntry(
            step="local_index", request=req, code=None,
            msg="本地镜像检索" + ("" if hits else "：无命中"), count=len(hits),
            ms=int((time.perf_counter() - t0) * 1000), origin="local_mirror"))
        return hits

    def _hit_from_ima(self, it: dict, titles: dict[str, str]) -> SearchHit:
        mid = str(it.get("media_id") or "")
        title = str(it.get("title") or "")
        path = titles.get(mid, "")
        snippet = str(it.get("highlight_content") or "")
        snippet = snippet.replace("<em>", "").replace("</em>", "").strip()[:200]
        return SearchHit(title=title, path=path, snippet=snippet,
                         model_id=resolve_path(path) or resolve_any(title, snippet[:80]))

    def _search_ima(self, query: str, model_id: Optional[str], limit: int, t0: float) -> list[SearchHit]:
        client = self._client
        assert client is not None
        titles = self._vfs.media_title_map() if isinstance(self._vfs, ImaFS) else {}
        hits: list[SearchHit] = []
        err: Optional[ImaError] = None
        try:
            items = client.search_knowledge(self._kb_id, query)
            hits = [self._hit_from_ima(it, titles) for it in items]
            if model_id:
                hits = [h for h in hits if h.model_id in (model_id, None)]
            hits = hits[:limit]
        except ImaError as e:
            err = e
        finally:
            with self._lock:
                self._collect()
        if hits:
            return hits
        # search failed or came back empty -> browse the loaded directory tree / index instead
        fb = self._score(query, model_id, limit)
        why = f"ima 搜索失败（{err.human()}）" if err else "ima 搜索无结果"
        self._add_trace(TraceEntry(
            step="browse_fallback", request={"query": query, "limit": limit}, code=None,
            msg=f"{why}，已回退到目录浏览/已载入资料检索", count=len(fb),
            ms=int((time.perf_counter() - t0) * 1000), origin="ima"))
        return fb
