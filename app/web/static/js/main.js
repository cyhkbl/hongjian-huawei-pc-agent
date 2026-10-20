import { jget } from "./api.js";
import { S, on, emit } from "./state.js";
import { $, $$, announce } from "./util.js";
import { loadKb, refreshHistory } from "./actions.js";
import { initTask } from "./render/task.js";
import { initArticle, closeMenu, setPin } from "./render/article.js";
import { initSide } from "./render/side.js";
import { initDrawer, closeDrawer } from "./render/drawer.js";
import { initArchive, enterArchive, renderArchive } from "./render/archive.js";
import { enterToday } from "./render/today.js";

function applyPane() {
  const shell = $("#studio");
  shell.dataset.pane = S.pane;
  for (const b of $$("#panebar button")) {
    const on_ = b.dataset.pane === S.pane;
    b.setAttribute("aria-current", on_ ? "true" : "false");
    if (on_) b.classList.remove("has-new");
  }
}

function applyView() {
  const studio = S.view === "studio";
  const today = S.view === "today";
  $("#studio").hidden = !studio;
  $("#today").hidden = !today;
  $("#archive").hidden = !(S.view === "archive");
  $("#panebar").hidden = !studio;
  document.body.dataset.view = S.view;
  for (const b of $$(".view-btn")) b.setAttribute("aria-current", b.dataset.view === S.view ? "page" : "false");
  if (today) enterToday();
  if (!studio && !today) { renderArchive(); enterArchive(); }
  window.scrollTo(0, 0);
}

function wire() {
  for (const b of $$(".view-btn")) b.addEventListener("click", () => { S.view = b.dataset.view; emit("view"); });
  for (const b of $$("#panebar button")) b.addEventListener("click", () => { S.pane = b.dataset.pane; emit("pane"); });
  on("pane", applyPane);
  on("view", applyView);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (closeMenu()) return;
    if (closeDrawer()) return;
    if (S.pinned) setPin(null);
  });
}

async function boot() {
  initTask();
  initArticle();
  initSide();
  initDrawer();
  initArchive();
  wire();
  if (window.matchMedia("(max-width: 1100px)").matches) S.pane = "task";
  applyPane();
  S.view = "today";                 // 打开就是今日创作台：零表单，一键就能写
  applyView();

  loadKb(false);
  refreshHistory();
  try {
    S.options = await jget("/api/options");
    emit("options", "side");
  } catch (e) {
    announce("无法加载选项：" + e.message);
    const root = $("#col-task");
    root.textContent = "";
    const p = document.createElement("div");
    p.className = "state error";
    p.setAttribute("role", "alert");
    p.innerHTML = "";
    const h2 = document.createElement("h2");
    h2.textContent = "页面没有加载完整";
    const msg = document.createElement("p");
    msg.textContent = `${e.message}。${e.hint || "请刷新页面重试。"}`;
    const b = document.createElement("button");
    b.className = "btn primary";
    b.textContent = "刷新重试";
    b.addEventListener("click", () => location.reload());
    const act = document.createElement("div");
    act.className = "actions";
    act.append(b);
    p.append(h2, msg, act);
    root.append(p);
  }
}

boot();
