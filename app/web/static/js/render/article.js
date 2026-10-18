// 中栏“稿件”：状态（空/加载/失败/追问/拒答）与四段页签。
import { S, on, emit, active } from "../state.js";
import { h, mount, $, $$, icon, toast, PLATFORM_NAME, STATUS_NAME } from "../util.js";
import { modelOf, markRuns } from "../model.js";
import { startRun } from "../actions.js";
import { imgUrl } from "../api.js";
import { EXPORTS, doExport } from "../export.js";
import { drawPoster, canvasBlob } from "../poster.js";
import { badge, btn, skeleton, stateCard } from "./common.js";
import { sceneSection, basisSection } from "./sections.js";
import { verifySection } from "./verify.js";

const TABS = [
  ["scene", "一", "场景判断", "场景"],
  ["basis", "二", "知识库依据", "依据"],
  ["article", "三", "图文软文", "软文"],
  ["verify", "四", "核验结果", "核验"],
];
const clarPick = new Map(); // run_id -> {field: value}
let menuOpen = false;

// ---------------------------------------------------------------- pinning
export function setPin(key) {
  S.pinned = key ? { key } : null;
  paintMarks();
  emit("side");
  if (key && window.matchMedia("(min-width: 1101px)").matches === false) {
    // narrow screens: keep reading; the evidence is one tap away in the “证据” pane
    S.side = "evidence";
    const bar = $("#panebar [data-pane='side']");
    if (bar) bar.classList.add("has-new");
  } else if (key) {
    S.side = "evidence";
    emit("side");
  }
}

export function setHover(key) {
  if (S.hover === key) return;
  S.hover = key;
  paintMarks();
  if (!S.pinned) emit("side");
}

function paintMarks() {
  const pin = S.pinned && S.pinned.key;
  for (const el of $$("[data-key]")) {
    const k = el.dataset.key;
    el.classList.toggle("pin", k === pin);
    el.classList.toggle("hv", k === S.hover && k !== pin);
    if (el.hasAttribute("aria-pressed")) el.setAttribute("aria-pressed", k === pin ? "true" : "false");
  }
}

// ---------------------------------------------------------------- sentences
function sentenceEl(s) {
  const cls = ["s"];
  if (s.status === "cited") cls.push("cited");
  if (s.status === "pass" && s.factIds.length) cls.push("cited");
  if (s.status === "flag") cls.push("flag");
  if (s.status === "rewritten") cls.push("rewritten");
  if (s.ghost) cls.push("removed");
  const kids = markRuns(s.text, s.hits).map((r) => (r.issue ? h("mark", { class: "hit", title: `${r.issue.rule_label}：${r.issue.suggestion || ""}` }, r.text) : r.text));
  const el = h("span", {
    class: cls.join(" "), tabindex: "0", role: "button", "aria-pressed": "false", dataset: { key: s.key },
    "aria-label": sentenceLabel(s),
    onclick: (e) => { if (e.target.closest("a")) return; setPin(S.pinned && S.pinned.key === s.key ? null : s.key); },
    onmouseenter: () => setHover(s.key),
    onmouseleave: () => setHover(""),
    onfocus: () => setHover(s.key),
    onblur: () => setHover(""),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPin(s.key); } },
  }, kids);
  return el;
}

function sentenceLabel(s) {
  const parts = [];
  if (s.status === "removed") parts.push("已被核验删除");
  else if (s.status === "rewritten") parts.push("已被核验改写");
  else if (s.status === "flag") parts.push("核验提示");
  if (s.hits.length) parts.push("命中合规规则");
  parts.push(s.factIds.length ? `有 ${s.factIds.length} 条事实依据` : "无产品断言");
  return parts.join("，") + "，按 Enter 查看依据";
}

function linesOf(sec, tag, cls) {
  return sec.lines.map((sents) => h(tag, { class: cls }, sents.map((s, i) => [sentenceEl(s), i < sents.length - 1 ? "" : null])));
}

function ghostEl(g) {
  const why = (g.check && g.check.reason) || (g.hits[0] && g.hits[0].suggestion) || "无依据，已删除";
  return h("div", { class: "ghost-s", tabindex: "0", role: "button", "aria-pressed": "false", dataset: { key: g.key },
    onclick: () => setPin(S.pinned && S.pinned.key === g.key ? null : g.key),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPin(g.key); } },
    onmouseenter: () => setHover(g.key), onmouseleave: () => setHover("") },
    badge("bad", "已删除"), " ", h("del", { text: g.text }), h("span", { class: "why", text: why }));
}

