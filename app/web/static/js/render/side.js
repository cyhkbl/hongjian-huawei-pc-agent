// 右栏：证据 / 对比 / 修改台。
import { S, on, emit, active } from "../state.js";
import { h, mount, $, fmtTime, PLATFORM_NAME, SCENARIO_NAME, FACT_STATUS, ACTION_NAME } from "../util.js";
import { modelOf } from "../model.js";
import { startRevise } from "../actions.js";
import { badge, btn, extLink } from "./common.js";

const SIDE_TABS = [["evidence", "证据"], ["compare", "策略对比"], ["revise", "修改台"]];
let reviseText = "";

// ---------------------------------------------------------------- evidence
function factCard(f, ref) {
  if (f.missing) return h("div", { class: "ev-fact" }, h("p", { class: "muted", text: `事实 ${f.id} 不在本次证据包里，无法展示原文。` }));
  const dl = h("dl", { class: "src" });
  const add = (k, v) => v && dl.append(h("dt", { text: k }), v instanceof Node ? h("dd", null, v) : h("dd", { text: v }));
  add("型号", f.model);
  add("资料标题", f.source_title);
  add("知识库路径", f.source_path && h("span", { class: "p", text: f.source_path }));
  if (f.source_urls && f.source_urls.length) {
    dl.append(h("dt", { text: "官方链接" }), h("dd", null, f.source_urls.map((u) => h("div", null, extLink(u)))));
  }
  add("核验日期", f.verified_date);
  return h("div", { class: "ev-fact" },
    ref ? badge("mute", ref) : null,
    h("blockquote", { text: f.text }),
    f.constraints && f.constraints.length
      ? h("div", null, h("b", { class: "small", text: "必须带上的限定条件" }), h("ul", { class: "cons" }, f.constraints.map((c) => h("li", { text: c }))))
      : null,
    dl);
}

