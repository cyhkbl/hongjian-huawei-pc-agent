"""Model registry (curated metadata), name -> model_id resolver and alias matcher.

Official full names come from the KB documents; everything user-facing that cannot be
read from a document (aliases, confusable pairs, short names) is curated here.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.models import ProductModel

# model_id -> curated metadata (order = display order)
MODEL_META: dict[str, dict] = {
    "pro-hm": dict(
        short="MateBook Pro", series="MateBook Pro", os="harmonyos",
        confusable=["pros-hm"],
        aliases=["HUAWEI MateBook Pro", "MateBook Pro", "MateBook Pro 鸿蒙版", "MateBook Pro（鸿蒙版）",
                 "鸿蒙版 MateBook Pro", "Pro 鸿蒙版", "Pro（鸿蒙版）", "鸿蒙 Pro", "Pro"]),
    "pros-hm": dict(
        short="MateBook Pro S", series="MateBook Pro", os="harmonyos",
        confusable=["pro-hm"],
        aliases=["HUAWEI MateBook Pro S", "MateBook Pro S", "MateBook ProS", "Pro S", "ProS",
                 "MateBook Pro S 鸿蒙版", "鸿蒙版 MateBook Pro S"]),
    "mb14-hm": dict(
        short="MateBook 14 鸿蒙版", series="MateBook 14", os="harmonyos",
        confusable=["mb14-ultra"],
        aliases=["HUAWEI MateBook 14（鸿蒙版）", "HUAWEI MateBook 14 鸿蒙版", "MateBook 14（鸿蒙版）",
                 "MateBook 14 鸿蒙版", "MateBook 14 HarmonyOS", "鸿蒙版 MateBook 14", "鸿蒙 MateBook 14",
                 "鸿蒙版14", "14 鸿蒙版", "鸿蒙版 14 英寸", "MateBook 14"]),
    "fold": dict(
        short="MateBook Fold 非凡大师", series="MateBook Fold", os="harmonyos",
        confusable=[],
        aliases=["HUAWEI MateBook Fold 非凡大师", "MateBook Fold 非凡大师", "MateBook Fold", "Fold 非凡大师",
                 "非凡大师", "折叠本", "折叠屏笔记本", "折叠屏电脑", "鸿蒙折叠电脑", "Fold"]),
    "mb14-ultra": dict(
        short="MateBook 14 酷睿 Ultra", series="MateBook 14", os="windows",
        confusable=["mb14-hm", "d14"],
        aliases=["HUAWEI MateBook 14 酷睿 Ultra", "MateBook 14 酷睿 Ultra", "MateBook 14 酷睿 Ultra 版",
                 "MateBook 14（酷睿 Ultra）", "MateBook 14 Ultra", "14 酷睿 Ultra", "酷睿 Ultra 版 14",
                 "酷睿Ultra版14", "酷睿 Ultra 版 MateBook 14", "Windows 版 MateBook 14", "MateBook 14"]),
    "d14": dict(
        short="MateBook D 14", series="MateBook D 14", os="windows",
        confusable=["d16", "d16se", "mb14-ultra"],
        aliases=["HUAWEI MateBook D 14", "MateBook D 14", "MateBook D14", "D14", "D 14", "MateBook D 14 2024",
                 "D 14 2024"]),
    "d16": dict(
        short="MateBook D 16", series="MateBook D 16", os="windows",
        confusable=["d16se", "d14"],
        aliases=["HUAWEI MateBook D 16", "MateBook D 16", "MateBook D16", "D16", "D 16", "MateBook D 16 2024",
                 "D 16 2024"]),
    "d16se": dict(
        short="MateBook D 16 SE", series="MateBook D 16", os="windows",
        confusable=["d16", "d14"],
        aliases=["HUAWEI MateBook D 16 SE 版", "MateBook D 16 SE 版", "MateBook D 16 SE", "D 16 SE", "D16SE",
                 "D16 SE 版", "D 16 SE 版", "MateBook D 16 SE 版 2024"]),
    "gt14": dict(
        short="MateBook GT 14", series="MateBook GT", os="windows",
        confusable=["xpro"],
        aliases=["HUAWEI MateBook GT 14", "MateBook GT 14", "MateBook GT", "MateBook GT 系列", "GT 14", "GT14",
                 "GT 系列", "GT"]),
    "xpro": dict(
        short="MateBook X Pro 微绒典藏版", series="MateBook X", os="windows",
        confusable=["gt14"],
        aliases=["HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版", "MateBook X Pro 酷睿 Ultra", "MateBook X Pro",
                 "MateBook X 系列", "MateBook X", "X Pro 微绒典藏版", "微绒典藏版", "X Pro", "XPro", "X 系列"]),
}
MODEL_ORDER = list(MODEL_META)


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()


def resolve_model(text: str) -> Optional[str]:
    """Map any official/dir/price-table product name to a model_id (None if not one of the 10)."""
    t = _nfkc(text)
    if not t or "matebook" not in t:
        return None
    if "企业版" in t or "擎云" in t:
        return None
    if re.search(r"matebook\s*d\s*16\s*se", t):
        return "d16se"
    if re.search(r"matebook\s*d\s*16", t):
        return "d16"
    if re.search(r"matebook\s*d\s*14", t):
        return "d14"
    if re.search(r"matebook\s*gt", t):
        return "gt14"
    if re.search(r"matebook\s*x(?![a-z0-9])", t):
        return "xpro"
    if "fold" in t:
        return "fold"
    if re.search(r"matebook\s*14", t):
        return "mb14-ultra" if ("ultra" in t or "酷睿" in t) else "mb14-hm"
    if re.search(r"matebook\s*pro\s*s(?![a-z0-9])", t):
        return "pros-hm"
    if re.search(r"matebook\s*pro", t):
        return "pro-hm"
    return None


def resolve_any(*texts: str) -> Optional[str]:
    for t in texts:
        r = resolve_model(t)
        if r:
            return r
    return None


def resolve_path(path: str) -> Optional[str]:
    """Resolve by the deepest path segment that names a model."""
    for seg in reversed([s for s in (path or "").replace("\\", "/").split("/") if s]):
        r = resolve_model(seg)
        if r:
            return r
    return None


# --------------------------------------------------------------------------
# free-text alias matching
# --------------------------------------------------------------------------
_SEP = r"[\s\-_·]*"


def _alias_regex(alias: str) -> re.Pattern:
    a = _nfkc(alias)
    chars = [re.escape(c) for c in a if not c.isspace() and c not in "-_·"]
    body = _SEP.join(chars)
    pre = r"(?<![a-z0-9])" if re.match(r"[a-z0-9]", a) else ""
    post = r"(?![a-z0-9])" if re.search(r"[a-z0-9]$", a) else ""
    return re.compile(pre + body + post)


def _compact(s: str) -> str:
    return re.sub(r"[\s\-_·]+", "", _nfkc(s))


class AliasMatcher:
    def __init__(self, models: list[ProductModel]):
        self._models = {m.model_id: m for m in models}
        self._entries: list[tuple[str, str, re.Pattern, float, int]] = []
        owners: dict[str, set[str]] = {}
        for m in models:
            for a in m.aliases + [m.name, m.short_name]:
                owners.setdefault(_compact(a), set()).add(m.model_id)
        all_keys = list(owners)
        for key, mids in owners.items():
            if not key:
                continue
            shared = len(mids) > 1
            proper_sub = any(key != k and key in k and (owners[k] - mids) for k in all_keys)
            if shared:
                score = 0.5
            elif proper_sub:
                score = 0.7
            elif len(key) <= 2:
                score = 0.6
            else:
                score = 0.95
            alias_display = key
            pat = _alias_regex(key)
            for mid in mids:
                self._entries.append((mid, alias_display, pat, score, len(key)))
        # keep original alias text for reporting
        self._display: dict[str, str] = {}
        for m in models:
            for a in m.aliases + [m.name, m.short_name]:
                self._display.setdefault(_compact(a), a)

    def match(self, text: str) -> list[tuple[ProductModel, float, str]]:
        t = _nfkc(text)
        if not t.strip():
            return []
        found: list[tuple[int, int, int, str, str, float]] = []
        seen = set()
        for mid, key, pat, score, ln in self._entries:
            for mo in pat.finditer(t):
                k = (mid, key, mo.start())
                if k in seen:
                    continue
                seen.add(k)
                found.append((mo.end() - mo.start(), mo.start(), mo.end(), mid, key, score))
        found.sort(key=lambda x: (-x[0], x[1]))
        accepted: list[tuple[int, int, str, str, float]] = []
        for _ln, s, e, mid, key, score in found:
            blocked = False
            for (s2, e2, mid2, key2, _sc) in accepted:
                if s < e2 and s2 < e:      # overlap with a longer (already accepted) match
                    # equal span shared alias for several models is fine
                    if not (s == s2 and e == e2 and key == key2):
                        blocked = True
                        break
            if not blocked:
                accepted.append((s, e, mid, key, score))
        best: dict[str, tuple[float, str, int]] = {}
        for s, e, mid, key, score in accepted:
            cur = best.get(mid)
            if cur is None or score > cur[0]:
                best[mid] = (score, self._display.get(key, key), s)
        order = {mid: i for i, mid in enumerate(MODEL_ORDER)}
        res = [(self._models[mid], sc, al) for mid, (sc, al, _pos) in best.items() if mid in self._models]
        res.sort(key=lambda x: (-x[1], order.get(x[0].model_id, 99)))
        return res
