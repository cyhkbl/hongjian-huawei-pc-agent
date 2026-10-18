"""Shared helpers for the rules layer (understand / compliance / verify).

Pure functions only. No KB access, no I/O.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Iterable, Optional

# --------------------------------------------------------------------------
# Sentence splitting
# --------------------------------------------------------------------------
_OPEN = "（(【「『《“"
_CLOSE = "）)】」』》”"
_TERMINAL = "。！？!?；;…"
_CLAUSE_SEPS = "，,；;、"


def split_sentences(line: str) -> list[str]:
    """Split one line into sentences, keeping terminal punctuation.

    Bracket-aware: a terminal mark inside （…） never ends a sentence, and a
    trailing "（限定：…）" stays attached to the sentence it qualifies.
    """
    s = line or ""
    out: list[str] = []
    cur = ""
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        cur += ch
        i += 1
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif ch in _TERMINAL and depth == 0:
            while i < n and (s[i] in _TERMINAL or s[i] in _CLOSE):
                cur += s[i]
                i += 1
            # a qualifier group directly after the mark belongs to this sentence
            m = re.match(r"\s*[（(]\s*限定[^）)]*[）)]", s[i:])
            if m:
                cur += m.group(0)
                i += m.end()
                while i < n and s[i] in _TERMINAL:
                    cur += s[i]
                    i += 1
            out.append(cur)
            cur = ""
    if cur.strip():
        out.append(cur)
    return [x for x in out if x.strip()]


def segments(sent: str) -> list[str]:
    """Split at clause separators outside brackets. Separator stays with its left part."""
    segs: list[str] = []
    cur = ""
    depth = 0
    for ch in sent:
        cur += ch
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif ch in _CLAUSE_SEPS and depth == 0:
            segs.append(cur)
            cur = ""
    if cur:
        segs.append(cur)
    return segs

def map_sentences(text: str, fn: Callable[[str], Optional[str]]) -> str:
    """Apply fn to every sentence of every line. fn returns the new sentence, or
    None / "" to drop it. Lines that end up empty are removed."""
    lines_out: list[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        kept = []
        for s in split_sentences(line):
            r = fn(s)
            if r:
                kept.append(r)
        joined = "".join(kept).strip()
        if joined:
            lines_out.append(joined)
    return "\n".join(lines_out)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


_PUNCT_RE = re.compile(r"[\s\u3000，,。.、；;：:！!？?（）()\[\]【】《》<>“”\"'‘’「」『』·\-_—–~～…/\\|]+")


def squash(s: str) -> str:
    """Lower-case, NFKC, strip spaces and punctuation. For substring comparison."""
    return _PUNCT_RE.sub("", nfkc(s).lower())


_DATE_RES = [
    re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"),
    re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]"),
    re.compile(r"\d{4}\s*年"),
]
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def strip_dates(s: str) -> str:
    s = nfkc(s)
    for r in _DATE_RES:
        s = r.sub(" ", s)
    return s


def canon_num(tok: str) -> str:
    ip, _, frac = tok.partition(".")
    ip = ip.lstrip("0") or "0"
    frac = frac.rstrip("0")
    return ip + ("." + frac if frac else "")


def numbers(s: str, drop_dates: bool = True) -> list[str]:
    """Canonical numeric tokens. '14.20' -> '14.2', '1,600' -> '1600', '3:2' -> ['3','2']."""
    s = strip_dates(s) if drop_dates else nfkc(s)
    # thousands separators only: "1,600" -> "1600"; "2080,264 ppi" (a list comma) stays two numbers
    s = re.sub(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])", lambda m: m.group(0).replace(",", ""), s)
    return [canon_num(t) for t in _NUM_RE.findall(s)]


_UNIT_TOKENS = {
    "nits", "nit", "hz", "khz", "gb", "tb", "mb", "kb", "kg", "g", "mm", "cm", "ppi", "wh", "w", "inch", "k",
    "ms", "fps", "mah", "mp", "db", "a", "v", "x", "s", "gen", "ghz", "mhz", "gbps", "mbps", "rpm", "ghz",
}


def latin_tokens(s: str) -> list[str]:
    """Feature-like Latin tokens ('USB-C', 'OLED', 'HDR', 'P3', 'Wi-Fi'), units excluded."""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", nfkc(s))
    out = []
    for t in toks:
        k = t.lower()
        if len(k) < 2 or k in _UNIT_TOKENS:
            continue
        out.append(k)
    return out


def alnum_key(s: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", nfkc(s).lower())


def cjk_bigrams(s: str) -> set[str]:
    chars = re.sub(r"[^\u4e00-\u9fff]", "", nfkc(s))
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


# --------------------------------------------------------------------------
# Model-name patterns (generic, used when no KB is at hand)
# --------------------------------------------------------------------------
MODEL_NAME_RE = re.compile(
    r"(?:HUAWEI\s*|华为\s*)?MateBook\s*(?:Pro\s*S|Pro|Fold|X\s*Pro|X|GT\s*\d*|D\s*\d+(?:\s*SE)?|\d+)"
    r"(?:\s*[（(]?\s*(?:鸿蒙版|酷睿\s*Ultra\s*版?|非凡大师|典藏版)\s*[）)]?)?",
    re.I,
)

# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
AMOUNT_RE = re.compile(
    r"(?:[¥￥]\s*\d[\d,]*(?:\.\d+)?)"
    r"|(?:\d[\d,]*(?:\.\d+)?\s*(?:万元|元(?![素件宇旦])|块钱|rmb|RMB))"
    r"|(?:\d{3,6}\s*起)"
    r"|(?:(?:价格|售价|标价|报价|到手价|页面价|参考价)\s*[:：]?\s*\d{3,6})"
)
# subsidy / discount amounts (dynamic claims, handled by the dynamic_claim rule)
DYN_AMOUNT_RE = re.compile(
    r"(?:国补|补贴|立减|直降|直减|满减|优惠|减免|返现|省|减|抵|返)\s*\d+(?:\.\d+)?\s*(?:元|块|%|折)?"
)


def find_amounts(s: str) -> list[str]:
    return [m.group(0) for m in AMOUNT_RE.finditer(nfkc(s))]


def amount_values(s: str) -> list[str]:
    vals = []
    for a in find_amounts(s):
        for n in numbers(a, drop_dates=False):
            vals.append(n)
    return vals


def dedupe(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out
