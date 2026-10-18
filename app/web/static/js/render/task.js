// 左栏“任务台”：自然语言 + 结构化选择，示例，进度，最近记录。
import { S, on, emit, active } from "../state.js";
import { h, mount, $, icon, fmtMs, fmtTime, toast, PLATFORM_NAME, SCENARIO_NAME } from "../util.js";
import { startRun, startRevise, cancelRun, openRun } from "../actions.js";
import { btn } from "./common.js";

const form = { text: "", model: "", scenario: "", platform: "", audience: "", point: "", price: false };

function opt(value, label, selected) {
  return h("option", { value, selected: selected ? true : null }, label);
}

function buildRequest() {
  const req = { text: form.text.trim() };
  if (form.model) req.model_ids = [form.model];
  if (form.scenario) req.scenario = form.scenario;
  if (form.platform) req.platform = form.platform;
  if (form.audience.trim()) req.audience = form.audience.trim();
  if (form.point.trim()) req.selling_point = form.point.trim();
  if (form.price) req.want_price = true;
  return req;
}

function submit() {
  const req = buildRequest();
  if (!req.text && !req.model_ids && !req.platform && !req.scenario) {
    toast("先写一句要做什么，或者选好产品和平台。", "error");
    $("#f-text") && $("#f-text").focus();
    return;
  }
  startRun(req);
}

function formView(o) {
  const running = !!S.running;
  const text = h("textarea", {
    id: "f-text", rows: 4, maxlength: o.limits.max_text, placeholder: "例如：给 HUAWEI MateBook Pro 写一篇开学季的小红书，面向大学新生。",
    "aria-describedby": "f-text-help",
    oninput: (e) => { form.text = e.target.value; },
    onkeydown: (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey || !e.shiftKey)) { e.preventDefault(); submit(); } },
  });
  text.value = form.text;

  const sel = (id, label, key, items, blank) => h("label", { class: "field", for: id }, h("span", { text: label }),
    h("select", { id, onchange: (e) => { form[key] = e.target.value; } },
      opt("", blank, !form[key]), items.map(([v, l]) => opt(v, l, form[key] === v))));

  const modelItems = o.models.map((m) => [m.model_id, m.short_name || m.name]);

  return h("form", { class: "task-form", onsubmit: (e) => { e.preventDefault(); submit(); }, "aria-label": "新建任务" },
    h("label", { class: "field", for: "f-text" }, h("span", { text: "用一句话说任务" }), text,
      h("div", { class: "help", id: "f-text-help", text: "Enter 提交，Shift+Enter 换行。缺信息时我会追问，不会猜。" })),
    h("details", { class: "fold", open: true },
      h("summary", { text: "或者用选项指定（会覆盖文字里的同类信息）" }),
      sel("f-model", "产品", "model", modelItems, o.models.length ? "未指定，由文字识别" : "产品列表暂时不可用"),
      h("div", { class: "row" },
        sel("f-scenario", "场景", "scenario", o.scenarios.map((s) => [s.id, s.label]), "未指定"),
        sel("f-platform", "平台", "platform", o.platforms.map((p) => [p.id, p.label]), "未指定")),
      h("label", { class: "field", for: "f-aud" }, h("span", { text: "受众" }),
        h("input", { id: "f-aud", type: "text", list: "aud-list", value: form.audience, placeholder: "例如：大学新生", maxlength: 40, oninput: (e) => { form.audience = e.target.value; } }),
        h("datalist", { id: "aud-list" }, o.audiences.map((a) => h("option", { value: a })))),
      h("label", { class: "field", for: "f-point" }, h("span", { text: "主卖点" }),
        h("input", { id: "f-point", type: "text", list: "pt-list", value: form.point, placeholder: "例如：续航", maxlength: 40, oninput: (e) => { form.point = e.target.value; } }),
        h("datalist", { id: "pt-list" }, o.selling_points.map((a) => h("option", { value: a })))),
      h("label", { class: "check" },
        h("input", { type: "checkbox", checked: form.price ? true : null, onchange: (e) => { form.price = e.target.checked; } }),
        "文中写价格（只会写知识库里有出处的价格）")),
    h("div", { class: "row", style: { marginTop: "6px" } },
      running
        ? btn("停止", cancelRun, { kind: "" })
        : h("button", { type: "submit", class: "btn primary block", style: { gridColumn: "1 / -1" } }, icon("play", 14), "生成稿件"),
      running ? h("span", { class: "muted small", role: "status", text: "正在生成，可以随时停止。" }) : null));
}

