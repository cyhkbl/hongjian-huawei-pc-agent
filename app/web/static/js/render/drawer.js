// 顶栏 KB 胶囊 + “账号与知识库”抽屉。绝不显示完整 key；对服务端返回的内容再做一层兜底脱敏。
import { S, on } from "../state.js";
import { h, mount, $, icon, fmtMs, maskSecret, redact } from "../util.js";
import { loadKb } from "../actions.js";
import { badge, btn, kvList } from "./common.js";

let open = false;
let opener = null;

function lampState(kb) {
  if (!kb) return "unknown";
  if (!kb.connected) return "bad";
  return kb.mode === "ima" ? "ok" : "local";
}

function pill() {
  const kb = S.kb;
  const lamp = $("#kb-pill .lamp");
  const text = $("#kb-pill-text");
  if (!lamp || !text) return;
  lamp.dataset.state = S.kbLoading && !kb ? "unknown" : lampState(kb);
  if (S.kbLoading && !kb) text.textContent = "知识库连接中";
  else if (S.kbError && !kb) text.textContent = "知识库状态不可用";
  else if (kb) text.textContent = `${kb.mode === "ima" ? "ima" : kb.mode === "local_mirror" ? "本地镜像" : "未连接"} · ${kb.connected ? "已连接" : "未连接"}`;
  $("#kb-pill").setAttribute("aria-label", `账号与知识库：${text.textContent}。打开详情`);
}

function modeLabel(m) { return m === "ima" ? "ima 共享知识库" : m === "local_mirror" ? "本地镜像" : "未连接"; }

function body() {
  const kb = S.kb;
  const box = h("div", { class: "drawer-body" });
  if (S.kbLoading && !kb) { box.append(h("div", { class: "sk" }), h("div", { class: "sk" }), h("div", { class: "sk" })); return box; }
  if (!kb) {
    box.append(h("div", { class: "state error", role: "alert" }, h("h2", { text: "读不到知识库状态" }), h("p", { text: S.kbError || "服务暂时没有返回。" }),
      h("div", { class: "actions" }, btn("重新连接", () => loadKb(true), { kind: "primary", ic: "refresh" }))));
    return box;
  }
  const last = redact(kb.last_response || {});
  const code = last.code;
  box.append(
    h("div", { style: { display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px", flexWrap: "wrap" } },
      h("span", { class: "lamp", "data-state": lampState(kb), "aria-hidden": "true" }),
      h("b", { text: kb.connected ? "已连接" : "未连接" }),
      badge(kb.mode === "ima" ? "ok" : "warn", modeLabel(kb.mode))),
    kb.detail ? h("p", { style: { marginBottom: "12px" }, text: kb.detail }) : null,
    kb.mode !== "ima" ? h("div", { class: "note-box warn" }, "当前读取的是本地镜像，不是 ima 在线接口。状态面板如实显示，不会伪造 ima 返回。") : null);

  box.append(kvList([
    ["当前账号", kb.account_hint ? maskSecret(kb.account_hint) : "未配置（本地镜像不需要）"],
    ["接口密钥", kb.api_key_hint ? maskSecret(kb.api_key_hint) : "未配置"],
    ["知识库", kb.kb_name || "—"],
    ["连接模式", modeLabel(kb.mode)],
    ["资料基线", kb.snapshot_date || "—"],
    ["最近一次返回", Object.keys(last).length ? `code ${code === undefined ? "—" : code} · ${last.msg || "—"}` : "还没有调用记录"],
    ["调用端点", last.endpoint || null],
  ]));

  box.append(h("h3", { class: "block-title", text: "收录数量" }));
  box.append(h("div", { class: "stats" }, [["models", "机型"], ["facts", "事实点"], ["images", "图片"], ["prices", "价格记录"]].map(([k, l]) =>
    h("div", null, h("b", { text: kb[k] ?? 0 }), h("span", { text: l })))));

  box.append(h("h3", { class: "block-title" }, "检索记录", h("small", { text: `${(kb.trace || []).length} 条` })));
  if (!(kb.trace || []).length) box.append(h("p", { class: "muted small", text: "还没有检索。生成一篇稿件后，这里会列出每次知识库调用。" }));
  else box.append(h("ul", { class: "trace" }, kb.trace.map((t) => h("li", null,
    h("div", null, h("span", { class: "step", text: t.step }), " ", badge(t.origin === "ima" ? "ok" : "mute", t.origin === "ima" ? "ima" : "本地"),
      " ", h("span", { class: "muted", text: [t.code == null ? "" : `code ${t.code}`, t.count == null ? "" : `${t.count} 条`, fmtMs(t.ms)].filter(Boolean).join(" · ") })),
    t.msg ? h("div", { class: "small", text: t.msg }) : null,
    t.request && Object.keys(t.request).length ? h("pre", { text: JSON.stringify(redact(t.request), null, 0) }) : null))));

  box.append(h("div", { style: { marginTop: "18px" } },
    btn(S.kbLoading ? "连接中…" : "重新连接", () => loadKb(true), { kind: "primary", ic: "refresh", disabled: S.kbLoading }),
    S.kbError ? h("p", { class: "small", style: { color: "var(--red-ink)", marginTop: "8px" }, role: "alert", text: S.kbError }) : null));
  return box;
}

function render() {
  const dr = $("#kb-drawer");
  if (!dr) return;
  pill();
  if (!open) return;
  const focusReconnect = document.activeElement && dr.contains(document.activeElement);
  mount(dr,
    h("div", { class: "drawer-head" }, h("h2", { id: "kb-title", text: "账号与知识库" }),
      h("button", { type: "button", class: "btn small", id: "kb-close", onclick: closeDrawer, "aria-label": "关闭" }, icon("x", 14), "关闭"))
    , body());
  if (focusReconnect && !dr.contains(document.activeElement)) $("#kb-close").focus();
}

export function openDrawer() {
  open = true;
  opener = document.activeElement;
  $("#kb-drawer").hidden = false;
  $("#kb-scrim").hidden = false;
  $("#kb-pill").setAttribute("aria-expanded", "true");
  render();
  $("#kb-close").focus();
  loadKb(false);
}

export function closeDrawer() {
  if (!open) return false;
  open = false;
  $("#kb-drawer").hidden = true;
  $("#kb-scrim").hidden = true;
  $("#kb-pill").setAttribute("aria-expanded", "false");
  if (opener && opener.focus) opener.focus();
  return true;
}

export function initDrawer() {
  on("pill", pill);
  on("drawer", render);
  $("#kb-pill").addEventListener("click", () => (open ? closeDrawer() : openDrawer()));
  $("#kb-scrim").addEventListener("click", closeDrawer);
  $("#kb-drawer").addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = Array.from($("#kb-drawer").querySelectorAll("button, a[href], input, select, textarea")).filter((x) => !x.disabled);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  pill();
}
