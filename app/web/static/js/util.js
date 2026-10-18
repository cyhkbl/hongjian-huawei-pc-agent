// Small DOM and text helpers. Everything user- or model-supplied goes through
// textContent (via h()), never innerHTML, so generated copy cannot inject markup.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function mount(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  check: "M4 10.5l4 4 8-9",
  x: "M5 5l10 10M15 5L5 15",
  copy: "M7 7V4h9v9h-3M4 7h9v9H4z",
  download: "M10 3v9m0 0l-3.5-3.5M10 12l3.5-3.5M4 16h12",
  refresh: "M16 10a6 6 0 1 1-2-4.5M16 3v4h-4",
  chevron: "M6 8l4 4 4-4",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM14 14l4 4",
  link: "M8.5 11.5l3-3M7 13l-1.5 1.5a3 3 0 0 1-4-4L3 9m10-2l1.5-1.5a3 3 0 0 1 4 4L17 11",
  edit: "M4 16l1-4 9-9 3 3-9 9zM12 5l3 3",
  warn: "M10 3l8 14H2zM10 8v4M10 14.5v.5",
  info: "M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM10 9v5M10 6.5v.5",
  swap: "M4 7h12l-3-3M16 13H4l3 3",
  play: "M6 4l10 6-10 6z",
  image: "M3 4h14v12H3zM3 13l4-4 4 4 2-2 4 4M13 8h.01",
};

export function icon(name, size = 16) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", ICONS[name] || ICONS.info);
  svg.append(p);
  return svg;
}

export function fmtMs(ms) {
  if (ms === undefined || ms === null) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

export function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const END = new Set(["。", "！", "？", "!", "?", "；", ";"]);
const CLOSERS = new Set(["”", "’", "」", "』", "）", ")", "\"", "'"]);

/** Split one line into sentences, keeping punctuation attached. */
export function splitSentences(line) {
  const out = [];
  let buf = "";
  const chars = Array.from(line);
  for (let i = 0; i < chars.length; i++) {
    buf += chars[i];
    if (END.has(chars[i])) {
      while (i + 1 < chars.length && (CLOSERS.has(chars[i + 1]) || END.has(chars[i + 1]))) buf += chars[++i];
      out.push(buf);
      buf = "";
    }
  }
  if (buf.trim()) out.push(buf);
  return out;
}

export const norm = (s) => String(s || "").replace(/\s+/g, "").replace(/[“”"]/g, "");

export function maskSecret(v) {
  const s = String(v || "");
  if (!s) return "";
  if (s.includes("*")) return s;
  return s.length <= 4 ? "****" : "****" + s.slice(-2);
}

const SENSITIVE_KEY = /(key|secret|token|authorization|password|clientid|client_id|media_id|folder_id|kb_id|knowledge_base_id)/i;
export function redact(obj) {
  if (Array.isArray(obj)) return obj.map(redact);
  if (obj && typeof obj === "object") {
    const o = {};
    for (const [k, v] of Object.entries(obj)) o[k] = SENSITIVE_KEY.test(k) ? "****" : redact(v);
    return o;
  }
  return obj;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h("textarea", { "aria-hidden": "true", style: { position: "fixed", opacity: "0", top: "0" } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

let toastTimer;
export function toast(msg, kind = "info") {
  const box = $("#toast");
  if (!box) return;
  box.className = `toast show ${kind}`;
  box.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = "toast"; }, 3200);
}

export function announce(msg) {
  const live = $("#live");
  if (!live) return;
  live.textContent = "";
  setTimeout(() => { live.textContent = msg; }, 30);
}

export const PLATFORM_NAME = { wechat_mp: "公众号", xiaohongshu: "小红书", moments: "门店朋友圈", poster: "门店海报" };
export const SCENARIO_NAME = {
  back_to_school: "开学季", office: "职场办公", creator: "内容创作", home_upgrade: "家庭换新",
  enterprise_procurement: "企业采购", store_visit: "门店到访", new_launch: "新品首发", festival: "节日营销",
};
export const STATUS_NAME = { ok: "已生成", needs_clarification: "需要追问", blocked: "已拦截", refused: "已拒绝" };
export const VERDICT_NAME = { pass: "核验通过", pass_with_flags: "通过，有提示项", blocked: "已拦截" };
export const FACT_STATUS = { pass: "通过", flag: "提示", removed: "已删除", rewritten: "已改写" };
export const ACTION_NAME = { removed: "已删除", rewritten: "已改写", flagged: "已提示", blocked: "已拦截" };
