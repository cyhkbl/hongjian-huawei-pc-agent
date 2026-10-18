"""Fact and image verification + verdict.

check_facts   sentence-level check of every text block against the Facts it cites
check_images  image refs against the KB image index and the real image bytes
build_verification  verdict + stats

Principles
- A product claim (number / model name / Latin feature token / known function
  term) must be found in the cited Facts of the *article's own model*.
- Unsupported claims are removed, or rewritten down to the wording of the best
  matching Fact. ``before`` always keeps the original sentence.
- Facts of another model never support a sentence (cross-model splicing).
- Fact.constraints travel with the fact: when the block does not carry them,
  they are appended as "（限定：…）".
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

from app.agent.rules_common import (
    alnum_key, cjk_bigrams, dedupe, find_amounts, latin_tokens, nfkc, numbers, segments, split_sentences,
    squash, strip_dates, canon_num,
)
from app.agent.understand import _match_models  # model-name matching shared with task parsing
from app.kb.base import KnowledgeBase
from app.models import (
    Article, Block, EvidencePack, Fact, FactCheckItem, ImageCheckItem, ComplianceIssue,
    PriceRecord, ProductModel, Verification,
)

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
# Concrete function / feature names. A sentence that names one must find it in the cited facts.
FEATURE_TERMS = [
    "多屏协同", "超级终端", "小艺", "智慧多窗", "分屏", "悬浮窗", "星闪", "卫星", "指纹", "人脸识别", "触控笔", "手写笔",
    "M-Pen", "防窥", "柔光", "抗反射", "护眼", "低蓝光", "快充", "反向充电", "双外接屏", "雷电", "HDMI", "SD卡",
    "NFC", "碰一碰", "一碰传", "音频", "扬声器", "麦克风", "摄像头", "键盘背光", "背光键盘", "指关节", "十点触控",
    "触控板", "压感", "全面屏", "折叠", "展开", "UTG", "AI", "鸿蒙", "麒麟", "酷睿", "锐龙", "独显", "核显",
    "WPS", "Office", "Photoshop", "PS", "Premiere", "剪映", "达芬奇", "Final Cut", "AutoCAD", "SolidWorks",
    "游戏", "云游戏", "Linux", "Windows", "Android", "安卓应用", "投屏", "打印", "扩展坞", "电源适配器", "充电器",
]
_FEATURE_TERMS = sorted(set(FEATURE_TERMS), key=len, reverse=True)

_GENERIC_LATIN = {"huawei", "matebook", "pc", "app", "apps", "ok"}
_LIST_MARK_RE = re.compile(r"^\s*(?:[-•·*]|\d{1,2}\s*[.、)）]|[①-⑩])\s*")
_QUALIFIER_RE = re.compile(r"[（(]\s*限定[:：]?\s*([^）)]*)[）)]")
_SENTENCE_END_RE = re.compile(r"[。！？!?…]$")

PLATFORM_IMAGE_MAX = {"wechat_mp": 4, "xiaohongshu": 6, "moments": 3, "poster": 1}
PLATFORM_IMAGE_MIN = {"wechat_mp": 2, "xiaohongshu": 3, "moments": 1, "poster": 1}


# --------------------------------------------------------------------------
# Pools (what the cited facts allow us to say)
# --------------------------------------------------------------------------
@dataclass
class Pool:
    raw: str = ""
    sq: str = ""
    nums: set = field(default_factory=set)
    latin: set = field(default_factory=set)
    bigrams: set = field(default_factory=set)

    def add(self, text: str) -> None:
        self.raw += "\n" + text
        self.sq = squash(self.raw)
        self.nums |= _pool_numbers(text)
        self.latin |= {alnum_key(t) for t in latin_tokens(text)}
        self.bigrams |= cjk_bigrams(text)


def _pool_numbers(text: str) -> set:
    t = nfkc(text)
    out = set(numbers(t))
    # kg <-> g
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(kg|千克|公斤|g|克)\b", t, flags=re.I):
        v = float(num)
        if unit.lower() in ("kg", "千克", "公斤"):
            out.add(canon_num(f"{v * 1000:.3f}"))
        else:
            out.add(canon_num(f"{v / 1000:.4f}"))
    # TB <-> GB
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(tb|gb)\b", t, flags=re.I):
        v = float(num)
        out.add(canon_num(f"{v * 1024 if unit.lower() == 'tb' else v / 1024:.3f}"))
        out.add(canon_num(f"{v * 1000 if unit.lower() == 'tb' else v / 1000:.3f}"))
    return out


def build_pool(texts: list[str]) -> Pool:
    p = Pool()
    for t in texts:
        if t:
            p.add(t)
    return p


def _fact_texts(f: Fact) -> list[str]:
    return [f.text, *f.constraints]


def _model_texts(m: Optional[ProductModel]) -> list[str]:
    if not m:
        return []
    return [m.name, m.short_name, m.series, m.os_label, *m.aliases]


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def _clean_for_claims(sent: str) -> str:
    s = _LIST_MARK_RE.sub("", sent)
    return s


def unsupported_claims(sent: str, pool: Pool, allowed: Pool) -> list[str]:
    """Descriptions of claims in ``sent`` that neither the cited facts nor the model identity back."""
    s = _clean_for_claims(sent)
    out: list[str] = []
    for t in numbers(s):
        if t in pool.nums or t in allowed.nums:
            continue
        out.append(f"数字 {t}")
    for tok in latin_tokens(s):
        k = alnum_key(tok)
        if k in _GENERIC_LATIN or k in pool.latin or k in allowed.latin:
            continue
        if k and (k in pool.sq or k in allowed.sq):
            continue
        out.append(f"术语 {tok}")
    ns = nfkc(s)
    for term in _FEATURE_TERMS:
        if term.lower() in ns.lower():
            k = squash(term)
            if k in pool.sq or k in allowed.sq:
                continue
            out.append(f"功能名 {term}")
            ns = re.sub(re.escape(term), " ", ns, flags=re.I)  # longer terms first, avoid double count
    return dedupe(out)


def has_claim(sent: str, models: list[ProductModel]) -> bool:
    """True when the sentence asserts something about the product (needs a fact)."""
    s = _clean_for_claims(sent)
    if re.search(r"\d+(?:\.\d+)?\s*(?:英寸|寸|Hz|hz|GB|TB|MB|kg|g|克|nits|尼特|mm|cm|ppi|PPI|Wh|W|瓦|小时|分钟|万|核|代|点|路|倍|%|％|K|k|mAh)", s):
        return True
    if re.search(r"\d\s*[:：×xX*]\s*\d", s):
        return True
    if latin_tokens(s) and any(alnum_key(t) not in _GENERIC_LATIN for t in latin_tokens(s)):
        return True
    ns = nfkc(s).lower()
    if any(t.lower() in ns for t in _FEATURE_TERMS):
        return True
    ids, amb, _ = _match_models(s, models)
    return bool(ids or amb)


def _overlap(sent: str, text: str) -> float:
    a, b = cjk_bigrams(sent), cjk_bigrams(text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _num_overlap(sent: str, text: str) -> int:
    return len(set(numbers(_clean_for_claims(sent))) & _pool_numbers(text))


def fact_to_sentence(f: Fact) -> str:
    """Spec lines '键：值' become '键为值'; constraints are appended as 限定."""
    t = nfkc(f.text).strip()
    m = re.match(r"^([^：:]{1,12})[：:]\s*(.+)$", t)
    if m and not re.search(r"[，。；]", m.group(1)):
        t = f"{m.group(1)}为{m.group(2)}"
    t = t.rstrip("。；;，, ") + "。"
    if f.constraints:
        t += "（限定：" + "；".join(c.rstrip("。") for c in f.constraints) + "）"
    return t


# --------------------------------------------------------------------------
# Context for one article
# --------------------------------------------------------------------------
@dataclass
class _Env:
    kb: KnowledgeBase
    evidence: EvidencePack
    models: list[ProductModel]
    main: Optional[str]
    facts: dict[str, Fact]
    missing_fact_ids: set = field(default_factory=set)

    def fact(self, fid: str) -> Optional[Fact]:
        if fid in self.facts:
            return self.facts[fid]
        f = None
        try:
            f = self.kb.get_fact(fid)
        except Exception:  # noqa: BLE001
            f = None
        if f:
            self.facts[fid] = f
        else:
            self.missing_fact_ids.add(fid)
        return f

    def model(self, mid: str) -> Optional[ProductModel]:
        for m in self.models:
            if m.model_id == mid:
                return m
        try:
            return self.kb.get_model(mid)
        except Exception:  # noqa: BLE001
            return None


def _main_model(article: Article, evidence: EvidencePack, env_facts: dict[str, Fact], kb: KnowledgeBase) -> Optional[str]:
    if evidence and evidence.models:
        return evidence.models[0].model_id
    counts: dict[str, int] = {}
    for b in article.blocks:
        for fid in b.fact_ids:
            f = env_facts.get(fid) or kb.get_fact(fid)
            if f:
                counts[f.model_id] = counts.get(f.model_id, 0) + 1
    if counts:
        return max(counts, key=lambda k: counts[k])
    return None


# --------------------------------------------------------------------------
# Sentence verification
# --------------------------------------------------------------------------
@dataclass
class _Res:
    original: str
    text: str                    # final text ("" when removed)
    status: str                  # pass | flag | removed | rewritten
    reason: str = ""
    fact_ids: list = field(default_factory=list)
    line: int = 0
    missing_cons: list = field(default_factory=list)   # 未内联的限定语，统一进文末说明


def _used_facts(sent: str, facts: list[Fact]) -> list[Fact]:
    out = []
    for f in facts:
        if _num_overlap(sent, f.text) > 0 or _overlap(f.text, sent) >= 0.5:
            out.append(f)
    return out


def _best_fact(sent: str, facts: list[Fact]) -> tuple[Optional[Fact], float]:
    best, score = None, 0.0
    for f in facts:
        sc = _overlap(sent, f.text) + 0.3 * _num_overlap(sent, f.text)
        if sc > score:
            best, score = f, sc
    return best, score


def _check_sentence(sent: str, env: _Env, own: list[Fact], foreign: list[Fact], allowed: Pool,
                    has_ids: bool, note: str) -> _Res:
    sent_clean = _clean_for_claims(sent)
    # ---- foreign model name in the sentence
    ids, amb, _ = _match_models(sent_clean, env.models)
    foreign_names = [i for i in ids if env.main and i != env.main]
    foreign_names += [g[0] for g in amb if env.main and env.main not in g]
    if foreign_names:
        nm = env.model(foreign_names[0])
        return _Res(sent, "", "removed",
                    f"句子写到了另一款机型「{nm.short_name if nm else foreign_names[0]}」，与稿件主机型不一致，已删除。")

    own_pool = build_pool([t for f in own for t in _fact_texts(f)])
    claims = unsupported_claims(sent, own_pool, allowed)
    claim_present = has_claim(sent, env.models)

    # ---- cross-model splicing
    if foreign:
        fpool = build_pool([t for f in foreign for t in _fact_texts(f)])
        best_o, so = _best_fact(sent, own)
        best_f, sf = _best_fact(sent, foreign)
        fc = unsupported_claims(sent, fpool, allowed)
        if (claims and len(fc) < len(claims) and sf >= 0.3) or (sf > so + 0.15 and sf >= 0.3):
            fm = env.model(best_f.model_id) if best_f else None
            return _Res(sent, "", "removed",
                        f"句子依据的事实属于另一款机型「{fm.short_name if fm else (best_f.model_id if best_f else '?')}」，"
                        f"与稿件主机型不一致（跨型号拼接），已删除。", fact_ids=[best_f.id] if best_f else [])

    if not has_ids and not own:
        if claim_present:
            return _Res(sent, "", "removed", "句子带有产品数字、型号或功能名，但没有引用任何知识库事实，已删除。")
        return _Res(sent, sent, "pass", "纯场景句，没有产品断言。")

    if env.missing_fact_ids and not own and has_ids:
        if claim_present:
            return _Res(sent, "", "removed", "引用的事实编号在知识库中不存在，无法核对，已删除。")
        return _Res(sent, sent, "pass", "没有产品断言。")

    if not claims:
        used = _used_facts(sent, own)
        return _Res(sent, sent, "pass",
                    "与引用事实一致。" if claim_present else "没有产品断言。",
                    fact_ids=[f.id for f in used] or ([] if not claim_present else [f.id for f in own[:1]]))

    # ---- unsupported claims: prune clauses first
    segs = segments(sent)
    if len(segs) > 1:
        kept, dropped = [], []
        for seg in segs:
            if unsupported_claims(seg, own_pool, allowed):
                dropped.append(seg)
            else:
                kept.append(seg)
        if kept and dropped:
            new = "".join(kept)
            core = re.sub(r"[（(][^）)]*[）)]", "", new)
            if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", core)) >= 6:
                if not _SENTENCE_END_RE.search(new):
                    tail = _SENTENCE_END_RE.search(sent)
                    new = new.rstrip("，,；;、 ") + (tail.group(0) if tail else "。")
                used = _used_facts(new, own)
                return _Res(sent, new, "rewritten",
                            f"删除了知识库里没有依据的分句（{'；'.join(claims)}）。", fact_ids=[f.id for f in used])
    # ---- degrade to the best fact wording
    best, score = _best_fact(sent, own)
    if best is not None and score >= 0.45:
        new = fact_to_sentence(best)
        return _Res(sent, new, "rewritten",
                    f"原句里有知识库没有的内容（{'；'.join(claims)}），已改成知识库事实的原表述。", fact_ids=[best.id])
    return _Res(sent, "", "removed", f"句子里的内容在引用的事实中找不到依据（{'；'.join(claims)}），已删除。")


def _split_lines(text: str) -> list[list[str]]:
    lines = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        lines.append(split_sentences(line))
    return lines


def _check_text_block(block_id: str, text: str, fact_ids: list[str], note: str, env: _Env,
                      pool_fact_ids: Optional[list[str]] = None,
                      kind: str = "para") -> tuple[str, list[Fact], list[_Res], list[str]]:
    """Returns (new text, own facts, results, kept fact ids)."""
    ids_for_pool = pool_fact_ids if pool_fact_ids is not None else fact_ids
    resolved = [env.fact(fid) for fid in ids_for_pool]
    facts = [f for f in resolved if f]
    own = [f for f in facts if (not env.main or f.model_id == env.main)]
    foreign = [f for f in facts if env.main and f.model_id != env.main]
    allowed = Pool()
    main_model = env.model(env.main) if env.main else None
    for t in _model_texts(main_model):
        allowed.add(t)
    for m in env.evidence.models if env.evidence else []:
        if not env.main or m.model_id == env.main:
            for t in _model_texts(m):
                allowed.add(t)

    results: list[_Res] = []
    for li, sentences in enumerate(_split_lines(text)):
        for s in sentences:
            r = _check_sentence(s, env, own, foreign, allowed, bool(fact_ids), note)
            r.line = li
            results.append(r)

    # ---- constraints must travel with the fact
    # 正文不逐段内联限定语：compose.py 会在文末统一加“使用前请注意”。这里只做登记，
    # 由 check_facts 汇总成 pending/dedup 后的统一提示，避免同一段限定在多个段落复读。
    if (note or "").strip() != "limit" and kind != "heading":
        full = squash("".join(r.text for r in results))
        done: set = set()
        for r in results:
            if not r.text or r.status == "removed":
                continue
            for f in _used_facts(r.text, own):
                if f.id in done or not f.constraints or f.kind in ("boundary", "unfit"):
                    continue
                miss = [c for c in f.constraints if squash(c) and squash(c) not in full]
                done.add(f.id)
                for c in miss:
                    r.missing_cons.append(c)
                if miss:
                    r.status = "flag" if r.status == "pass" else r.status

    # ---- rebuild text
    by_line: dict[int, list[str]] = {}
    for r in results:
        if r.text:
            by_line.setdefault(r.line, []).append(r.text)
    new_text = "\n".join("".join(v).strip() for _, v in sorted(by_line.items()) if "".join(v).strip())
    kept_ids = [f.id for f in own] if own else []
    return new_text, own, results, kept_ids


# --------------------------------------------------------------------------
# Price blocks
# --------------------------------------------------------------------------
def _amount_numbers(s: str) -> list[str]:
    out = []
    for a in find_amounts(s):
        n = numbers(a, drop_dates=False)
        if n:
            out.append(n[0])
    return out


def _check_price_block(b: Block, env: _Env) -> tuple[str, list[_Res]]:
    note = (b.note or "").strip()
    ids = [x.strip() for x in note[len("price:"):].split(",") if x.strip()]
    recs: dict[str, PriceRecord] = {p.record_id: p for p in (env.evidence.prices if env.evidence else [])}
    results: list[_Res] = []
    text = b.text
    if ids == ["none"]:
        pool = Pool()
        for t in _model_texts(env.model(env.main) if env.main else None):
            pool.add(t)
        for li, sentences in enumerate(_split_lines(text)):
            for s in sentences:
                if find_amounts(s):
                    results.append(_Res(s, "", "removed", "该机型没有公开金额，不写金额，已删除。", line=li))
                else:
                    results.append(_Res(s, s, "pass", "如实说明官方未公开当前金额。", line=li))
        return _rebuild(results), results
    pool = Pool()
    amounts: set = set()
    bad = [i for i in ids if i not in recs]
    for i in ids:
        p = recs.get(i)
        if not p:
            continue
        if env.main and p.model_id and p.model_id != env.main:
            bad.append(i)
            continue
        for v in (p.amount, p.ref_amount):
            if v is not None:
                amounts.add(canon_num(f"{v:.2f}"))
        pool.add(" ".join([p.product_name, p.spec, p.price_type, p.conditions, p.stock, p.verified_at, p.status, p.category]))
    allowed = Pool()
    for t in _model_texts(env.model(env.main) if env.main else None):
        allowed.add(t)
    for li, sentences in enumerate(_split_lines(text)):
        for s in sentences:
            if not pool.raw:
                results.append(_Res(s, "", "removed", "价格块引用的价格记录不存在，或属于另一款机型，已删除。", line=li))
                continue
            amt = _amount_numbers(s)
            wrong = [a for a in amt if a not in amounts]
            other = [c for c in unsupported_claims(re.sub(r"[¥￥]?\s*\d[\d,]*(?:\.\d+)?\s*(?:元|万元)", " ", s), pool, allowed)
                     if not c.startswith("数字") or True]
            if wrong:
                results.append(_Res(s, "", "removed",
                                    f"金额 {'、'.join(wrong)} 与价格记录不符，已删除。", line=li))
            elif other:
                results.append(_Res(s, "", "removed",
                                    f"句子里有价格记录之外的内容（{'；'.join(other)}），已删除。", line=li))
            else:
                results.append(_Res(s, s, "pass", "金额与价格记录一致。", line=li))
    return _rebuild(results), results


def _rebuild(results: list[_Res]) -> str:
    by_line: dict[int, list[str]] = {}
    for r in results:
        if r.text:
            by_line.setdefault(r.line, []).append(r.text)
    return "\n".join("".join(v).strip() for _, v in sorted(by_line.items()) if "".join(v).strip())


# --------------------------------------------------------------------------
# check_facts
# --------------------------------------------------------------------------
def _items(block_id: str, results: list[_Res], block_fact_ids: list[str]) -> list[FactCheckItem]:
    out = []
    for r in results:
        shown = r.text if r.text else r.original
        out.append(FactCheckItem(
            block_id=block_id, sentence=shown.strip(), status=r.status,  # type: ignore[arg-type]
            fact_ids=list(r.fact_ids) if r.fact_ids else ([] if r.status in ("removed",) else []),
            reason=r.reason,
            before=r.original.strip() if r.status in ("removed", "rewritten", "flag") and r.original.strip() != shown.strip() or r.status == "removed" else ""))
    return out


def check_facts(article: Article, evidence: EvidencePack, kb: KnowledgeBase) -> tuple[Article, list[FactCheckItem], list[str]]:
    art = article.model_copy(deep=True)
    evidence = evidence or EvidencePack(models=[], facts=[], images=[])
    facts = {f.id: f for f in evidence.facts}
    models = list(evidence.models) or list(kb.models())
    # models for name matching must be the complete catalogue
    try:
        catalogue = list(kb.models())
    except Exception:  # noqa: BLE001
        catalogue = models
    main = _main_model(art, evidence, facts, kb)
    env = _Env(kb=kb, evidence=evidence, models=catalogue or models, main=main, facts=facts)
    items: list[FactCheckItem] = []
    pending: list[str] = []
    cited_all: list[str] = []
    new_blocks: list[Block] = []
    removed_n = 0
    cross_notes: list[str] = []
    cons_pending: list[str] = []

    for b in art.blocks:
        if b.kind == "image":
            new_blocks.append(b)
            continue
        note = (b.note or "").strip()
        if note.startswith("price:"):
            text, res = _check_price_block(b, env)
            items.extend(_items(b.id, res, b.fact_ids))
            removed_n += sum(1 for r in res if r.status == "removed")
            if text.strip():
                new_blocks.append(b.model_copy(update={"text": text}))
            continue
        text, own, res, kept = _check_text_block(b.id, b.text, b.fact_ids, note, env, kind=b.kind)
        for r in res:
            cons_pending.extend(r.missing_cons)
        # record foreign facts that were dropped from the citation list
        resolved = [env.fact(fid) for fid in b.fact_ids]
        foreign_ids = [f.id for f in resolved if f and env.main and f.model_id != env.main]
        missing_ids = [fid for fid, f in zip(b.fact_ids, resolved) if f is None]
        for r in res:
            r.fact_ids = [x for x in r.fact_ids if x not in foreign_ids]
        if foreign_ids:
            cross_notes.append(f"{b.id} 引用了其他机型的事实 {', '.join(foreign_ids)}，已从引用中移除")
            if not any(r.status == "removed" and "跨型号" in r.reason for r in res):
                pass
        items.extend(_items(b.id, res, b.fact_ids))
        removed_n += sum(1 for r in res if r.status == "removed")
        if not text.strip():
            continue
        used_ids = dedupe([x for r in res if r.text for x in r.fact_ids])
        keep_ids = [fid for fid in b.fact_ids if fid not in foreign_ids and fid not in missing_ids]
        if b.fact_ids and not keep_ids:
            keep_ids = []
        cited_all.extend(keep_ids)
        new_blocks.append(b.model_copy(update={"text": text, "fact_ids": keep_ids}))
    art.blocks = new_blocks

    # ---- title / intro / cta / poster against the article's own facts
    union_ids = dedupe([x for b in art.blocks for x in b.fact_ids])
    union_note = ""
    for field_name, bid in (("intro", "intro"), ("cta", "cta")):
        txt = getattr(art, field_name)
        if not txt:
            continue
        text, _own, res, _k = _check_text_block(bid, txt, union_ids, union_note, env, kind="para")
        items.extend(_items(bid, res, union_ids))
        removed_n += sum(1 for r in res if r.status == "removed")
        if field_name == "cta" and not text.strip():
            text = "了解更多，请以华为官方渠道的产品页面为准。"
        setattr(art, field_name, text)
    # title
    tt, _own, res, _k = _check_text_block("title", art.title, union_ids, "", env, kind="heading")
    items.extend(_items("title", res, union_ids))
    if not tt.strip():
        alt = None
        for cand in art.titles[1:]:
            ct, _o, rr, _kk = _check_text_block("title", cand, union_ids, "", env, kind="heading")
            if ct.strip() and all(r.status == "pass" for r in rr):
                alt = ct
                break
        tt = alt or art.title
        if not alt:
            items[-1] = items[-1].model_copy(update={"status": "flag", "reason": items[-1].reason + " 没有可替换的备选标题，请人工处理。"})
            pending.append("标题含有知识库没有依据的内容，需要人工改写。")
    if tt != art.title:
        art.titles = [tt] + [t for t in art.titles if t != art.title and t != tt]
        art.title = tt
    # poster points
    if isinstance(art.poster, dict) and isinstance(art.poster.get("points"), list):
        p = dict(art.poster)
        pts = []
        for i, pt in enumerate(p["points"]):
            if not isinstance(pt, dict):
                continue
            q = dict(pt)
            ids = list(q.get("fact_ids") or [])
            txt = str(q.get("text") or "")
            if not txt.strip():
                pts.append(q)
                continue
            text, _own, res, _k = _check_text_block(f"poster:{i + 1}", txt, ids, "", env)
            items.extend(_items("poster", res, ids))
            removed_n += sum(1 for r in res if r.status == "removed")
            if text.strip():
                q["text"] = text
                pts.append(q)
        p["points"] = pts
        for key in ("main_title", "sub_title", "event_note"):
            if isinstance(p.get(key), str) and p[key].strip():
                text, _own, res, _k = _check_text_block(f"poster:{key}", p[key], union_ids, "", env, kind="heading")
                items.extend(_items("poster", res, union_ids))
                p[key] = text if text.strip() else ""
        art.poster = p

    # ---- pending
    if removed_n:
        pending.append(f"有 {removed_n} 句因为知识库里没有依据已删除，如需保留请补充官方资料。")
    pending.extend(f"{n}。" for n in cross_notes[:3])
    if env.missing_fact_ids:
        pending.append("部分引用的事实编号在知识库中找不到，请核对知识库版本：" + "、".join(sorted(env.missing_fact_ids)[:3]) + "。")
    cited = [env.fact(fid) for fid in dict.fromkeys(cited_all)]
    cited = [f for f in cited if f]
    spec_cited = any(f.kind in ("spec", "card") for f in cited)
    if spec_cited and not art.price_note.strip():
        pending.append("具体销售 SKU（颜色、内存与存储组合）稿件没有指定，参数以购买页面所选配置为准。")
    for f in cited:
        for c in f.constraints:
            if re.search(r"SKU|销售款|销售配置|型号版本|以官方|须核验|需核验|待核验", c):
                pending.append(f"{c.rstrip('。')}。")
    # 正文没有内联的限定语在这里汇总，稿件已经在文末统一给出“使用前请注意”
    for c in cons_pending:
        pending.append(f"{c.rstrip('。')}。")
    return art, items, dedupe(pending)


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
def _model_colors(kb: KnowledgeBase, model_id: str) -> set:
    try:
        return {a.color for a in kb.images(model_id) if a.color}
    except Exception:  # noqa: BLE001
        return set()


def _article_text(article: Article) -> str:
    parts = [article.title, article.intro, article.cta, *article.titles, *(b.text for b in article.blocks if b.kind != "image")]
    if isinstance(article.poster, dict):
        for k in ("main_title", "sub_title", "event_note", "cta"):
            if article.poster.get(k):
                parts.append(str(article.poster[k]))
        for p in article.poster.get("points") or []:
            if isinstance(p, dict):
                parts.extend(str(p.get(k) or "") for k in ("label", "text"))
    return "\n".join(x for x in parts if x)


def _infer_main_model(article: Article, kb: KnowledgeBase, model_ids: Optional[list[str]]) -> Optional[str]:
    if model_ids:
        return model_ids[0]
    counts: dict[str, int] = {}
    for b in article.blocks:
        for fid in b.fact_ids:
            try:
                f = kb.get_fact(fid)
            except Exception:  # noqa: BLE001
                f = None
            if f:
                counts[f.model_id] = counts.get(f.model_id, 0) + 1
    if counts:
        return max(counts, key=lambda k: counts[k])
    ids = [r.model_id for r in article.image_refs]
    if ids:
        return max(set(ids), key=ids.count)
    return None


def check_images(article: Article, kb: KnowledgeBase,
                 model_ids: Optional[list[str]] = None) -> tuple[Article, list[ImageCheckItem]]:
    art = article.model_copy(deep=True)
    items: list[ImageCheckItem] = []
    main = _infer_main_model(art, kb, model_ids)
    text = _article_text(art)
    limit = PLATFORM_IMAGE_MAX.get(art.platform, 6)
    seen: set = set()
    ok_ids: list[str] = []
    bad_ids: set = set()
    kept_refs = []
    colors_cache: dict[str, set] = {}

    # image blocks that have no ref are checked too
    ref_ids = {r.image_id for r in art.image_refs}
    orphan_blocks = [b for b in art.blocks if b.kind == "image" and b.image_id and b.image_id not in ref_ids]

    for ref in art.image_refs:
        reasons: list[str] = []
        asset = None
        try:
            asset = kb.get_image(ref.image_id)
        except Exception:  # noqa: BLE001
            asset = None
        source_ok = bool(asset and (asset.source_url or asset.page_url))
        model_ok = bool(asset) and asset.model_id == ref.model_id and (main is None or ref.model_id == main)
        file_ok = False
        aspect_ok = True
        if asset is None:
            reasons.append("图片不在知识库图片索引中")
        else:
            if asset.model_id != ref.model_id:
                reasons.append(f"图片实际属于「{asset.model_id}」，稿件标注为「{ref.model_id}」，型号不一致")
            if main is not None and ref.model_id != main:
                reasons.append(f"图片型号「{ref.model_id}」与稿件主机型「{main}」不一致")
            if main is not None and asset.model_id != main and asset.model_id == ref.model_id:
                model_ok = False
            if not source_ok:
                reasons.append("图片缺少原始来源或页面来源")
            try:
                data, _mime = kb.image_bytes(ref.image_id)
                from PIL import Image
                with Image.open(io.BytesIO(data)) as im:
                    im.load()
                    w, h = im.size
                if w > 0 and h > 0:
                    file_ok = True
                    if asset.width and asset.height:
                        if abs((w / h) - (asset.width / asset.height)) / (asset.width / asset.height) > 0.02:
                            aspect_ok = False
                            reasons.append(f"解码尺寸 {w}×{h} 与索引记录 {asset.width}×{asset.height} 的宽高比不同，需按原比例展示")
                else:
                    reasons.append("图片尺寸异常")
            except KeyError:
                reasons.append("图片文件读取不到")
            except Exception as e:  # noqa: BLE001 - corrupt/undecodable file
                reasons.append(f"图片文件无法解码（{type(e).__name__}）")
            # colour conflict
            if asset.color:
                cs = colors_cache.setdefault(asset.model_id, _model_colors(kb, asset.model_id))
                other = [c for c in cs if c != asset.color and c in text and asset.color not in text]
                mention_other = [c for c in cs if c != asset.color and c in text]
                if other or (mention_other and asset.color not in text):
                    reasons.append(f"图片是「{asset.color}」，文中写的是「{'、'.join(mention_other)}」，颜色冲突")
        if ref.image_id in seen:
            reasons.append("同一张图片重复使用")
        seen.add(ref.image_id)
        if not reasons and len(ok_ids) >= limit:
            reasons.append(f"超过该平台的配图上限（{limit} 张）")
        fatal = [r for r in reasons if "宽高比" not in r]
        status = "fail" if fatal or not (model_ok and source_ok and file_ok) else "pass"
        if status == "pass":
            ok_ids.append(ref.image_id)
            kept_refs.append(ref)
        else:
            bad_ids.add(ref.image_id)
        items.append(ImageCheckItem(
            image_id=ref.image_id, model_ok=model_ok, source_ok=source_ok, file_ok=file_ok, aspect_ok=aspect_ok,
            status=status, reason="；".join(reasons) if reasons else "型号、来源、文件均通过"))

    for b in orphan_blocks:
        asset = None
        try:
            asset = kb.get_image(b.image_id)
        except Exception:  # noqa: BLE001
            asset = None
        items.append(ImageCheckItem(
            image_id=b.image_id, model_ok=False, source_ok=bool(asset and (asset.source_url or asset.page_url)),
            file_ok=False, aspect_ok=True, status="fail", reason="正文里有图片但没有对应的图片引用记录，已移除"))
        bad_ids.add(b.image_id)

    art.image_refs = kept_refs
    art.blocks = [b for b in art.blocks if not (b.kind == "image" and b.image_id in bad_ids)]
    if isinstance(art.poster, dict) and art.poster.get("image_id") in bad_ids:
        p = dict(art.poster)
        p["image_id"] = ""
        art.poster = p
    return art, items


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------
def build_verification(fact_items: list[FactCheckItem], image_items: list[ImageCheckItem],
                       issues: list[ComplianceIssue], pending: list[str], article: Article) -> Verification:
    removed = sum(1 for i in fact_items if i.status == "removed")
    rewritten = sum(1 for i in fact_items if i.status == "rewritten")
    flagged = sum(1 for i in fact_items if i.status == "flag")
    cited = sum(1 for i in fact_items if i.fact_ids)
    images_ok = sum(1 for i in image_items if i.status == "pass")
    c_block = sum(1 for i in issues if i.severity == "block")
    unresolved = [i for i in issues if i.action == "blocked"]
    if unresolved:
        verdict = "blocked"
    elif removed or rewritten or flagged or issues or any(i.status == "fail" for i in image_items):
        verdict = "pass_with_flags"
    else:
        verdict = "pass"
    return Verification(
        facts=fact_items, images=image_items, compliance=issues, pending=dedupe(pending), verdict=verdict,
        stats={
            "sentences": len(fact_items), "cited": cited, "removed": removed, "rewritten": rewritten,
            "flagged": flagged, "images_ok": images_ok, "compliance_blocks": c_block,
        })
