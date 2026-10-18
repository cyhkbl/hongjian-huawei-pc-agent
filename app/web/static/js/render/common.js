import { h, icon } from "../util.js";

export function badge(kind, text, withIcon) {
  return h("span", { class: `badge ${kind}` }, withIcon ? icon(withIcon === true ? (kind === "bad" ? "x" : "check") : withIcon, 12) : null, text);
}

export function skeleton(lines = 6) {
  const box = h("div", { class: "sk-box", "aria-hidden": "true" });
  for (let i = 0; i < lines; i++) box.append(h("div", { class: "sk", style: { width: i === 0 ? "55%" : i % 3 === 2 ? "80%" : "100%" } }));
  return box;
}

export function stateCard({ kind = "", title, body, actions = [], list = [] }) {
  return h("div", { class: `state ${kind}`, role: kind === "error" ? "alert" : "status" },
    h("h2", { text: title }),
    body ? h("p", { text: body }) : null,
    list.length ? h("ul", null, list.map((x) => h("li", { text: x }))) : null,
    actions.length ? h("div", { class: "actions" }, actions) : null);
}

export function btn(label, onClick, { kind = "", ic = "", title = "", disabled = false, small = false, id = "" } = {}) {
  return h("button", {
    type: "button", id: id || null, class: `btn ${kind} ${small ? "small" : ""}`.trim(), onclick: onClick, title, disabled,
  }, ic ? icon(ic, 14) : null, label);
}

export function kvList(pairs) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of pairs) {
    if (v === undefined || v === null || v === "") continue;
    dl.append(h("dt", { text: k }), h("dd", null, v));
  }
  return dl;
}

export function extLink(url, label) {
  return h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label || url });
}