function evidenceFor(run, key) {
  const m = modelOf(run);
  if (key.startsWith("img:")) {
    const id = key.slice(4);
    const ref = m.imageRef.get(id);
    const chk = m.imageCheck.get(id);
    return h("div", { class: "ev-card pinned" }, h("h3", { text: "配图依据" }),
      ref ? h("dl", { class: "src ev-fact" },
        h("dt", { text: "图片名称" }), h("dd", { text: ref.file_name }),
        h("dt", { text: "型号" }), h("dd", { text: ref.model_name }),
        h("dt", { text: "说明" }), h("dd", { text: ref.caption }),
        h("dt", { text: "插入位置" }), h("dd", { text: ref.position }),
        h("dt", { text: "选图理由" }), h("dd", { text: ref.reason || "—" }),
        h("dt", { text: "知识库路径" }), h("dd", null, h("span", { class: "p", text: ref.kb_path || "—" })),
        h("dt", { text: "图片来源" }), h("dd", null, ref.source_url ? extLink(ref.source_url) : "—"),
        h("dt", { text: "页面来源" }), h("dd", null, ref.page_url ? extLink(ref.page_url) : "—"))
        : h("p", { class: "muted", text: "这张图没有登记信息。" }),
      chk ? h("div", { class: "badges", style: { display: "flex", gap: "6px", marginTop: "10px", flexWrap: "wrap" } },
        badge(chk.model_ok ? "ok" : "bad", "型号一致"), badge(chk.source_ok ? "ok" : "bad", "来源可查"), badge(chk.file_ok ? "ok" : "bad", "文件可读"), badge(chk.aspect_ok ? "ok" : "bad", "原比例")) : null,
      chk && chk.reason ? h("p", { class: "small muted", text: chk.reason }) : null);
  }
  const s = m.byKey.get(key);
  if (!s) return null;
  const card = h("div", { class: `ev-card ${S.pinned && S.pinned.key === key ? "pinned" : ""}` });
  card.append(h("h3", { text: s.ghost ? "被删除的句子" : "这句话的依据" }), h("div", { class: "ev-sent", text: s.text }));

  const c = s.check;
  if (c) {
    card.append(h("div", { style: { marginBottom: "8px", display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" } },
      badge({ pass: "ok", flag: "warn", removed: "bad", rewritten: "info" }[c.status] || "mute", "核验：" + (FACT_STATUS[c.status] || c.status)),
      c.reason ? h("span", { class: "small", text: c.reason }) : null));
    if ((c.status === "rewritten" || c.status === "removed") && (c.before || c.status === "removed")) {
      card.append(h("div", { class: "ev-diff" },
        h("div", { class: "before" }, h("small", { text: "改写前" }), h("del", { text: c.before || c.sentence })),
        c.status === "rewritten" ? h("div", { class: "after" }, h("small", { text: "改写后" }), c.sentence) : h("div", { class: "after" }, h("small", { text: "处理" }), "整句删除，正文里不再出现。")));
    }
  }
  if (s.hits.length) {
    for (const i of s.hits) {
      card.append(h("div", { class: "note-box warn" },
        h("b", { text: i.rule_label || i.rule }), "　",
        badge(i.severity === "block" ? "bad" : "warn", ACTION_NAME[i.action] || i.action),
        h("div", null, "命中：", h("mark", { class: "hit", text: i.text })),
        i.suggestion ? h("div", { class: "small", text: "建议：" + i.suggestion }) : null));
    }
  }
  if (!s.factIds.length) {
    card.append(h("p", { class: "muted", text: s.ghost ? "这句话没有对应的事实，所以被删掉了。" : "这是场景或过渡句，不含产品断言，所以没有对应的事实。" }));
  } else {
    s.factIds.forEach((id) => card.append(factCard(m.factOf(id), m.refOf.get(id))));
  }
  return card;
}

function renderEvidence(run) {
  const wrap = h("div");
  if (!run || !run.article) return h("p", { class: "side-empty", text: "生成稿件后，点正文里的任意一句，这里会显示它依赖的事实、资料标题、知识库路径和官方链接。" });
  const key = (S.pinned && S.pinned.key) || S.hover;
  wrap.append(h("p", { class: "hint-line", text: S.pinned ? "已固定。再点一次同一句取消，Esc 也可以。" : "悬停或聚焦预览，点击固定。" }));
  const card = key ? evidenceFor(run, key) : null;
  if (card) wrap.append(card);
  else wrap.append(h("div", { class: "side-empty" }, h("b", { text: "还没有选中的句子。" }), " 虚线下划线的句子都有事实依据，试试点一句。"));
  const m = modelOf(run);
  const refs = [...m.refOf.entries()];
  if (refs.length) {
    wrap.append(h("details", { class: "fold" }, h("summary", { text: `本稿全部事实（${refs.length}）` }),
      h("ul", null, refs.map(([id, ref]) => h("li", { style: { margin: "6px 0", fontSize: "13px" } }, badge("mute", ref), " ", m.factOf(id).text)))));
  }
  return wrap;
}

// ---------------------------------------------------------------- compare
function sig(run) {
  const st = run.strategy, a = run.article;
  if (!st || !a) return null;
  return {
    platform: PLATFORM_NAME[a.platform] || a.platform,
    scenario: st.scenario_label || SCENARIO_NAME[run.task.scenario] || "",
    audience: st.audience,
    hook: st.hook,
    order: st.selling_points.map((p) => p.label),
    structure: st.structure,
    images: `${(a.image_refs || []).length} 张（计划 ${st.image_count}）`,
    imgSlots: (st.image_slots || []).map((s) => s.slot),
    cta: a.cta || st.cta,
    tone: st.tone,
    length: st.length,
    title: a.title,
  };
}

function listCell(items, otherItems) {
  const other = new Set(otherItems || []);
  return h("ol", null, items.map((x) => h("li", { class: other.has(x) ? "" : "only", text: x })));
}

function compareView() {
  const wrap = h("div");
  const runs = [...S.runs.values()].filter((r) => r.status === "ok" && r.article);
  if (runs.length < 2) {
    wrap.append(h("p", { class: "side-empty" }, h("b", { text: "至少需要两篇稿件。" }), " 同一个产品换场景或换平台再生成一次，就能在这里并排比较切入点、卖点顺序、结构、图数和行动引导。"));
    const cur = active();
    if (cur && cur.status === "ok" && S.options) {
      const quick = h("div", { class: "cmp-quick" }, h("div", { class: "lbl", text: "一键生成对照稿（基于当前稿件）" }));
      const r1 = h("div", { class: "row" });
      const other = S.options.scenarios.filter((s) => s.id !== cur.task.scenario).slice(0, 3);
      other.forEach((s) => r1.append(btn("换成" + s.label, () => { S.side = "revise"; startRevise(`换成${s.label}场景。`, { scenario: s.id }); S.side = "compare"; }, { small: true })));
      quick.append(r1);
      const r2 = h("div", { class: "row" });
      S.options.platforms.filter((p) => cur.article && p.id !== cur.article.platform).forEach((p) => r2.append(btn("换成" + p.label, () => startRevise(`换成${p.label}。`, { platform: p.id }), { small: true })));
      quick.append(r2);
      wrap.append(quick);
    }
    return wrap;
  }
  if (!S.compareA || !S.runs.has(S.compareA)) S.compareA = S.thread.length > 1 ? S.thread[S.thread.length - 2] : runs[runs.length - 2].run_id;
  if (!S.compareB || !S.runs.has(S.compareB)) S.compareB = S.activeId && S.runs.get(S.activeId)?.article ? S.activeId : runs[runs.length - 1].run_id;
  const label = (r, i) => `${i + 1}. ${PLATFORM_NAME[r.article.platform] || ""} · ${(r.strategy && r.strategy.scenario_label) || ""} · ${fmtTime(r.created_at)}`;
  const picker = (id, key, aria) => h("label", { class: "field" }, h("span", { text: aria }),
    h("select", { onchange: (e) => { S[key] = e.target.value; emit("side"); } },
      runs.map((r, i) => h("option", { value: r.run_id, selected: r.run_id === id ? true : null }, label(r, i)))));
  wrap.append(h("div", { class: "cmp-pick" }, picker(S.compareA, "compareA", "A（之前）"),
    h("button", { type: "button", class: "btn small swap", "aria-label": "交换 A 和 B", onclick: () => { [S.compareA, S.compareB] = [S.compareB, S.compareA]; emit("side"); } }, "⇄"),
    picker(S.compareB, "compareB", "B（之后）")));

  const A = sig(S.runs.get(S.compareA)), B = sig(S.runs.get(S.compareB));
  if (!A || !B) { wrap.append(h("p", { class: "side-empty", text: "所选稿件缺少策略信息，无法比较。" })); return wrap; }
  const rows = [
    ["平台", A.platform, B.platform], ["场景", A.scenario, B.scenario], ["受众", A.audience, B.audience],
    ["切入点", A.hook, B.hook], ["卖点顺序", A.order, B.order], ["结构", A.structure, B.structure],
    ["配图", A.images, B.images], ["配图位", A.imgSlots, B.imgSlots], ["行动引导", A.cta, B.cta],
    ["语气", A.tone, B.tone], ["篇幅", A.length, B.length], ["标题", A.title, B.title],
  ];
  const differs = (x, y) => JSON.stringify(x) !== JSON.stringify(y);
  const nd = rows.filter((r) => differs(r[1], r[2])).length;
  wrap.append(h("p", { class: "cmp-sum", text: `${rows.length} 项里有 ${nd} 项不同，已用红色标出。` }));
  const tbl = h("div", { class: "cmp", role: "table", "aria-label": "两次运行的策略对比" },
    h("div", { class: "cmp-row head", role: "row" }, h("div", { role: "columnheader", text: "项目" }), h("div", { role: "columnheader", text: "A" }), h("div", { role: "columnheader", text: "B" })));
  for (const [k, a, b] of rows) {
    const d = differs(a, b);
    const cell = (v, o) => (Array.isArray(v) ? listCell(v, o) : h("div", { text: v || "—" }));
    tbl.append(h("div", { class: `cmp-row ${d ? "diff" : ""}`, role: "row" },
      h("div", { class: "k", role: "rowheader" }, k, d ? h("span", { class: "sr", text: "（有差异）" }) : null),
      h("div", { class: "v", role: "cell" }, cell(a, Array.isArray(b) ? b : null)),
      h("div", { class: "v", role: "cell" }, cell(b, Array.isArray(a) ? a : null))));
  }
  wrap.append(tbl);
  return wrap;
}

// ---------------------------------------------------------------- revise
function reviseView() {
  const run = active();
  const wrap = h("div");
  if (!run || run.status !== "ok") {
    wrap.append(h("p", { class: "side-empty" }, h("b", { text: "先生成一篇稿件。" }), " 之后可以用一句话改：再短一点、删掉价格、换成朋友圈、把续航换成主卖点。改完会重新核验和做合规检查。"));
    return wrap;
  }
  const busy = !!S.running;
  const go = (instr, extra) => { if (!instr.trim() && !extra) return; startRevise(instr, extra || {}); };
  const ta = h("textarea", { id: "rev-text", rows: 3, maxlength: 600, placeholder: "例如：开头别这么正式，再加一句让人到店看看的话。",
    oninput: (e) => { reviseText = e.target.value; },
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(reviseText); } } });
  ta.value = reviseText;
  wrap.append(h("label", { class: "field", for: "rev-text" }, h("span", { text: "想怎么改" }), ta,
    h("div", { class: "help", text: "Enter 提交。改动会生成新版本，旧版本在上方版本链里随时可回看。" })));
  wrap.append(btn(busy ? "修改中…" : "按这句话修改", () => { go(reviseText); reviseText = ""; }, { kind: "primary", ic: "edit", disabled: busy }));

  wrap.append(h("h3", { class: "block-title", text: "快捷修改" }));
  const q = h("div", { class: "quick" });
  for (const s of (S.options && S.options.revise_shortcuts) || []) {
    q.append(h("button", { type: "button", class: "chip", disabled: busy ? true : null, onclick: () => {
      const extra = {};
      if (s.platform) extra.platform = s.platform;
      if (s.selling_point) extra.selling_point = s.selling_point;
      if (s.scenario) extra.scenario = s.scenario;
      go(s.instruction, extra);
    } }, s.label));
  }
  wrap.append(q);

  const chain = S.thread.filter((id) => S.runs.has(id));
  wrap.append(h("h3", { class: "block-title" }, "版本链", h("small", { text: `${chain.length} 个版本` })));
  wrap.append(h("ol", { class: "chain" }, chain.map((id, i) => {
    const r = S.runs.get(id);
    return h("li", { class: id === S.activeId ? "cur" : "" }, h("button", { type: "button", "aria-current": id === S.activeId ? "true" : "false",
      onclick: () => { S.activeId = id; S.pinned = null; emit("article", "side", "task"); } },
    h("b", { text: `v${i + 1}` }), " ", h("span", { text: r.article ? r.article.title : "" }),
    h("div", { class: "note", text: i === 0 ? "初稿" : "改动：" + (r.revision_note || "—") }),
    h("div", { class: "meta", text: [PLATFORM_NAME[r.article && r.article.platform] || "", r.verification ? ({ pass: "核验通过", pass_with_flags: "有提示项", blocked: "已拦截" })[r.verification.verdict] : "", fmtTime(r.created_at)].filter(Boolean).join(" · ") })));
  })));
  return wrap;
}

