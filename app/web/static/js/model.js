// Derived view-model for a run: sentence-level evidence mapping.
// FactCheckItem.sentence is matched back to block text, so every sentence in the
// rendered article knows which Facts it leans on, how verification treated it,
// and which compliance hits fall inside it.
import { splitSentences, norm } from "./util.js";

const cache = new WeakMap();
const TEXT_KINDS = new Set(["heading", "para", "list", "callout", "quote"]);

export function modelOf(run) {
  if (!run) return null;
  let m = cache.get(run);
  if (!m) { m = build(run); cache.set(run, m); }
  return m;
}

function build(run) {
  const art = run.article;
  const ver = run.verification || { facts: [], images: [], compliance: [], pending: [] };
  const ev = run.evidence || { facts: [], images: [], models: [] };
  const factMap = new Map();
  for (const f of ev.facts || []) factMap.set(f.id, f);
  const sourceMap = new Map();
  const refOf = new Map();
  for (const s of (art && art.sources) || []) { sourceMap.set(s.fact_id, s); refOf.set(s.fact_id, s.ref); }
  const modelName = new Map();
  for (const mo of ev.models || []) modelName.set(mo.model_id, mo.name);

  const factOf = (id) => {
    const f = factMap.get(id);
    const s = sourceMap.get(id);
    if (!f && !s) return { id, missing: true };
    return {
      id,
      ref: refOf.get(id) || "",
      text: (f && f.text) || (s && s.text) || "",
      constraints: (f && f.constraints) || [],
      source_title: (f && f.source_title) || (s && s.source_title) || "",
      source_path: (f && f.source_path) || (s && s.source_path) || "",
      source_urls: (f && f.source_urls && f.source_urls.length ? f.source_urls : s && s.source_urls) || [],
      verified_date: (f && f.verified_date) || (s && s.verified_date) || "",
      model: modelName.get(f && f.model_id) || (s && s.model_name) || (f && f.model_id) || "",
      kind: f && f.kind,
    };
  };

  const checksByBlock = new Map();
  for (const c of ver.facts || []) {
    if (!checksByBlock.has(c.block_id)) checksByBlock.set(c.block_id, []);
    checksByBlock.get(c.block_id).push(c);
  }
  const issuesByWhere = new Map();
  for (const i of ver.compliance || []) {
    const k = i.where || "";
    if (!issuesByWhere.has(k)) issuesByWhere.set(k, []);
    issuesByWhere.get(k).push(i);
  }

  const byKey = new Map();
  const sections = [];

  const mkSentence = (blockId, idx, text, block, checks, issues) => {
    const n = norm(text);
    let check = null;
    for (const c of checks) {
      if (c.status === "removed") continue;
      const cn = norm(c.sentence);
      if (!cn) continue;
      if (cn === n || (cn.length >= 4 && (n.includes(cn) || cn.includes(n)))) { check = c; break; }
    }
    let factIds = [];
    if (check) factIds = check.fact_ids && check.fact_ids.length ? check.fact_ids : [];
    else if (block && block.fact_ids) factIds = block.fact_ids;
    const hits = [];
    for (const i of issues) if (i.text && text.includes(i.text)) hits.push(i);
    const s = {
      key: `${blockId}:${idx}`, blockId, idx, text, check, factIds, hits,
      status: check ? check.status : (factIds.length ? "cited" : "plain"),
      refs: factIds.map((id) => refOf.get(id)).filter(Boolean),
    };
    byKey.set(s.key, s);
    return s;
  };

  if (art) {
    const pseudo = [];
    if (art.intro) pseudo.push({ id: "intro", kind: "para", text: art.intro, fact_ids: [], intro: true });
    const blocks = pseudo.concat(art.blocks || []);
    const imgBlocks = new Set(blocks.filter((b) => b.kind === "image").map((b) => b.image_id));
    const strays = (art.image_refs || []).filter((r) => !imgBlocks.has(r.image_id));
    for (const b of blocks) {
      const checks = checksByBlock.get(b.id) || [];
      const issues = (issuesByWhere.get(b.id) || []).concat(issuesByWhere.get("") || []);
      const sec = { block: b, lines: [], ghosts: [], strays: [] };
      // sentences the verifier deleted: not in the text any more, shown as struck-through ghosts
      checks.filter((c) => c.status === "removed").forEach((c, gi) => {
        const g = { key: `${b.id}:g${gi}`, blockId: b.id, idx: -1, text: c.before || c.sentence, check: c,
          factIds: c.fact_ids || [], hits: issues.filter((i) => i.text && (c.before || c.sentence || "").includes(i.text)),
          status: "removed", ghost: true,
          refs: (c.fact_ids || []).map((id) => refOf.get(id)).filter(Boolean) };
        byKey.set(g.key, g);
        sec.ghosts.push(g);
      });
      // compliance deletions whose text is already gone from the block
      issues.filter((i) => (i.action === "removed" || i.action === "blocked") && i.text && !(b.text || "").includes(i.text)
        && !sec.ghosts.some((g) => g.text.includes(i.text)) && (i.where || "") === b.id).forEach((i, gi) => {
        const g = { key: `${b.id}:c${gi}`, blockId: b.id, idx: -1, text: i.text, check: null, factIds: [],
          hits: [i], status: "removed", ghost: true, refs: [], complianceOnly: true };
        byKey.set(g.key, g);
        sec.ghosts.push(g);
      });
      if (TEXT_KINDS.has(b.kind)) {
        let idx = 0;
        const lines = b.kind === "list" ? b.text.split("\n").filter((x) => x.trim()) : b.text.split("\n");
        for (const line of lines) {
          if (!line.trim()) continue;
          sec.lines.push(splitSentences(line).map((t) => mkSentence(b.id, idx++, t, b, checks, issues)));
        }
      }
      if (b.kind !== "image") {
        sec.strays = strays.filter((r) => r.after_block === b.id);
      }
      sections.push(sec);
    }
    // images that name a block we do not have: put them at the end
    const placed = new Set(sections.flatMap((s) => s.strays.map((r) => r.image_id)));
    const orphan = strays.filter((r) => !placed.has(r.image_id));
    if (orphan.length && sections.length) sections[sections.length - 1].strays.push(...orphan);
  }

  const titleHits = (issuesByWhere.get("title") || []);
  const ctaHits = (issuesByWhere.get("cta") || []);
  const imageRef = new Map(((art && art.image_refs) || []).map((r) => [r.image_id, r]));
  const imageCheck = new Map((ver.images || []).map((c) => [c.image_id, c]));

  return { sections, byKey, factOf, titleHits, ctaHits, imageRef, imageCheck, refOf, modelName };
}

