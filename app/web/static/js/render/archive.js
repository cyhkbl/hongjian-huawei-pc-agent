// “运行档案与自测”页：系统提示词、内置评测集、最近运行。
import { S, on, emit } from "../state.js";
import { h, mount, $, fmtMs, fmtTime, copyText, toast, PLATFORM_NAME, SCENARIO_NAME } from "../util.js";
import { jget, jpost } from "../api.js";
import { openRun, refreshHistory } from "../actions.js";
import { badge, btn, skeleton } from "./common.js";

const A = S.archive;

async function loadPrompt() {
  A.promptError = null;
  emit("archive");
  try { A.prompt = await jget("/api/prompt"); } catch (e) { A.promptError = e.message; }
  emit("archive");
}

async function loadCases() {
  A.casesError = null;
  try { A.cases = (await jget("/api/selftest/cases")).cases || []; } catch (e) { A.casesError = e.message; }
  emit("archive");
}

async function runCase(c) {
  A.results.set(c.id, { pending: true });
  emit("archive");
  try {
    const r = await jpost("/api/selftest/run", { case_id: c.id });
    A.results.set(c.id, r);
  } catch (e) {
    A.results.set(c.id, { error: e.message + (e.hint ? " " + e.hint : "") });
  }
  emit("archive");
}

async function runAll() {
  if (A.running || !A.cases) return;
  A.running = true;
  emit("archive");
  for (const c of A.cases) await runCase(c);
  A.running = false;
  emit("archive");
}

export async function enterArchive() {
  if (!A.prompt && !A.promptError) loadPrompt();
  if (!A.cases && !A.casesError) loadCases();
  refreshHistory();
}

function promptSection() {
  const sec = h("section", { "aria-labelledby": "ar-prompt" }, h("h2", { id: "ar-prompt", text: "系统提示词" }),
    h("p", { class: "lede", text: "写稿时交给大模型的系统提示词全文，包含角色与任务、场景理解、平台规则、知识库约束、图片规则、生成要求、核验规则和合规规则。没有配置大模型时，规则编排路径同样遵守这些约束。" }));
  if (A.promptError) {
    sec.append(h("div", { class: "state error", role: "alert" }, h("h2", { text: "提示词暂时读不到" }), h("p", { text: A.promptError }), h("div", { class: "actions" }, btn("重试", loadPrompt, { kind: "primary", ic: "refresh" }))));
    return sec;
  }
  if (!A.prompt) { sec.append(skeleton(5)); return sec; }
  const p = A.prompt;
  sec.append(h("div", { class: "sumbar" }, badge("info", "版本 " + (p.version || "未标注")), h("span", { class: "muted small", text: `${p.chars} 字` }),
    btn("复制全文", async () => toast((await copyText(p.text)) ? "已复制提示词" : "复制失败", "info"), { small: true, ic: "copy" })));
  if (p.sections && p.sections.length) sec.append(h("div", { class: "chips", style: { marginBottom: "8px" } }, p.sections.slice(0, 12).map((s) => h("span", { class: "badge mute", text: s }))));
  sec.append(h("details", { class: "fold", id: "prompt-fold" }, h("summary", { text: "展开提示词全文" }), h("pre", { class: "prompt-pre", tabindex: "0", text: p.text })));
  return sec;
}

function caseCard(c) {
  const r = A.results.get(c.id);
  const status = !r ? badge("mute", "未运行") : r.pending ? badge("info", "运行中…") : r.error ? badge("bad", "出错") : r.passed ? badge("ok", "通过", true) : badge("bad", "未通过", true);
  const card = h("div", { class: "case", dataset: { case: c.id } },
    h("div", { class: "case-head" }, badge("mute", c.group || "用例"), h("span", { class: "t", text: c.title || c.id }), status,
      btn(r && !r.pending ? "重新运行" : "运行", () => runCase(c), { small: true, ic: "play", disabled: !!(r && r.pending) })));
  const body = h("div", { class: "case-body" });
  const input = typeof c.input === "string" ? c.input : c.input ? JSON.stringify(c.input) : "";
  if (input) body.append(h("div", null, h("b", { text: "输入：" }), input));
  if (c.expect) body.append(h("div", null, h("b", { text: "期望：" }), c.expect));
  if (r && r.error) body.append(h("div", { style: { color: "var(--red-ink)" }, role: "alert", text: r.error }));
  if (r && r.checks) {
    r.checks.forEach((k) => body.append(h("div", { class: "chk-line" }, badge(k.passed ? "ok" : "bad", k.passed ? "通过" : "未通过"), h("span", null, h("b", { text: k.name }), k.detail ? " " + k.detail : ""))));
  }
  if (r && r.evidence) body.append(h("pre", { text: typeof r.evidence === "string" ? r.evidence : JSON.stringify(r.evidence, null, 2) }));
  if (r && r.ms) body.append(h("div", { class: "small muted", text: "耗时 " + fmtMs(r.ms) }));
  if (r && r.run_id) body.append(btn("打开这次运行", () => { S.view = "studio"; emit("view"); openRun(r.run_id); }, { small: true }));
  card.append(body);
  return card;
}

