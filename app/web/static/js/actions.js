// User actions that talk to the server and move state forward.
import { jget, jpost, stream, ApiFail } from "./api.js";
import { S, emit, active } from "./state.js";
import { announce, toast } from "./util.js";

function beginRunning(kind, label) {
  S.running = { kind, label, stages: [], startedAt: performance.now() };
  S.error = null;
  emit("task", "article", "side");
}

function fail(e, retry) {
  S.running = null;
  if (e && e.name === "AbortError") { emit("task", "article"); return; }
  const f = e instanceof ApiFail ? e : new ApiFail("unknown", "出了点问题", "请重试一次。");
  S.error = { message: f.message, hint: f.hint, code: f.code, retry: f.retryable ? retry : retry };
  announce("生成失败：" + f.message);
  emit("task", "article", "side");
}

function accept(run, req, { revise = false, replaceId = "" } = {}) {
  S.runs.set(run.run_id, run);
  S.reqs.set(run.run_id, req);
  S.running = null;
  S.error = null;
  if (revise) {
    if (!S.thread.includes(run.run_id)) S.thread.push(run.run_id);
  } else if (replaceId && S.thread[S.thread.length - 1] === replaceId) {
    S.thread[S.thread.length - 1] = run.run_id;
  } else {
    S.thread = [run.run_id];
  }
  S.activeId = run.run_id;
  S.pinned = null;
  S.hover = null;
  if (run.status === "ok") S.section = S.section || "article";
  S.pane = "article";
  announce({ ok: "稿件已生成", needs_clarification: "需要补充信息", refused: "这个任务被拒绝了", blocked: "稿件被拦截" }[run.status] || "完成");
  emit("task", "article", "side", "pane");
  refreshHistory();
}

let ctl = null;
function abortable() {
  if (ctl) ctl.abort();
  ctl = new AbortController();
  return ctl.signal;
}
function settled() { ctl = null; }

export function cancelRun() {
  if (ctl) ctl.abort();
  ctl = null;
  S.running = null;
  emit("task", "article");
}

export async function startRun(req) {
  const replaceId = req.parent_run_id || "";
  beginRunning("run", "正在生成");
  S.pane = "article";
  emit("pane");
  const retry = () => startRun(req);
  try {
    const run = await stream("/api/run/stream", req, {
      signal: abortable(),
      onStage: (st) => { if (S.running) { S.running.stages.push(st); emit("progress"); } },
    });
    settled();
    accept(run, req, { replaceId });
  } catch (e) { settled(); fail(e, retry); }
}

export async function startRevise(instruction, extra = {}) {
  const cur = active();
  if (!cur || cur.status !== "ok") { toast("先生成一篇稿件，再来改。", "error"); return null; }
  const req = { run_id: cur.run_id, instruction, ...extra };
  beginRunning("revise", "正在修改");
  S.pane = "article";
  emit("pane");
  const retry = () => startRevise(instruction, extra);
  try {
    const run = await stream("/api/revise/stream", req, {
      signal: abortable(),
      onStage: (st) => { if (S.running) { S.running.stages.push(st); emit("progress"); } },
    });
    settled();
    accept(run, req, { revise: true });
    return run;
  } catch (e) { settled(); fail(e, retry); return null; }
}

export async function loadRun(id) {
  if (S.runs.has(id)) return S.runs.get(id);
  const run = await jget("/api/runs/" + encodeURIComponent(id));
  S.runs.set(id, run);
  return run;
}

export async function openRun(id) {
  try {
    const run = await loadRun(id);
    // rebuild the thread by walking parents we know about
    const chain = [run.run_id];
    let p = run.parent_run_id;
    for (let guard = 0; p && guard < 20; guard++) {
      let parent = S.runs.get(p);
      if (!parent) { try { parent = await loadRun(p); } catch { break; } }
      if (parent.status !== "ok") break;
      chain.unshift(p);
      p = parent.parent_run_id;
    }
    S.thread = chain;
    S.activeId = id;
    S.pinned = null;
    S.error = null;
    S.pane = "article";
    emit("task", "article", "side", "pane");
  } catch (e) {
    toast(e.message || "打开失败", "error");
  }
}

export async function refreshHistory() {
  try {
    const d = await jget("/api/runs?limit=12");
    S.history = d.runs || [];
    emit("history");
  } catch { /* history is a convenience only */ }
}

export async function loadKb(refresh = false) {
  S.kbLoading = true;
  S.kbError = null;
  emit("pill", "drawer");
  try {
    S.kb = await jget("/api/kb/status" + (refresh ? "?refresh=1" : ""));
  } catch (e) {
    S.kbError = e.message || "无法读取知识库状态";
  }
  S.kbLoading = false;
  emit("pill", "drawer");
}