/** Split text into [{text, issue?}] runs so compliance hits can be wrapped in <mark>. */
export function markRuns(text, issues) {
  const spans = [];
  for (const issue of issues || []) {
    if (!issue.text) continue;
    const at = text.indexOf(issue.text);
    if (at >= 0) spans.push({ start: at, end: at + issue.text.length, issue });
  }
  spans.sort((a, b) => a.start - b.start);
  const out = [];
  let pos = 0;
  for (const sp of spans) {
    if (sp.start < pos) continue;
    if (sp.start > pos) out.push({ text: text.slice(pos, sp.start) });
    out.push({ text: text.slice(sp.start, sp.end), issue: sp.issue });
    pos = sp.end;
  }
  if (pos < text.length) out.push({ text: text.slice(pos) });
  return out;
}

/** Plain-text version of the article (what “复制正文” puts on the clipboard). */
export function plainText(run) {
  const a = run && run.article;
  if (!a) return "";
  const out = [a.title];
  if (a.platform === "poster" && a.poster) {
    const p = a.poster;
    out.push(p.sub_title || "", ...(p.points || []).map((x) => `${x.label}：${x.text}`), p.event_note || "", p.cta || "");
    return out.filter(Boolean).join("\n");
  }
  if (a.intro) out.push("", a.intro);
  for (const b of a.blocks || []) {
    if (b.kind === "image") continue;
    if (b.kind === "heading") out.push("", b.text);
    else if (b.kind === "list") out.push(...b.text.split("\n").filter(Boolean).map((x) => "· " + x));
    else out.push(b.text);
  }
  if (a.cta) out.push("", a.cta);
  if (a.hashtags && a.hashtags.length) out.push("", a.hashtags.join(" "));
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}
