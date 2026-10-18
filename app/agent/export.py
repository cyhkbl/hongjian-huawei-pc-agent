"""导出：md / txt / html（自包含，图片 base64 内联）/ json / docx。png 由前端 canvas 生成。

每种格式都包含统一四段：一、场景判断 二、知识库依据 三、图文软文 四、核验结果。
"""
from __future__ import annotations

import base64
import html as _html
import io
import json
import re
from typing import Optional

from app.models import Article, RunResult

FORMATS = ("md", "txt", "html", "json", "docx")
STATUS_ZH = {"pass": "通过", "flag": "已标注", "removed": "已删除", "rewritten": "已改写"}
VERDICT_ZH = {"pass": "通过", "pass_with_flags": "通过（含标注）", "blocked": "未通过（被拦截）"}


def _safe_name(run: RunResult) -> str:
    t = (run.article.title if run.article else "鸿笺稿件") or "鸿笺稿件"
    t = re.sub(r'[\\/:*?"<>|\r\n]+', "", t).strip()[:30] or "鸿笺稿件"
    return f"{t}-{run.run_id}"


def _need_article(run: RunResult) -> Article:
    if not run.article:
        raise ValueError("该运行没有稿件（可能处于追问或拒绝状态），无法导出")
    return run.article


def _model_names(run: RunResult) -> str:
    ev = run.evidence
    return "、".join(m.name for m in ev.models) if ev and ev.models else "（未确定）"


# --------------------------------------------------------------------------
# 结构化中间表示：[(kind, text)]，md/txt/docx 共用
# --------------------------------------------------------------------------
def _sections(run: RunResult, kb=None) -> dict:
    a = _need_article(run)
    s, ev, v = run.strategy, run.evidence, run.verification
    one = []
    if s:
        one += [("场景", s.scenario_label), ("平台", s.platform_label), ("目标人群", s.audience),
                ("使用场景", s.usage_scene), ("购买阶段", s.purchase_stage), ("内容目标", s.goal),
                ("开场切入", s.hook), ("语气", s.tone), ("篇幅", s.length), ("配图数量", str(s.image_count)),
                ("行动引导", s.cta)]
    one_lists = [("用户痛点", s.pain_points)] if s else []
    rationale = list(s.rationale) if s else []
    sel = [f"第{p.rank}位 {p.label}（{'、'.join(p.fact_ids)}）：{p.why}" for p in s.selling_points] if s else []
    return dict(article=a, one=one, one_lists=one_lists, rationale=rationale, selling=sel, strategy=s, evidence=ev,
                verification=v)


def _block_lines(a: Article) -> list[tuple[str, str]]:
    out = []
    imgs = {r.image_id: r for r in a.image_refs}
    for b in a.blocks:
        if b.kind == "image":
            r = imgs.get(b.image_id)
            out.append(("image", f"[图：{b.text or b.image_id}｜{r.position if r else ''}]"))
        else:
            out.append((b.kind, b.text))
    return out


def _fact_status_counts(v) -> str:
    if not v:
        return ""
    st = v.stats or {}
    return (f"句子 {st.get('sentences', 0)}，有出处 {st.get('cited', 0)}，删除 {st.get('removed', 0)}，"
            f"改写 {st.get('rewritten', 0)}，标注 {st.get('flagged', 0)}；图片通过 {st.get('images_ok', 0)}；"
            f"合规 block {st.get('compliance_blocks', 0)}")


