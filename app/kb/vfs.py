"""Virtual file system over the knowledge base.

The indexer only talks to a ``VFS``; it never knows whether bytes come from the
organiser's local copy (``LocalFS``) or from the ima OpenAPI (``ImaFS``).

Paths are KB-relative, always use ``/`` and have no leading slash (``""`` = root).
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable


def norm_path(path: str) -> str:
    p = (path or "").replace("\\", "/")
    parts = [s for s in p.split("/") if s and s != "."]
    if any(s == ".." for s in parts):
        raise ValueError("非法路径")
    return "/".join(parts)


def join_path(*parts: str) -> str:
    return norm_path("/".join(p for p in parts if p))


def split_path(path: str) -> tuple[str, str]:
    p = norm_path(path)
    if "/" not in p:
        return "", p
    head, _, tail = p.rpartition("/")
    return head, tail


@dataclass
class VEntry:
    name: str
    is_dir: bool
    media_id: str = ""      # ima only; never shown to users
    folder_id: str = ""     # ima only; never shown to users
    guess_dir: bool = False  # ima: folder inferred from title only


@runtime_checkable
class VFS(Protocol):
    label: str

    def list_dir(self, path: str) -> list[VEntry]: ...
    def read_bytes(self, path: str) -> bytes: ...
    def read_text(self, path: str) -> str: ...
    def exists(self, path: str) -> bool: ...
    def is_dir(self, path: str) -> bool: ...


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Local mirror
# --------------------------------------------------------------------------
class LocalFS:
    label = "local"

    def __init__(self, root: str | os.PathLike):
        r = Path(root).expanduser().resolve()
        if not r.is_dir():
            raise FileNotFoundError(f"本地知识库目录不存在：{r.name}")
        # tolerate pointing at the parent of the KB folder (zip often unpacks with one wrapper dir)
        if not (r / "P1-产品参数库").is_dir():
            subs = [d for d in r.iterdir() if d.is_dir()]
            hit = [d for d in subs if (d / "P1-产品参数库").is_dir()]
            if len(hit) == 1:
                r = hit[0]
        self.root = r

    @property
    def name(self) -> str:
        return self.root.name

    def _p(self, path: str) -> Path:
        parts = [s for s in norm_path(path).split("/") if s]
        p = self.root.joinpath(*parts) if parts else self.root
        return p

    def list_dir(self, path: str) -> list[VEntry]:
        p = self._p(path)
        if not p.is_dir():
            raise FileNotFoundError(path)
        out = [VEntry(c.name, c.is_dir()) for c in sorted(p.iterdir(), key=lambda x: x.name)]
        return out

    def read_bytes(self, path: str) -> bytes:
        p = self._p(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_bytes()

    def read_text(self, path: str) -> str:
        return decode_text(self.read_bytes(path))

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._p(path).is_dir()


# --------------------------------------------------------------------------
# ima
# --------------------------------------------------------------------------
def _entry_from_item(item: dict) -> Optional[VEntry]:
    """Turn one get_knowledge_list item into a VEntry (folder or file).

    实测（2026-10-18，任德耀新建华为PC知识库）：根目录只有一项
    `title == kb_name`、`media_type: 99`、带 `parent_folder_id`，它其实是**文件夹**。
    ima 的 MediaType 枚举里没有 99，所以这里把 99 与 folder_info、无 media_type 一并
    视为文件夹线索；真实返回若还有别的文件夹标记，按同样方式补在 `explicit` 里。
    """
    fi = item.get("folder_info") if isinstance(item.get("folder_info"), dict) else {}
    mid = str(item.get("media_id") or "")
    fid = str(fi.get("folder_id") or item.get("folder_id") or "")
    title = str(item.get("title") or fi.get("name") or item.get("name") or "").strip()
    if not title:
        return None
    mtype = item.get("media_type")
    folder_marked = mtype in (99, "99") or fi or item.get("is_folder") is True
    if folder_marked:
        return VEntry(title, True, media_id=mid, folder_id=mid or fid)
    has_type = mtype not in (None, "", 0, "0")
    if not has_type and not re.search(r"\.[A-Za-z0-9]{1,5}$", title):
        return VEntry(title, True, media_id=mid, folder_id=mid or fid, guess_dir=True)
    return VEntry(title, False, media_id=mid)


def _stem(name: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)


def _find_entry(entries: list[VEntry], name: str) -> Optional[VEntry]:
    for e in entries:
        if e.name == name:
            return e
    low = name.lower()
    for e in entries:
        if e.name.lower() == low:
            return e
    sn = _stem(name)
    for e in entries:
        if not e.is_dir and (_stem(e.name) == sn) and (_stem(e.name) != e.name or sn != name):
            return e
    return None


class ImaFS:
    """Lazy directory tree over ima ``get_knowledge_list`` + ``get_media_info`` downloads
    with an on-disk cache (keyed by a hash of the media id)."""

    label = "ima"

    def __init__(self, client, kb_id: str, cache_dir: str | os.PathLike, kb_name: str = ""):
        self.client = client
        self._kb_id = kb_id
        self.kb_name = kb_name
        self._dirs: dict[str, list[VEntry]] = {}
        self._lock = threading.RLock()
        h = hashlib.sha1(kb_id.encode("utf-8")).hexdigest()[:10]
        self.cache_dir = Path(cache_dir) / "ima" / h
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"folders": 0, "files": 0, "downloads": 0, "cache_hits": 0}
        # ima 的根列表只有一项：名字与知识库相同的包装文件夹（media_type=99），
        # 它的 media_id 才是真正的根 folder_id。不带 folder_id 调 get_knowledge_list
        # 只能拿到这一项，拿不到任何子目录。
        self._root_ids: list[str] = []
        self._root_loaded = False

    def reset(self) -> None:
        with self._lock:
            self._dirs.clear()
            self._root_loaded = False
            self.stats.update({"folders": 0, "files": 0, "downloads": 0, "cache_hits": 0})

    # ---- root ---------------------------------------------------------
    def _root_folders(self) -> list[str]:
        """返回真正的根 folder_id 列表（ima 的根列表是名字同知识库的包装文件夹）。"""
        if self._root_loaded:
            return self._root_ids
        with self._lock:
            if self._root_loaded:
                return self._root_ids
            # 根路径 "" 用不带 folder_id 的方式列一次
            items = self.client.iter_knowledge_list(self._kb_id, None, folder_title="")
            entries: list[VEntry] = []
            for it in items:
                e = _entry_from_item(it)
                if e is None:
                    continue
                entries.append(e)
                if e.is_dir and e.folder_id:
                    self._root_ids.append(e.folder_id)
            self._dirs[""] = entries
            self.client.register_ids(*[e.media_id for e in entries], *self._root_ids)
            self._root_loaded = True
            return self._root_ids

    # ---- tree ---------------------------------------------------------
    def _load(self, path: str) -> list[VEntry]:
        path = norm_path(path)
        with self._lock:
            if path in self._dirs:
                return self._dirs[path]
            if path == "":
                # 若干包装文件夹并列时按名称合并成一级
                merged: list[VEntry] = []
                for rid in self._root_folders():
                    for e in self._load_folder(rid, ""):
                        if e.name not in {x.name for x in merged}:
                            merged.append(e)
                self._dirs[""] = merged
                return merged
            parent, name = split_path(path)
            parent_entries = self._load(parent)
            entry = next((e for e in parent_entries if e.name == name), None)
            if entry is None or not entry.is_dir:
                raise FileNotFoundError(path)
            return self._load_folder(entry.folder_id, entry.name)

    def _load_folder(self, folder_id: str, title: str) -> list[VEntry]:
        items = self.client.iter_knowledge_list(self._kb_id, folder_id, folder_title=title)
        entries: list[VEntry] = []
        seen: set[str] = set()
        for it in items:
            e = _entry_from_item(it)
            if e is None or e.name in seen:
                continue
            seen.add(e.name)
            entries.append(e)
            self.stats["folders" if e.is_dir else "files"] += 1
            self.client.register_ids(e.media_id, e.folder_id)
        return entries

    def list_dir(self, path: str) -> list[VEntry]:
        return list(self._load(path))

    def _entry(self, path: str) -> Optional[VEntry]:
        path = norm_path(path)
        if path == "":
            return VEntry("", True)
        parent, name = split_path(path)
        try:
            return _find_entry(self._load(parent), name)
        except FileNotFoundError:
            return None

    def exists(self, path: str) -> bool:
        return self._entry(path) is not None

    def is_dir(self, path: str) -> bool:
        e = self._entry(path)
        return bool(e and e.is_dir)

    def media_title_map(self) -> dict[str, str]:
        """media_id -> KB path for all loaded files (internal use for search hits)."""
        out: dict[str, str] = {}
        with self._lock:
            for d, entries in self._dirs.items():
                for e in entries:
                    if e.media_id:
                        out[e.media_id] = join_path(d, e.name)
        return out

    # ---- content ------------------------------------------------------
    def _cache_file(self, media_id: str) -> Path:
        return self.cache_dir / hashlib.sha1(media_id.encode("utf-8")).hexdigest()

    def read_bytes(self, path: str) -> bytes:
        e = self._entry(path)
        if e is None or (e.is_dir and not e.guess_dir) or not e.media_id:
            raise FileNotFoundError(path)
        cf = self._cache_file(e.media_id)
        if cf.is_file():
            self.stats["cache_hits"] += 1
            return cf.read_bytes()
        info = self.client.get_media_info(e.media_id, title=e.name)
        ui = info.get("url_info") or {}
        url = ui.get("url")
        if not url:
            if info.get("notebook_ext_info"):
                raise OSError(f"「{e.name}」是 ima 笔记，暂不支持下载原文")
            raise FileNotFoundError(f"ima 未提供「{e.name}」的可访问链接，请在 ima 客户端查看原文")
        data = self.client.download(url, ui.get("headers") or {})
        tmp = cf.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, cf)
        self.stats["downloads"] += 1
        return data

    def read_text(self, path: str) -> str:
        return decode_text(self.read_bytes(path))