function selftestSection() {
  const sec = h("section", { "aria-labelledby": "ar-test" }, h("h2", { id: "ar-test", text: "Agent 自测台" }),
    h("p", { class: "lede", text: "评委统一测试和参考难题的内置版本：基础生成、换场景、换平台、干扰与修改、想买轻薄本、相近机型、编造价格。每条用例给出通过或失败，以及判断依据。" }));
  if (A.casesError) {
    sec.append(h("div", { class: "state error", role: "alert" }, h("h2", { text: "评测集暂时读不到" }), h("p", { text: A.casesError }), h("div", { class: "actions" }, btn("重试", loadCases, { kind: "primary", ic: "refresh" }))));
    return sec;
  }
  if (!A.cases) { sec.append(skeleton(4)); return sec; }
  if (!A.cases.length) { sec.append(h("p", { class: "muted", text: "评测集是空的。" })); return sec; }
  const done = A.cases.filter((c) => { const r = A.results.get(c.id); return r && !r.pending; });
  const pass = done.filter((c) => A.results.get(c.id).passed).length;
  sec.append(h("div", { class: "sumbar" },
    btn(A.running ? "运行中…" : "一键运行全部", runAll, { kind: "primary", ic: "play", disabled: A.running }),
    done.length ? h("span", { role: "status", id: "selftest-sum" }, badge(pass === done.length ? "ok" : "bad", `${pass}/${done.length} 通过`), h("span", { class: "muted small", text: `（共 ${A.cases.length} 条）` })) : h("span", { class: "muted small", text: `共 ${A.cases.length} 条，运行会真实调用整条链路。` })));
  const groups = new Map();
  A.cases.forEach((c) => { const g = c.group || "其他"; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(c); });
  for (const [g, list] of groups) {
    sec.append(h("h3", { class: "block-title", text: g }));
    list.forEach((c) => sec.append(caseCard(c)));
  }
  return sec;
}

function runsSection() {
  const sec = h("section", { "aria-labelledby": "ar-runs" }, h("h2", { id: "ar-runs", text: "最近的运行" }),
    h("p", { class: "lede", text: "每次运行都有完整档案（任务、策略、证据、稿件、核验、检索记录），不含任何凭证。打开后可在“导出”里下载 JSON。" }));
  if (!S.history.length) { sec.append(h("p", { class: "muted", text: "还没有运行记录。回到工作台生成一篇稿件。" })); return sec; }
  sec.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["时间", "标题", "平台", "场景", "状态", ""].map((x) => h("th", { text: x })))),
    h("tbody", null, S.history.map((r) => h("tr", null, h("td", { text: fmtTime(r.created_at) }), h("td", { text: r.title || "—" }),
      h("td", { text: PLATFORM_NAME[r.platform] || "—" }), h("td", { text: SCENARIO_NAME[r.scenario] || "—" }),
      h("td", { text: ({ ok: "已生成", needs_clarification: "待追问", refused: "已拒绝", blocked: "已拦截" })[r.status] || r.status }),
      h("td", null, btn("打开", () => { S.view = "studio"; emit("view"); openRun(r.run_id); }, { small: true }))))))));
  return sec;
}

function render() {
  const root = $("#archive");
  if (!root || root.hidden) return;
  const scroll = window.scrollY;
  mount(root, h("h2", { style: { fontSize: "var(--fs-xl)" }, text: "运行档案与自测" }), promptSection(), selftestSection(), runsSection());
  window.scrollTo(0, scroll);
}

export function initArchive() {
  on("archive", render);
  on("history", render);
}
export { render as renderArchive };