# --------------------------------------------------------------------------
# Markdown / TXT
# --------------------------------------------------------------------------
def to_markdown(run: RunResult, kb=None) -> str:
    d = _sections(run, kb)
    a: Article = d["article"]
    L: list[str] = []
    L.append(f"# {a.title}")
    L.append("")
    L.append(f"> 鸿笺运行档案 {run.run_id}｜{run.created_at}｜机型：{_model_names(run)}")
    if run.engine:
        L.append(f"> 生成方式：{'大模型' if run.engine.writer == 'llm' else '确定性编排器'}"
                 f"{('（' + run.engine.llm_model + '）') if run.engine.llm_model else ''}｜提示词 {run.engine.prompt_version}｜"
                 f"知识库：{run.engine.kb_mode}" + (f"｜{run.engine.note}" if getattr(run.engine, 'note', '') else ""))
    if run.refusal:
        L += ["", f"> 已拒绝的要求：{run.refusal}"]
    L += ["", "## 一、场景判断", ""]
    for k, val in d["one"]:
        L.append(f"- **{k}**：{val}")
    for k, items in d["one_lists"]:
        L.append(f"- **{k}**：" + "；".join(items))
    if d["selling"]:
        L += ["", "卖点排序：", ""] + [f"{i}. {x}" for i, x in enumerate(d["selling"], 1)]
    if d["rationale"]:
        L += ["", "策略理由：", ""] + [f"- {x}" for x in d["rationale"]]
    L += ["", "## 二、知识库依据", ""]
    ev = d["evidence"]
    L.append(f"型号：{_model_names(run)}")
    if a.sources:
        L += ["", "| 编号 | 事实点 | 资料标题 | 日期 |", "|---|---|---|---|"]
        for s in a.sources:
            L.append(f"| {s.ref} | {s.text.replace('|', '／')} | {s.source_title} | {s.verified_date} |")
        urls = []
        for s in a.sources:
            for u in s.source_urls:
                if u not in urls:
                    urls.append(u)
        if urls:
            L += ["", "官方链接："] + [f"- {u}" for u in urls[:8]]
    if ev and ev.trace:
        L += ["", "检索记录：", ""] + [f"- {t.step}｜{t.msg or 'ok'}｜命中 {t.count if t.count is not None else '-'}｜{t.ms}ms｜{t.origin}" for t in ev.trace]
    L += ["", "## 三、图文软文", ""]
    if len(a.titles) > 1:
        L += ["标题备选：", ""] + [f"{i}. {t}" for i, t in enumerate(a.titles, 1)] + [""]
    if a.intro and a.platform != "poster":
        L += [f"> {a.intro}", ""]
    if a.poster:
        p = a.poster
        L += [f"**海报主标题**：{p.get('main_title', '')}", f"**副标题**：{p.get('sub_title', '')}", ""]
        for pt in p.get("points", []):
            L.append(f"- **{pt.get('label', '')}**：{pt.get('text', '')}")
        L += ["", f"活动说明：{p.get('event_note', '')}", f"行动引导：{p.get('cta', '')}", ""]
    imgs = {r.image_id: r for r in a.image_refs}
    for b in a.blocks:
        if b.kind == "heading":
            L += ["", f"### {b.text}", ""] if a.platform != "poster" else []
        elif b.kind == "image":
            r = imgs.get(b.image_id)
            L += ["", f"*【配图】{r.file_name if r else b.image_id}｜{r.position if r else ''}｜{b.text}*", ""]
        elif b.kind == "list":
            L += [f"- {x}" for x in b.text.split("\n") if x.strip()] + [""]
        elif b.kind == "callout":
            L += [f"> {b.text}", ""]
        elif b.kind == "quote":
            L += [f"> {b.text}", ""]
        else:
            if a.platform != "poster":
                L += [b.text, ""]
    if a.platform != "poster":
        L += ["", f"**行动引导**：{a.cta}"]
    if a.hashtags:
        L += ["", " ".join(a.hashtags)]
    if a.price_note:
        L += ["", "价格出处：", ""] + a.price_note.split("\n")
    if a.disclaimers:
        L += [""] + [f"*{x}*" for x in a.disclaimers]
    L += ["", "### 图片清单", ""]
    if a.image_refs:
        L += ["| 图片名 | 型号 | 插入位置 | 说明 | 来源 |", "|---|---|---|---|---|"]
        for r in a.image_refs:
            L.append(f"| {r.file_name} | {r.model_name} | {r.position} | {r.caption} | {r.source_url or r.page_url} |")
    else:
        L.append("（无配图）")
    L += ["", "## 四、核验结果", ""]
    v = d["verification"]
    if v:
        L.append(f"结论：**{VERDICT_ZH.get(v.verdict, v.verdict)}**｜{_fact_status_counts(v)}")
        L += ["", "产品事实核验：", ""]
        for it in v.facts:
            if it.status != "pass":
                L.append(f"- [{STATUS_ZH.get(it.status, it.status)}] {it.sentence}（{it.reason}）")
        if all(it.status == "pass" for it in v.facts):
            L.append("- 全部句子均有出处，未发现需要删改的内容。")
        L += ["", "图片核验：", ""] + [f"- {it.image_id}：型号{'✓' if it.model_ok else '✗'} 来源{'✓' if it.source_ok else '✗'} 文件{'✓' if it.file_ok else '✗'}（{it.reason or '通过'}）" for it in v.images]
        L += ["", "合规检查：", ""]
        L += ([f"- [{c.rule_label}] {c.text} → {c.suggestion}（{c.action}）" for c in v.compliance] or ["- 未发现问题。"])
        L += ["", "待确认信息：", ""] + ([f"- {p}" for p in v.pending] or ["- 无"])
    else:
        L.append("本运行没有核验结果。")
    return "\n".join(L).rstrip() + "\n"