// ---------------------------------------------------------------- shell
function render() {
  const root = $("#col-side");
  if (!root) return;
  const scroll = root.scrollTop;
  const focusId = document.activeElement && root.contains(document.activeElement) ? document.activeElement.id : "";
  const tabs = h("div", { class: "tabs side-tabs", role: "tablist", "aria-label": "右栏" }, SIDE_TABS.map(([id, name]) => h("button", {
    type: "button", class: "tab", role: "tab", id: "stab-" + id, "aria-selected": S.side === id ? "true" : "false",
    onclick: () => { S.side = id; emit("side"); },
    onkeydown: (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const i = SIDE_TABS.findIndex((t) => t[0] === S.side);
      S.side = SIDE_TABS[(i + (e.key === "ArrowRight" ? 1 : SIDE_TABS.length - 1)) % SIDE_TABS.length][0];
      emit("side");
      requestAnimationFrame(() => $("#stab-" + S.side) && $("#stab-" + S.side).focus());
    },
  }, name)));
  const body = S.side === "compare" ? compareView() : S.side === "revise" ? reviseView() : renderEvidence(active());
  mount(root, tabs, h("div", { class: "side-body", role: "tabpanel", "aria-labelledby": "stab-" + S.side }, body));
  root.scrollTop = scroll;
  if (focusId) { const el = document.getElementById(focusId); if (el) el.focus({ preventScroll: true }); }
}

export function initSide() {
  on("side", render);
  on("progress", () => { if (S.side === "revise") render(); });
  render();
}