function figureEl(ref, model, fallbackId) {
  const id = ref ? ref.image_id : fallbackId;
  const chk = model.imageCheck.get(id);
  const key = "img:" + id;
  const dl = h("dl", { class: "mi" });
  if (ref) {
    const add = (k, v) => v && dl.append(h("dt", { text: k }), h("dd", { text: v }));
    add("图片名称", ref.file_name);
    add("来源", ref.page_url || ref.source_url || "");
    add("插入位置", ref.position);
    add("型号", ref.model_name);
  }
  const ok = (b) => (b ? "ok" : "bad");
  const fig = h("figure", { class: "fig", tabindex: "0", role: "button", "aria-pressed": "false", dataset: { key },
    onclick: (e) => { if (e.target.closest("a")) return; setPin(S.pinned && S.pinned.key === key ? null : key); },
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPin(key); } } },
    h("div", { class: "fig-img" }, h("img", {
      src: imgUrl(id), alt: (ref && ref.caption) || id, loading: "lazy", decoding: "async",
      onerror: (e) => { const box = e.target.parentElement; box.classList.add("missing"); e.target.replaceWith(h("span", { text: "图片未能加载（知识库里没有这张图）" })); },
    })),
    h("figcaption", null,
      h("div", { class: "cap", text: (ref && ref.caption) || id }), dl,
      h("div", { class: "badges" },
        chk ? [badge(ok(chk.model_ok), "型号", chk.model_ok ? "check" : "x"), badge(ok(chk.source_ok), "来源", chk.source_ok ? "check" : "x"), badge(ok(chk.file_ok), "文件", chk.file_ok ? "check" : "x")]
          : badge("mute", "未核验"),
        ref && ref.origin ? badge("info", ref.origin === "ima" ? "ima 图片" : "本地镜像") : null)));
  return fig;
}

// ---------------------------------------------------------------- article tab
function articleSection(run) {
  const art = run.article;
  const model = modelOf(run);
  const wrap = h("div", null);
  wrap.append(h("h2", { class: "sec" }, "三、图文软文"),
    h("p", { class: "lead", text: `${PLATFORM_NAME[art.platform] || art.platform} · 点任意一句，右侧会显示它依赖的知识库事实。` }));

  if (run.status === "blocked" || (run.verification && run.verification.verdict === "blocked")) {
    wrap.append(h("div", { class: "note-box warn", role: "alert" }, h("b", { text: "这篇稿件被核验拦截。" }), "有无法自动改写的问题，下面的内容不建议直接发布。详情见“四、核验结果”。"));
  }

  if (art.platform === "poster" && art.poster) {
    const canvas = h("canvas", { id: "poster-canvas", role: "img", "aria-label": `海报成品：${art.poster.main_title || art.title}` });
    wrap.append(h("div", { class: "poster-wrap" }, canvas,
      h("div", { class: "poster-tools" }, btn("导出 PNG", () => doExport("png"), { kind: "primary", ic: "download" }))));
    drawPoster(canvas, art, run).catch(() => toast("海报渲染失败", "error"));
  }

  const legend = h("div", { class: "legend", "aria-label": "标注说明" },
    h("span", null, h("i", { class: "s cited" }, "虚线"), "有事实依据"),
    h("span", null, h("i", { class: "s flag" }, "黄线"), "核验提示"),
    h("span", null, h("i", { class: "s rewritten" }, "波浪线"), "已改写"),
    h("span", null, h("i", { class: "s removed" }, "删除线"), "已删除"),
    h("span", null, h("mark", { class: "hit" }, "红框"), "合规命中"),
    h("label", { class: "check", style: { minHeight: "24px" } },
      h("input", { type: "checkbox", checked: S.showMarks ? true : null, onchange: (e) => { S.showMarks = e.target.checked; $("#copy").classList.toggle("marks-off", !S.showMarks); } }), "显示标注"));
  wrap.append(legend);

  const copy = h("article", { class: `copy ${S.showMarks ? "" : "marks-off"}`, id: "copy" });
  const titleBox = h("div", { class: "titles" });
  titleBox.append(h("h3", { class: "title" }, markRuns(art.title, model.titleHits).map((r) => (r.issue ? h("mark", { class: "hit", title: r.issue.rule_label }, r.text) : r.text))));
  if (art.titles && art.titles.length > 1) {
    titleBox.append(h("details", { class: "alt-titles" }, h("summary", { text: `备选标题（${art.titles.length}）` }),
      h("ol", null, art.titles.map((t) => h("li", { text: t })))));
  }
  copy.append(titleBox);

  for (const sec of model.sections) {
    const b = sec.block;
    if (b.intro) {
      if (sec.lines.length) copy.append(h("div", { class: "intro" }, sec.lines.map((sents) => h("p", null, sents.map(sentenceEl)))));
      continue;
    }
    if (b.kind === "image") {
      const ref = model.imageRef.get(b.image_id);
      copy.append(figureEl(ref, model, b.image_id));
    } else if (b.kind === "heading") {
      sec.lines.forEach((sents) => copy.append(h("h4", { class: "sub" }, sents.map(sentenceEl))));
    } else if (b.kind === "list") {
      copy.append(h("ul", { class: "items" }, sec.lines.map((sents) => h("li", null, sents.map(sentenceEl)))));
    } else if (b.kind === "callout") {
      copy.append(h("div", { class: "callout" }, sec.lines.map((sents) => h("p", null, sents.map(sentenceEl)))));
    } else if (b.kind === "quote") {
      copy.append(h("blockquote", null, sec.lines.map((sents) => h("p", null, sents.map(sentenceEl)))));
    } else {
      sec.lines.forEach((sents) => copy.append(h("p", { class: "blk" }, sents.map(sentenceEl))));
    }
    sec.ghosts.forEach((g) => copy.append(ghostEl(g)));
    sec.strays.forEach((r) => copy.append(figureEl(r, model, r.image_id)));
  }

  if (art.cta) {
    copy.append(h("div", { class: "cta" }, markRuns(art.cta, model.ctaHits).map((r) => (r.issue ? h("mark", { class: "hit", title: r.issue.rule_label }, r.text) : r.text))));
  }
  if (art.price_note) copy.append(h("div", { class: "price-note" }, h("b", { text: "价格说明：" }), art.price_note));
  if (art.hashtags && art.hashtags.length) copy.append(h("div", { class: "tags" }, art.hashtags.map((t) => h("span", { text: t }))));
  if (art.disclaimers && art.disclaimers.length) copy.append(h("div", { class: "disc" }, art.disclaimers.map((d) => h("p", { text: d }))));
  wrap.append(copy);
  return wrap;
}