def to_text(run: RunResult, kb=None) -> str:
    md = to_markdown(run, kb)
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.M)
    md = md.replace("**", "").replace("*【", "【").replace("*\n", "\n")
    md = re.sub(r"^\|[-|\s]+\|$\n?", "", md, flags=re.M)
    md = re.sub(r"^\|\s*", "", md, flags=re.M)
    md = md.replace(" | ", "｜").replace(" |", "")
    md = re.sub(r"^> ?", "", md, flags=re.M)
    return md


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
def _img_data_uri(kb, image_id: str) -> str:
    if kb is None:
        return ""
    try:
        data, mime = kb.image_bytes(image_id)
        return f"data:{mime};base64," + base64.b64encode(data).decode()
    except Exception:  # noqa: BLE001
        return ""


def to_html(run: RunResult, kb=None) -> str:
    d = _sections(run, kb)
    a: Article = d["article"]
    esc = _html.escape
    imgs = {r.image_id: r for r in a.image_refs}
    ref_of = {s.fact_id: s.ref for s in a.sources}
    body: list[str] = []
    for b in a.blocks:
        refs = "".join(f'<sup class="ref">{esc(ref_of[i])}</sup>' for i in b.fact_ids if i in ref_of)
        if b.kind == "heading":
            body.append(f"<h3>{esc(b.text)}</h3>")
        elif b.kind == "image":
            r = imgs.get(b.image_id)
            uri = _img_data_uri(kb, b.image_id)
            im = f'<img src="{uri}" alt="{esc(b.text)}">' if uri else '<div class="noimg">（图片未能内联）</div>'
            body.append(f'<figure>{im}<figcaption>{esc(b.text)}｜{esc(r.position if r else "")}｜图片名 {esc(r.file_name if r else b.image_id)}｜'
                        f'来源 {esc((r.source_url or r.page_url) if r else "")}</figcaption></figure>')
        elif b.kind == "list":
            body.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in b.text.split("\n") if x.strip()) + f"</ul>{refs}")
        elif b.kind in ("callout", "quote"):
            body.append(f'<blockquote class="{esc(b.note)}">{esc(b.text)}{refs}</blockquote>')
        else:
            body.append(f"<p>{esc(b.text)}{refs}</p>")
    one = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in d["one"])
    one += "".join(f"<tr><th>{esc(k)}</th><td>{esc('；'.join(v))}</td></tr>" for k, v in d["one_lists"])
    ratio = "".join(f"<li>{esc(x)}</li>" for x in d["rationale"])
    src = "".join(
        f"<tr><td>{esc(s.ref)}</td><td>{esc(s.text)}</td><td>{esc(s.source_title)}</td><td>{esc(s.verified_date)}</td>"
        f"<td>{''.join(f'<a href={chr(34)}{esc(u)}{chr(34)}>链接</a> ' for u in s.source_urls[:1])}</td></tr>" for s in a.sources)
    v = d["verification"]
    vf = ""
    if v:
        vf = (f"<p>结论：<b>{esc(VERDICT_ZH.get(v.verdict, v.verdict))}</b>｜{esc(_fact_status_counts(v))}</p>"
              "<h4>产品事实核验</h4><ul>" + "".join(f"<li>[{esc(STATUS_ZH.get(i.status, i.status))}] {esc(i.sentence)}（{esc(i.reason)}）</li>"
                                                   for i in v.facts if i.status != "pass") + "</ul>"
              "<h4>图片核验</h4><ul>" + "".join(
                  f"<li>{esc(i.image_id)}：型号{'✓' if i.model_ok else '✗'} 来源{'✓' if i.source_ok else '✗'} 文件{'✓' if i.file_ok else '✗'}</li>" for i in v.images) + "</ul>"
              "<h4>合规检查</h4><ul>" + ("".join(f"<li>[{esc(c.rule_label)}] {esc(c.text)} → {esc(c.suggestion)}（{esc(c.action)}）</li>" for c in v.compliance) or "<li>未发现问题。</li>") + "</ul>"
              "<h4>待确认信息</h4><ul>" + ("".join(f"<li>{esc(p)}</li>" for p in v.pending) or "<li>无</li>") + "</ul>")
    poster = ""
    if a.poster:
        p = a.poster
        poster = (f'<section class="poster"><h2>{esc(p.get("main_title", ""))}</h2><p>{esc(p.get("sub_title", ""))}</p>'
                  + "".join(f'<div class="pt"><b>{esc(x.get("label", ""))}</b> {esc(x.get("text", ""))}</div>' for x in p.get("points", []))
                  + f'<p class="ev">{esc(p.get("event_note", ""))}</p><p>{esc(p.get("cta", ""))}</p></section>')
    titles = "".join(f"<li>{esc(t)}</li>" for t in a.titles)
    price = ("<h4>价格出处</h4><ul>" + "".join(f"<li>{esc(x.lstrip('- '))}</li>" for x in a.price_note.split("\n")) + "</ul>") if a.price_note else ""
    tags = f'<p class="tags">{esc(" ".join(a.hashtags))}</p>' if a.hashtags else ""
    disc = "".join(f"<p class='disc'>{esc(x)}</p>" for x in a.disclaimers)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(a.title)}</title>
