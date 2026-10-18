// “四、核验结果”：产品事实逐句、图片型号、合规命中、待确认信息。
import { S, emit } from "../state.js";
import { h, VERDICT_NAME, FACT_STATUS, ACTION_NAME } from "../util.js";
import { modelOf } from "../model.js";
import { badge } from "./common.js";
import { imgUrl } from "../api.js";

let filter = "all";
const KIND = { pass: "ok", flag: "warn", removed: "bad", rewritten: "info" };

function focusSentence(key) {
  S.pinned = { key };
  S.side = "evidence";
  S.section = "article";
  S.pane = window.matchMedia("(max-width: 1100px)").matches ? "article" : S.pane;
  emit("article", "side", "pane");
  requestAnimationFrame(() => {
    const el = document.querySelector(`[data-key="${CSS.escape(key)}"]`);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.focus({ preventScroll: true }); }
  });
}

export function verifySection(run) {
  const v = run.verification;
  const wrap = h("div", null,
    h("h2", { class: "sec" }, "四、核验结果"),
    h("p", { class: "lead", text: "稿件生成后又过了一遍：事实对不对、图和型号配不配、有没有踩合规线。" }));
  if (!v) {
    wrap.append(h("div", { class: "note-box", text: "这次运行没有走到核验阶段。" }));
    return wrap;
  }
  const m = modelOf(run);
  wrap.append(h("div", { class: "verdict-row" },
    h("span", { class: `verdict ${v.verdict}`, role: "status" }, VERDICT_NAME[v.verdict] || v.verdict),
    h("span", { class: "muted small", text: v.verdict === "pass_with_flags" ? "没有硬伤，但有需要你确认的地方，见下方。" : v.verdict === "blocked" ? "存在无法自动改写的问题，稿件不应直接发布。" : "没有发现需要处理的问题。" })));

  const st = v.stats || {};
  const labels = [["sentences", "核验句数"], ["cited", "有出处"], ["removed", "已删除"], ["rewritten", "已改写"], ["flagged", "提示"], ["images_ok", "图片通过"], ["compliance_blocks", "合规拦截"]];
  const present = labels.filter(([k]) => st[k] !== undefined);
  if (present.length) wrap.append(h("div", { class: "stats" }, present.map(([k, l]) => h("div", null, h("b", { text: st[k] }), h("span", { text: l })))));

  // facts
  const counts = { all: v.facts.length };
  for (const c of v.facts) counts[c.status] = (counts[c.status] || 0) + 1;
  wrap.append(h("h3", { class: "block-title" }, "产品事实逐句核对", h("small", { text: `${v.facts.length} 句` })));
  const bar = h("div", { class: "filterbar", role: "group", "aria-label": "按核验结果筛选" });
  for (const [k, l] of [["all", "全部"], ["pass", "通过"], ["flag", "提示"], ["rewritten", "已改写"], ["removed", "已删除"]]) {
    if (k !== "all" && !counts[k]) continue;
    bar.append(h("button", { type: "button", class: "chip", "aria-pressed": filter === k ? "true" : "false",
      onclick: () => { filter = k; emit("article"); } }, l, h("small", { text: counts[k] || 0 })));
  }
  wrap.append(bar);
  const list = h("div", { class: "factlist" });
  const items = v.facts.filter((c) => filter === "all" || c.status === filter);
  if (!items.length) list.append(h("p", { class: "muted", text: "这一类没有条目。" }));
  for (const c of items) {
    const key = [...m.byKey.values()].find((s) => s.check === c)?.key;
    const row = h("div", { class: "chk", tabindex: key ? "0" : null, role: key ? "button" : null,
      onclick: key ? () => focusSentence(key) : null,
      onkeydown: key ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focusSentence(key); } } : null },
      badge(KIND[c.status] || "mute", FACT_STATUS[c.status] || c.status),
      h("div", { class: "sent" },
        c.status === "removed" ? h("del", { text: c.before || c.sentence }) : c.sentence,
        c.status === "rewritten" && c.before ? h("div", { class: "small muted" }, "原句：", h("del", { text: c.before })) : null),
      c.reason ? h("div", { class: "why", text: c.reason }) : null,
      c.fact_ids && c.fact_ids.length ? h("div", { class: "why small muted", text: "依据：" + c.fact_ids.map((id) => m.refOf.get(id) || id).join("、") }) : null);
    list.append(row);
  }
  wrap.append(list);

  // images
  wrap.append(h("h3", { class: "block-title" }, "图片型号核验", h("small", { text: `${v.images.length} 张` })));
  if (!v.images.length) wrap.append(h("p", { class: "muted", text: "这次没有配图。" }));
  else wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["图片", "型号一致", "来源", "文件", "比例", "结果"].map((x) => h("th", { text: x })))),
    h("tbody", null, v.images.map((c) => {
      const ref = m.imageRef.get(c.image_id);
      return h("tr", null,
        h("td", null, h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
          h("img", { src: imgUrl(c.image_id), alt: "", width: 48, height: 36, style: { objectFit: "contain", background: "#ece6d8", width: "48px", height: "36px" }, loading: "lazy" }),
          h("span", { class: "small", text: ref ? ref.caption : c.image_id }))),
        ...[c.model_ok, c.source_ok, c.file_ok, c.aspect_ok].map((b) => h("td", null, badge(b ? "ok" : "bad", b ? "通过" : "不通过", b ? "check" : "x"))),
        h("td", null, badge(c.status === "pass" ? "ok" : "bad", c.status === "pass" ? "通过" : "已移除"), c.reason ? h("div", { class: "small muted", text: c.reason }) : null));
    })))));

  // compliance
  wrap.append(h("h3", { class: "block-title" }, "合规检查", h("small", { text: `${v.compliance.length} 处命中` })));
  if (!v.compliance.length) wrap.append(h("p", { class: "muted", text: "没有命中绝对化、虚假承诺、价格误导、无依据对比等规则。" }));
  else wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["规则", "命中内容", "处理", "建议"].map((x) => h("th", { text: x })))),
    h("tbody", null, v.compliance.map((i) => h("tr", null,
      h("td", null, h("b", { text: i.rule_label || i.rule }), h("div", null, badge(i.severity === "block" ? "bad" : "warn", i.severity === "block" ? "拦截级" : "提示级"))),
      h("td", null, h("mark", { class: "hit", text: i.text }), i.where ? h("div", { class: "small muted", text: "位置：" + i.where }) : null),
      h("td", { text: ACTION_NAME[i.action] || i.action }), h("td", { text: i.suggestion })))))));

  // pending
  wrap.append(h("h3", { class: "block-title" }, "待确认信息", h("small", { text: `${v.pending.length} 项` })));
  if (!v.pending.length) wrap.append(h("p", { class: "muted", text: "没有需要人工确认的信息。" }));
  else wrap.append(h("ul", { class: "pending" }, v.pending.map((p) => h("li", { text: p }))));
  return wrap;
}