// ---------------------------------------------------------------- states
function emptyState() {
  const ex = S.options && S.options.examples.find((e) => e.kind === "run");
  return h("div", { class: "art-body" }, h("div", { class: "sheet" },
    stateCard({
      title: "还没有稿件", body: "鸿笺会先判断场景和平台，再从知识库里取事实和图片，写完逐句核验，最后做合规检查。",
      list: ["在左边写一句任务，或选好产品、场景、平台。", "信息不够时我会追问，不会替你猜型号。", "生成后点任意一句，右边会显示它的出处。"],
      actions: ex ? [btn("先跑一个示例", () => startRun({ text: ex.text }), { kind: "primary", ic: "play" })] : [],
    })));
}

function runningState() {
  const r = S.running;
  return h("div", { class: "art-body" }, h("div", { class: "sheet", "aria-busy": "true" },
    h("h2", { class: "sec", text: r.label + "…" }),
    h("p", { class: "lead", text: "左侧可以看到每个阶段的耗时。完整一轮通常要几秒到几十秒。" }), skeleton(9)));
}

function errorState() {
  const e = S.error;
  return h("div", { class: "art-body" }, h("div", { class: "sheet" }, stateCard({
    kind: "error", title: "这次没有生成成功", body: e.message + (e.hint ? " " + e.hint : ""),
    actions: [e.retry ? btn("重试", e.retry, { kind: "primary", ic: "refresh" }) : null,
      btn("返回任务台", () => { S.error = null; S.pane = "task"; emit("article", "pane"); }, {})],
  })));
}

function refusedState(run) {
  const blocked = (run.task.blocked_requests || []);
  return h("div", { class: "art-body" }, h("div", { class: "sheet" }, stateCard({
    kind: "refuse", title: "这个任务我不能这样写", body: run.refusal || "任务里有知识库无法支撑的内容。",
    list: blocked.map((b) => "不能写：" + b),
    actions: [btn("改一下任务", () => { S.pane = "task"; emit("pane"); const t = $("#f-text"); if (t) { t.value = run.task.raw || ""; t.focus(); } }, { kind: "primary", ic: "edit" })],
  }), h("p", { class: "muted small", style: { maxWidth: "560px", margin: "0 auto" }, text: "价格、补贴、库存、销量这类信息只能引用知识库里有出处的记录。把这些要求去掉，其余内容仍可以生成。" })));
}