<style>
body{{font:16px/1.8 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222}}
h1{{font-size:1.6rem}}h2{{border-bottom:1px solid #ddd;padding-bottom:.3rem;margin-top:2.2rem}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{border:1px solid #ddd;padding:.35rem .6rem;text-align:left;vertical-align:top}}
th{{background:#f6f6f6;width:7em}}figure{{margin:1rem 0}}img{{max-width:100%;height:auto;display:block}}
figcaption{{font-size:.8rem;color:#666}}blockquote{{margin:1rem 0;padding:.6rem 1rem;background:#fff8e6;border-left:4px solid #e0a800}}
blockquote.limit{{background:#fdecea;border-color:#c0392b}}.ref{{color:#0a62c4;margin-left:2px}}.poster{{background:#f3f6ff;padding:1rem;border-radius:8px}}
.meta{{color:#777;font-size:.85rem}}.noimg{{padding:2rem;background:#eee;color:#888}}.tags{{color:#0a62c4}}.disc{{font-size:.8rem;color:#777}}
</style></head><body>
<h1>{esc(a.title)}</h1>
<p class="meta">鸿笺运行档案 {esc(run.run_id)}｜{esc(run.created_at)}｜机型：{esc(_model_names(run))}</p>
{('<p class="meta">已拒绝的要求：' + esc(run.refusal) + '</p>') if run.refusal else ''}
<h2>一、场景判断</h2><table>{one}</table><h4>策略理由</h4><ul>{ratio}</ul>
<h2>二、知识库依据</h2><table><tr><th>编号</th><th>事实点</th><th>资料标题</th><th>日期</th><th>链接</th></tr>{src}</table>
<h2>三、图文软文</h2>
<h4>标题备选</h4><ol>{titles}</ol>
{('<p><i>' + esc(a.intro) + '</i></p>') if a.intro and not a.poster else ''}
{poster}
{''.join(body)}
<p><b>行动引导：</b>{esc(a.cta)}</p>{tags}{price}{disc}
<h2>四、核验结果</h2>{vf}
</body></html>"""


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------
def to_docx(run: RunResult, kb=None) -> bytes:
    try:
        from docx import Document
        from docx.shared import Cm, Pt
    except ImportError as e:  # noqa: F841
        raise ImportError("导出 docx 需要 python-docx（请在环境里安装 python-docx==1.2.0）") from None
    d = _sections(run, kb)
    a: Article = d["article"]
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(a.title, 0)
    doc.add_paragraph(f"鸿笺运行档案 {run.run_id}｜{run.created_at}｜机型：{_model_names(run)}")
    if run.refusal:
        doc.add_paragraph(f"已拒绝的要求：{run.refusal}")
    doc.add_heading("一、场景判断", 1)
    for k, val in d["one"]:
        doc.add_paragraph(f"{k}：{val}", style="List Bullet")
    for k, items in d["one_lists"]:
        doc.add_paragraph(f"{k}：" + "；".join(items), style="List Bullet")
    if d["rationale"]:
        doc.add_paragraph("策略理由：")
        for x in d["rationale"]:
            doc.add_paragraph(x, style="List Bullet")
    doc.add_heading("二、知识库依据", 1)
    if a.sources:
        t = doc.add_table(rows=1, cols=4)
        t.style = "Table Grid"
        for i, h in enumerate(["编号", "事实点", "资料标题", "日期"]):
            t.rows[0].cells[i].text = h
        for s in a.sources:
            c = t.add_row().cells
            c[0].text, c[1].text, c[2].text, c[3].text = s.ref, s.text, s.source_title, s.verified_date
    doc.add_heading("三、图文软文", 1)
    if len(a.titles) > 1:
        doc.add_paragraph("标题备选：" + " / ".join(a.titles))
    if a.intro and not a.poster:
        doc.add_paragraph(a.intro)
    if a.poster:
        p = a.poster
        doc.add_paragraph(f"海报主标题：{p.get('main_title', '')}")
        doc.add_paragraph(f"副标题：{p.get('sub_title', '')}")
        for pt in p.get("points", []):
            doc.add_paragraph(f"{pt.get('label', '')}：{pt.get('text', '')}", style="List Bullet")
        doc.add_paragraph(f"活动说明：{p.get('event_note', '')}")
    imgs = {r.image_id: r for r in a.image_refs}
    for b in a.blocks:
        if b.kind == "heading":
            if a.platform != "poster":
                doc.add_heading(b.text, 2)
        elif b.kind == "image":
            r = imgs.get(b.image_id)
            if kb is not None:
                try:
                    data, _m = kb.image_bytes(b.image_id)
                    doc.add_picture(io.BytesIO(data), width=Cm(12))
                except Exception:  # noqa: BLE001
                    doc.add_paragraph("（图片未能内联）")
            doc.add_paragraph(f"图：{b.text}｜{r.position if r else ''}｜{r.file_name if r else b.image_id}｜来源 {(r.source_url or r.page_url) if r else ''}")
        elif b.kind == "list":
            for x in b.text.split("\n"):
                if x.strip():
                    doc.add_paragraph(x, style="List Bullet")
        elif b.kind in ("callout", "quote"):
            doc.add_paragraph(b.text, style="Intense Quote")
        elif a.platform != "poster":
            doc.add_paragraph(b.text)
    doc.add_paragraph(f"行动引导：{a.cta}")
    if a.hashtags:
        doc.add_paragraph(" ".join(a.hashtags))
    if a.price_note:
        doc.add_paragraph("价格出处：")
        for ln in a.price_note.split("\n"):
            doc.add_paragraph(ln.lstrip("- "), style="List Bullet")
    for x in a.disclaimers:
        doc.add_paragraph(x)
    doc.add_heading("四、核验结果", 1)
    v = d["verification"]
    if v:
        doc.add_paragraph(f"结论：{VERDICT_ZH.get(v.verdict, v.verdict)}｜{_fact_status_counts(v)}")
        doc.add_paragraph("产品事实核验：")
        flagged = [i for i in v.facts if i.status != "pass"]
        for it in flagged or []:
            doc.add_paragraph(f"[{STATUS_ZH.get(it.status, it.status)}] {it.sentence}（{it.reason}）", style="List Bullet")
        if not flagged:
            doc.add_paragraph("全部句子均有出处，未发现需要删改的内容。", style="List Bullet")
        doc.add_paragraph("图片核验：")
        for it in v.images:
            doc.add_paragraph(f"{it.image_id}：型号{'✓' if it.model_ok else '✗'} 来源{'✓' if it.source_ok else '✗'} 文件{'✓' if it.file_ok else '✗'}", style="List Bullet")
        doc.add_paragraph("合规检查：")
        for c in v.compliance or []:
            doc.add_paragraph(f"[{c.rule_label}] {c.text} → {c.suggestion}（{c.action}）", style="List Bullet")
        if not v.compliance:
            doc.add_paragraph("未发现问题。", style="List Bullet")
        doc.add_paragraph("待确认信息：")
        for p in v.pending or ["无"]:
            doc.add_paragraph(p, style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
def export(run: RunResult, fmt: str, kb=None) -> tuple[bytes, str, str]:
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise ValueError(f"不支持的导出格式：{fmt}（支持 {', '.join(FORMATS)}；png 由前端生成）")
    name = _safe_name(run)
    if fmt == "md":
        return to_markdown(run, kb).encode("utf-8"), "text/markdown; charset=utf-8", name + ".md"
    if fmt == "txt":
        return to_text(run, kb).encode("utf-8"), "text/plain; charset=utf-8", name + ".txt"
    if fmt == "html":
        _need_article(run)
        return to_html(run, kb).encode("utf-8"), "text/html; charset=utf-8", name + ".html"
    if fmt == "json":
        return run.model_dump_json(indent=1).encode("utf-8"), "application/json", name + ".json"
    _need_article(run)
    return (to_docx(run, kb),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", name + ".docx")
