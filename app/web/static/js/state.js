// Tiny store: plain object + topic pub/sub. Renderers subscribe to topics.

export const S = {
  options: null,
  kb: null,
  kbLoading: false,
  kbError: null,
  runs: new Map(),      // run_id -> RunResult (this session or fetched)
  reqs: new Map(),      // run_id -> the request that produced it
  thread: [],           // run ids of the current working thread (v1 -> v2 ...)
  activeId: "",
  compareA: "",
  compareB: "",
  running: null,        // {kind, stages:[], startedAt, label}
  error: null,          // {message, hint, retry}
  view: "studio",       // studio | archive
  section: "article",   // scene | basis | article | verify
  side: "evidence",     // evidence | compare | revise
  pane: "article",      // narrow screens: task | article | side
  pinned: null,         // {blockId, idx}
  hover: null,
  showMarks: true,
  history: [],
  archive: { prompt: null, promptError: null, cases: null, casesError: null, results: new Map(), running: false },
  personaSet: null,     // 一题三解的结果：{personas, runs, diff}
  factCard: null,       // 新品事实卡：{model_name, groups, limits, unconfirmed, price_lines}
  chat: null,           // 对话式需求挖掘
};

const subs = new Map();

export function on(topic, fn) {
  if (!subs.has(topic)) subs.set(topic, new Set());
  subs.get(topic).add(fn);
}

export function emit(...topics) {
  for (const t of topics) for (const fn of subs.get(t) || []) {
    try { fn(); } catch (e) { console.error(`render ${t} failed`, e); }
  }
}

export const active = () => S.runs.get(S.activeId) || null;

export function setPersonaSet(r) { S.personaSet = r; emit("personaSet", "side", "article"); }
export function startChat() { S.chat = { fresh: true }; emit("chat", "side"); }

export function showStudio() {
  S.view = "studio";
  emit("view");
  requestAnimationFrame(() => document.getElementById("col-task")?.focus());
}

// 供渲染层以 S.xxx 形式调用
S.showStudio = showStudio;
S.startChat = startChat;