function examplesView(o) {
  const groups = new Map();
  for (const ex of o.examples) {
    if (!groups.has(ex.category)) groups.set(ex.category, []);
    groups.get(ex.category).push(ex);
  }
  const box = h("div", { class: "examples" });
  for (const [cat, list] of groups) {
    box.append(h("div", { class: "ex-group" }, h("div", { class: "lbl", text: cat }),
      h("div", { class: "chips" }, list.map((ex) => h("button", {
        type: "button", class: `chip ${ex.kind === "revise" ? "revise" : ""}`, title: ex.expect,
        onclick: () => {
          if (ex.kind === "revise") {
            if (active() && active().status === "ok") { S.side = "revise"; S.pane = "side"; emit("side", "pane"); startRevise(ex.text); }
            else { toast("改稿示例需要先有一篇稿件，先点上面的基础示例。", "error"); }
            return;
          }
          form.text = ex.text; form.model = ""; form.scenario = ""; form.platform = "";
          const ta = $("#f-text"); if (ta) ta.value = ex.text;
          ["f-model", "f-scenario", "f-platform"].forEach((id) => { const s = $("#" + id); if (s) s.value = ""; });
          submit();
        },
      }, ex.title)))));
  }
  return h("details", { class: "fold", open: true }, h("summary", { text: "示例任务（点一下直接运行）" }), box);
}

function progressView() {
  const run = S.running;
  const o = S.options;
  const seen = new Map();
  for (const st of run.stages) seen.set(st.stage, st);
  const plan = (o ? o.stages : []).slice();
  for (const st of run.stages) if (!plan.some((p) => p.id === st.stage)) plan.push({ id: st.stage, label: st.label });
  const lastId = run.stages.length ? run.stages[run.stages.length - 1].stage : "";
  const list = h("ol", { class: "stages", "aria-label": "阶段进度" });
  plan.forEach((p) => {
    const st = seen.get(p.id);
    const state = st ? (p.id === lastId ? "active" : "done") : "pending";
    list.append(h("li", { class: `stage ${state}`, "aria-current": state === "active" ? "step" : null },
      h("span", { class: "name", text: (st && st.label) || p.label }),
      h("span", { class: "ms", text: st ? fmtMs(st.ms) : "" }),
      st && st.note ? h("span", { class: "note", text: st.note }) : null));
  });
  return h("div", { class: "run-card", id: "progress-card" },
    h("h3", null, run.label, h("span", { class: "muted small", text: `${seen.size}/${plan.length}` })),
    h("div", { class: "bar", "aria-hidden": "true" }, h("i")), list);
}

function timelineView(run) {
  if (!run || !run.timeline || !run.timeline.length) return null;
  const total = run.timeline.reduce((a, b) => a + (b.ms || 0), 0);
  const list = h("ol", { class: "stages" }, run.timeline.map((st) => h("li", { class: "stage done" },
    h("span", { class: "name", text: st.label }), h("span", { class: "ms", text: fmtMs(st.ms) }),
    st.note ? h("span", { class: "note", text: st.note }) : null)));
  return h("details", { class: "fold run-card" }, h("summary", { text: `本次运行的阶段记录（${fmtMs(total)}）` }), list);
}

function recentView() {
  if (!S.history.length) return null;
  return h("details", { class: "fold" }, h("summary", { text: "最近的运行" }),
    h("ul", { class: "recent" }, S.history.map((r) => h("li", null, h("button", { type: "button", onclick: () => openRun(r.run_id) },
      h("span", { class: "t", text: r.title || "（无标题）" }),
      h("span", { class: "m", text: [fmtTime(r.created_at), PLATFORM_NAME[r.platform] || "", SCENARIO_NAME[r.scenario] || "", ({ ok: "", needs_clarification: "待追问", refused: "已拒绝", blocked: "已拦截" })[r.status] || ""].filter(Boolean).join(" · ") }))))));
}

function render() {
  const root = $("#col-task");
  if (!root) return;
  const o = S.options;
  if (!o) { mount(root, h("h2", { text: "任务台" }), h("div", { class: "sk" }), h("div", { class: "sk" }), h("div", { class: "sk" })); return; }
  const hadFocus = document.activeElement && root.contains(document.activeElement) ? document.activeElement.id : "";
  const scroll = root.scrollTop;
  mount(root,
    h("h2", { text: "任务台" }),
    h("p", { class: "sub", text: "写什么、给谁看、发在哪里。" }),
    formView(o),
    S.running ? progressView() : timelineView(active()),
    h("div", { class: "hr" }), examplesView(o), recentView());
  root.scrollTop = scroll;
  if (hadFocus && S.running === null) { const el = document.getElementById(hadFocus); if (el) el.focus({ preventScroll: true }); }
}

function renderProgress() {
  if (!S.running) return;
  const old = $("#progress-card");
  if (old) old.replaceWith(progressView());
  else render();
}

export function fillForm(patch) { Object.assign(form, patch); }

export function initTask() {
  on("task", render);
  on("options", render);
  on("history", () => { if (!S.running) render(); });
  on("progress", renderProgress);
  render();
}