function clarifyState(run) {
  const req0 = S.reqs.get(run.run_id) || { text: run.task.raw || "" };
  if (!clarPick.has(run.run_id)) clarPick.set(run.run_id, {});
  const picks = clarPick.get(run.run_id);
  const cl = run.clarifications || [];

  const send = (extra) => {
    const req = { ...req0, parent_run_id: run.run_id };
    delete req.run_id;
    const all = { ...picks, ...(extra || {}) };
    for (const c of cl) {
      const v = all[c.field + "|" + c.question];
      if (!v) continue;
      if (c.field === "model") req.model_ids = [v];
      else if (c.field === "platform") req.platform = v;
      else if (c.field === "scenario") req.scenario = v;
      else if (c.field === "audience") req.audience = v;
      else {
        const o = (c.options || []).find((x) => x.value === v);
        req.text = ((req.text || "") + " " + (o ? o.label : v)).trim();
      }
    }
    startRun(req);
  };

  const body = h("div", { class: "clar", role: "group", "aria-labelledby": "clar-h" },
    h("h2", { id: "clar-h", text: cl.length > 1 ? `还差 ${cl.length} 个信息` : "还差一个信息" }),
    h("p", { class: "reason", text: "不确定的地方我不替你选，选完会接着做同一个任务。" }));
  if ((run.task.blocked_requests || []).length) {
    body.append(h("div", { class: "note-box warn", id: "clar-blocked", role: "note" },
      h("b", { text: "这些要求不会写进稿件：" }), run.task.blocked_requests.join("；"),
      h("div", { class: "small", text: "知识库里没有出处，或属于虚构体验。其余内容可以继续生成。" })));
  }

  cl.forEach((c, ci) => {
    const id = c.field + "|" + c.question;
    const fs = h("fieldset", null, h("legend", { text: c.question }));
    if (c.reason) fs.append(h("p", { class: "reason", text: c.reason }));
    for (const o of c.options || []) {
      fs.append(h("button", { type: "button", class: "opt", "aria-pressed": picks[id] === o.value ? "true" : "false",
        onclick: () => {
          picks[id] = o.value;
          if (cl.length === 1) send({ [id]: o.value });
          else emit("article");
        } }, h("b", { text: o.label }), o.hint ? h("span", { text: o.hint }) : null));
    }
    if (c.allow_free_text || !(c.options || []).length) {
      const inp = h("input", { type: "text", id: `clar-free-${ci}`, "aria-label": "自己填写", placeholder: "或者自己填写", maxlength: 60 });
      fs.append(h("div", { class: "free" }, inp, btn("确定", () => {
        const v = inp.value.trim();
        if (!v) { inp.focus(); return; }
        picks[id] = v;
        if (cl.length === 1) send({ [id]: v }); else emit("article");
      }, { small: true })));
    }
    body.append(fs);
  });
  if (cl.length > 1) {
    const optional = (c) => c.field === "other" || c.field === "audience";
    const ready = cl.every((c) => optional(c) || picks[c.field + "|" + c.question]);
    const left = cl.filter((c) => !optional(c) && !picks[c.field + "|" + c.question]).length;
    body.append(h("div", { class: "free", style: { alignItems: "center" } },
      btn("继续生成", () => send(), { kind: "primary", ic: "play", disabled: !ready, id: "clar-go" }),
      left ? h("span", { class: "muted small", role: "status", text: `还有 ${left} 项没选` }) : null));
  }
  return h("div", { class: "art-body" }, body);
}

