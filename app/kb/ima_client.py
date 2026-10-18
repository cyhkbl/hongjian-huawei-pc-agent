"""ima OpenAPI client (official knowledge-base skill v1.1.10, 字段名严格按官方 api.md).

* All calls are ``POST {base}/openapi/wiki/v1/<api>`` with JSON body and headers
  ``ima-openapi-clientid`` / ``ima-openapi-apikey``.
* ``code != 0`` raises :class:`ImaError` carrying the server ``msg`` verbatim.
* 110021 (频控) and 110010 (下游网络) are retried with exponential back-off.
* Every call records a sanitized :class:`TraceEntry` (no keys, no kb/media/folder ids).
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, Optional

import httpx

from app.models import TraceEntry

BASE_PATH = "/openapi/wiki/v1"
SKILL_VERSION = "1.1.10"
RETRY_CODES = {110021, 110010}
HIDDEN = "[已隐藏]"


class ImaError(Exception):
    """ima returned ``code != 0`` (or the transport failed)."""

    def __init__(self, code: int, msg: str, api: str = ""):
        super().__init__(msg or f"ima 错误 {code}")
        self.code = code
        self.msg = msg or ""
        self.api = api

    @property
    def is_permission(self) -> bool:
        return self.code == 110030

    def human(self) -> str:
        if self.code == 110030:
            return f"无权限访问该知识库（110030）：{self.msg}"
        if self.code == 110021:
            return f"ima 请求过于频繁（110021）：{self.msg}"
        if self.code in (-100, -101):
            return f"网络不可达：{self.msg}"
        if self.code < 0:
            return f"ima 返回异常（HTTP {-self.code}）：{self.msg}"
        return f"ima 返回错误 {self.code}：{self.msg}"


class ImaClient:
    def __init__(self, client_id: str, api_key: str, base_url: str = "https://ima.qq.com", *,
                 timeout: float = 20.0, max_retries: int = 4, backoff: float = 0.8,
                 min_interval: float = 0.25,
                 transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self._client_id = client_id
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff = backoff
        self.min_interval = min_interval      # 客户端节流，避免自己把频控打满
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)
        self._lock = threading.RLock()
        self._last_call = 0.0
        self._secrets: set[str] = {s for s in (client_id, api_key) if s}
        self._pending: list[TraceEntry] = []
        self.history: deque[TraceEntry] = deque(maxlen=60)
        self.last_response: dict = {}

    # ---- housekeeping ---------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def register_ids(self, *ids: str) -> None:
        """Remember internal ids so they can never leak into trace/last_response."""
        with self._lock:
            for i in ids:
                if i and len(i) >= 4:
                    self._secrets.add(i)

    def _scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self._secrets:
                if s in value:
                    value = value.replace(s, HIDDEN)
            return value
        if isinstance(value, dict):
            return {k: self._scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._scrub(v) for v in value]
        return value

    def _record(self, step: str, request: dict, code: Optional[int], msg: str, count: Optional[int],
                ms: int, endpoint: str) -> None:
        with self._lock:
            entry = TraceEntry(step=step, request=self._scrub(request), code=code,
                               msg=self._scrub(msg or "")[:200], count=count, ms=ms, origin="ima")
            self._pending.append(entry)
            self.history.append(entry)
            self.last_response = {"code": code, "msg": entry.msg, "endpoint": endpoint}

    def drain_trace(self) -> list[TraceEntry]:
        with self._lock:
            out, self._pending = self._pending, []
            return out

    # ---- transport ------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "ima-openapi-clientid": self._client_id,
            "ima-openapi-apikey": self._api_key,
            "ima-openapi-ctx": f"skill_version={SKILL_VERSION}",
            "Content-Type": "application/json",
        }

    def _post(self, api: str, body: dict) -> dict:
        """POST with retry. Returns the ``data`` object; raises ImaError."""
        url = f"{self.base_url}{BASE_PATH}/{api}"
        attempt = 0
        while True:
            try:
                resp = self._http.post(url, headers=self._headers(),
                                       content=json.dumps(body, ensure_ascii=False).encode("utf-8"))
            except httpx.TimeoutException as e:
                err = ImaError(-100, f"请求 ima 超时（{type(e).__name__}）", api)
            except httpx.HTTPError as e:
                err = ImaError(-100, f"无法连接 ima（{type(e).__name__}）", api)
            else:
                err = None
                if resp.status_code != 200:
                    err = ImaError(-resp.status_code, f"HTTP {resp.status_code}", api)
                    if resp.status_code in (502, 503, 504, 429):
                        pass  # retried below
                    else:
                        try:
                            j = resp.json()
                            if isinstance(j, dict) and "code" in j:
                                err = ImaError(int(j["code"]), str(j.get("msg") or ""), api)
                        except Exception:
                            pass
                else:
                    try:
                        j = resp.json()
                    except Exception:
                        raise ImaError(-101, "ima 返回的不是合法 JSON", api)
                    if not isinstance(j, dict):
                        raise ImaError(-101, "ima 返回格式异常", api)
                    code = j.get("code", 0)
                    try:
                        code = int(code)
                    except (TypeError, ValueError):
                        code = -101
                    if code == 0:
                        data = j.get("data")
                        return data if isinstance(data, dict) else {}
                    err = ImaError(code, str(j.get("msg") or ""), api)
            retryable = err.code in RETRY_CODES or err.code in (-100, -429, -502, -503, -504)
            # 客户端节流：两次调用之间留最小间隔，别自己触发频控
            gap = self.min_interval - (time.monotonic() - self._last_call)
            if gap > 0:
                self._sleep(gap)
            self._last_call = time.monotonic()
            if retryable and attempt < self.max_retries:
                # 频控（110021）线性拉长等待，其余错误翻倍退避
                delay = (self.backoff * 2.0 * (attempt + 1) if err.code == 110021
                         else self.backoff * (2 ** attempt))
                self._sleep(delay)
                attempt += 1
                continue
            raise err

    def call(self, api: str, body: dict, *, step: Optional[str] = None, request: Optional[dict] = None,
             count_of: Optional[Callable[[dict], Optional[int]]] = None) -> dict:
        step = step or api
        t0 = time.perf_counter()
        endpoint = f"{BASE_PATH}/{api}"
        try:
            data = self._post(api, body)
        except ImaError as e:
            self._record(step, request or {}, e.code, e.msg, None,
                         int((time.perf_counter() - t0) * 1000), endpoint)
            raise
        cnt = count_of(data) if count_of else None
        self._record(step, request or {}, 0, "success", cnt,
                     int((time.perf_counter() - t0) * 1000), endpoint)
        return data

    # ---- APIs -----------------------------------------------------------
    def search_knowledge_base(self, query: str, limit: int = 20, max_pages: int = 5) -> list[dict]:
        """-> [{"id","name"}] ; accepts both kb_id/kb_name and id/name."""
        out: list[dict] = []
        cursor = ""
        limit = max(1, min(int(limit), 20))
        for page in range(max_pages):
            data = self.call(
                "search_knowledge_base", {"query": query, "cursor": cursor, "limit": limit},
                request={"query": query, "limit": limit, "page": page + 1},
                count_of=lambda d: len(d.get("info_list") or []))
            for it in data.get("info_list") or []:
                if not isinstance(it, dict):
                    continue
                kid = it.get("kb_id") or it.get("id") or ""
                name = it.get("kb_name") or it.get("name") or ""
                if kid:
                    out.append({"id": str(kid), "name": str(name)})
                    self.register_ids(str(kid))
            if data.get("is_end", True) or not data.get("next_cursor"):
                break
            cursor = str(data["next_cursor"])
        return out

    def get_addable_knowledge_base_list(self, max_pages: int = 5) -> list[dict]:
        """Browse fallback for finding a KB when search returns nothing."""
        out: list[dict] = []
        cursor = ""
        for page in range(max_pages):
            data = self.call(
                "get_addable_knowledge_base_list", {"cursor": cursor, "limit": 50},
                request={"limit": 50, "page": page + 1},
                count_of=lambda d: len(d.get("addable_knowledge_base_list") or []))
            for it in data.get("addable_knowledge_base_list") or []:
                if isinstance(it, dict) and (it.get("id") or it.get("kb_id")):
                    kid = str(it.get("id") or it.get("kb_id"))
                    out.append({"id": kid, "name": str(it.get("name") or it.get("kb_name") or "")})
                    self.register_ids(kid)
            if data.get("is_end", True) or not data.get("next_cursor"):
                break
            cursor = str(data["next_cursor"])
        return out

    def get_knowledge_base(self, kb_id: str, kb_title: str = "") -> dict:
        self.register_ids(kb_id)
        data = self.call("get_knowledge_base", {"ids": [kb_id]},
                         request={"kb": kb_title or "(知识库)"},
                         count_of=lambda d: len(d.get("infos") or {}))
        infos = data.get("infos") or {}
        return infos.get(kb_id) or (next(iter(infos.values())) if infos else {})

    def get_knowledge_list_page(self, kb_id: str, folder_id: Optional[str] = None, cursor: str = "",
                                limit: int = 50, folder_title: str = "") -> dict:
        body: dict = {"knowledge_base_id": kb_id, "cursor": cursor, "limit": max(1, min(int(limit), 50))}
        if folder_id:
            body["folder_id"] = folder_id
        self.register_ids(kb_id, folder_id or "")
        return self.call("get_knowledge_list", body,
                         request={"folder": folder_title or "(根目录)", "limit": body["limit"],
                                  "cursor": "next" if cursor else "first"},
                         count_of=lambda d: len(d.get("knowledge_list") or []))

    def iter_knowledge_list(self, kb_id: str, folder_id: Optional[str] = None, folder_title: str = "",
                            max_pages: int = 100) -> list[dict]:
        out: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            data = self.get_knowledge_list_page(kb_id, folder_id, cursor, 50, folder_title)
            out.extend(x for x in (data.get("knowledge_list") or []) if isinstance(x, dict))
            nxt = str(data.get("next_cursor") or "")
            if data.get("is_end", True) or not nxt or nxt == cursor:
                break
            cursor = nxt
        return out

    def search_knowledge(self, kb_id: str, query: str, max_pages: int = 1) -> list[dict]:
        out: list[dict] = []
        cursor = ""
        self.register_ids(kb_id)
        for page in range(max_pages):
            data = self.call(
                "search_knowledge", {"query": query, "cursor": cursor, "knowledge_base_id": kb_id},
                request={"query": query, "page": page + 1},
                count_of=lambda d: len(d.get("info_list") or []))
            for it in data.get("info_list") or []:
                if isinstance(it, dict):
                    self.register_ids(str(it.get("media_id") or ""))
                    out.append(it)
            nxt = str(data.get("next_cursor") or "")
            if data.get("is_end", True) or not nxt:
                break
            cursor = nxt
        return out

    def get_media_info(self, media_id: str, title: str = "") -> dict:
        self.register_ids(media_id)
        return self.call("get_media_info", {"media_id": media_id},
                         request={"title": title or "(文件)"},
                         count_of=lambda d: 1 if d.get("url_info") else 0)

    def download(self, url: str, headers: Optional[dict] = None, title: str = "") -> bytes:
        """Download a media URL returned by get_media_info (must carry returned headers)."""
        t0 = time.perf_counter()
        attempt = 0
        while True:
            try:
                r = self._http.get(url, headers=headers or {})
                if r.status_code == 200:
                    self._record("download_media", {"title": title or "(文件)"}, 0, "ok", len(r.content),
                                 int((time.perf_counter() - t0) * 1000), "(media url)")
                    return r.content
                err = ImaError(-r.status_code, f"下载原文失败：HTTP {r.status_code}", "download")
                retry = r.status_code in (429, 500, 502, 503, 504)
            except httpx.HTTPError as e:
                err = ImaError(-100, f"下载原文失败（{type(e).__name__}）", "download")
                retry = True
            if retry and attempt < self.max_retries:
                self._sleep(self.backoff * (2 ** attempt))
                attempt += 1
                continue
            self._record("download_media", {"title": title or "(文件)"}, err.code, err.msg, None,
                         int((time.perf_counter() - t0) * 1000), "(media url)")
            raise err


def pick_kb(candidates: Iterable[dict], name: str) -> Optional[dict]:
    """Choose the KB called ``name`` (exact, else unique containment)."""
    cands = list(candidates)
    for c in cands:
        if c.get("name") == name:
            return c
    norm = name.replace(" ", "")
    hits = [c for c in cands if norm and norm in (c.get("name") or "").replace(" ", "")]
    if len(hits) == 1:
        return hits[0]
    hits = [c for c in cands if (c.get("name") or "").replace(" ", "") in norm and c.get("name")]
    if len(hits) == 1:
        return hits[0]
    return None