// ---------------------------------------------------------------- header
function header(run) {
  const thread = S.thread.filter((id) => S.runs.has(id));
  const versions = h("div", { class: "versions", role: "group", "aria-label": "版本链" });
  thread.forEach((id, i) => {
    if (i) versions.append(h("span", { class: "arrow", "aria-hidden": "true", text: "→" }));
    const r = S.runs.get(id);
    versions.append(h("button", { type: "button", class: "ver", "aria-current": id === S.activeId ? "true" : "false",
      title: r.revision_note || (r.article && r.article.title) || "",
      onclick: () => { S.activeId = id; S.pinned = null; emit("article", "side", "task"); } }, `v${i + 1}`));
  });
  const canExport = run && run.article;
  const menu = h("div", { class: "menu-wrap" },
    h("button", { type: "button", class: "btn small", id: "export-btn", "aria-haspopup": "menu", "aria-expanded": menuOpen ? "true" : "false", disabled: !run,
      onclick: (e) => { e.stopPropagation(); menuOpen = !menuOpen; renderMenu(); } }, icon("download", 14), "导出"));
  const bar = h("div", { class: "art-bar" },
    h("div", { class: "grow" }, thread.length ? versions : h("span", { class: "muted small", text: run ? (STATUS_NAME[run.status] || "") : "" })),
    run && run.engine ? badge("mute", run.engine.writer === "llm" ? `大模型 ${run.engine.llm_model || ""}`.trim() : "规则编排") : null,
    menu);
  const tabs = h("div", { class: "tabs art-tabs", role: "tablist", "aria-label": "稿件四段" },
    TABS.map(([id, no, name, short]) => h("button", {
      type: "button", class: "tab", role: "tab", id: "tab-" + id, "aria-selected": S.section === id ? "true" : "false", "aria-controls": "tabpanel",
      tabindex: S.section === id ? "0" : "-1", disabled: canExport ? null : (id === "article" || id === "verify" || id === "basis" || id === "scene") && !run ? true : null,
      onclick: () => { S.section = id; emit("article"); },
      onkeydown: (e) => {
        const i = TABS.findIndex((t) => t[0] === S.section);
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          S.section = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length][0];
          emit("article");
          requestAnimationFrame(() => $("#tab-" + S.section) && $("#tab-" + S.section).focus());
        }
      },
    }, h("span", { class: "no", text: no }), h("span", { class: "long", text: name }), h("span", { class: "short sr", text: short }))));
  return h("div", { class: "art-head" }, bar, canExport ? tabs : null);
}

function renderMenu() {
  const old = $(".menu");
  if (old) old.remove();
  const btnEl = $("#export-btn");
  if (btnEl) btnEl.setAttribute("aria-expanded", menuOpen ? "true" : "false");
  if (!menuOpen) return;
  const run = active();
  const isPoster = run && run.article && run.article.platform === "poster";
  const items = EXPORTS.filter((x) => !x.posterOnly || isPoster);
  const m = h("div", { class: "menu", role: "menu", "aria-label": "导出格式" }, items.map((x, i) => [
    i === 1 ? h("hr") : null,
    h("button", { type: "button", role: "menuitem", onclick: () => { menuOpen = false; renderMenu(); doExport(x.id); } }, icon(x.id === "copy" ? "copy" : "download", 14), x.label),
  ]));
  btnEl.parentElement.append(m);
  const first = m.querySelector("button");
  if (first) first.focus();
  m.addEventListener("keydown", (e) => {
    const bs = Array.from(m.querySelectorAll("button"));
    const i = bs.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); bs[(i + bs.length - 1) % bs.length].focus(); }
  });
}

export function closeMenu() {
  if (!menuOpen) return false;
  menuOpen = false;
  renderMenu();
  const b = $("#export-btn");
  if (b) b.focus();
  return true;
}

// ---------------------------------------------------------------- render
function render() {
  const root = $("#col-article");
  if (!root) return;
  const run = active();
  const scroll = root.scrollTop;
  menuOpen = false;
  let body;
  if (S.running) body = runningState();
  else if (S.error) body = errorState();
  else if (!run) body = emptyState();
  else if (run.status === "needs_clarification") body = clarifyState(run);
  else if (run.status === "refused" || (!run.article && run.refusal)) body = refusedState(run);
  else if (!run.article) body = h("div", { class: "art-body" }, h("div", { class: "sheet" }, stateCard({ kind: "error", title: STATUS_NAME[run.status] || "没有稿件", body: "这次运行没有产出稿件。可以换个说法再试一次。" })));
  else {
    const sec = { scene: sceneSection, basis: basisSection, article: articleSection, verify: verifySection }[S.section] || articleSection;
    body = h("div", { class: "art-body" }, h("div", { class: `sheet ${S.section === "basis" || S.section === "verify" ? "wide" : ""}`, role: "tabpanel", id: "tabpanel", "aria-labelledby": "tab-" + S.section, tabindex: "-1" }, sec(run)));
  }
  const showHeader = run || S.thread.length;
  mount(root, showHeader ? header(run && !S.running && !S.error ? run : (run || null)) : h("div", { class: "art-head" }, h("div", { class: "art-bar" }, h("span", { class: "muted small", text: "稿件" }))), body);
  root.scrollTop = S.running ? 0 : scroll;
  paintMarks();
}

export function initArticle() {
  on("article", render);
  render();
  document.addEventListener("click", (e) => { if (menuOpen && !e.target.closest(".menu-wrap")) { menuOpen = false; renderMenu(); } });
}
