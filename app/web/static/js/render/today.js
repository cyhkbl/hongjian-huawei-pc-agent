/**
 * 今日创作台：打开页面就能写，不用填任何表单。
 *
 * 对应评委提的业务困境——门店销售员忙、不愿意做额外工作、文笔参差。
 * 所以这里反着来：系统先给出「今天该写什么」，销售员点一下就直接出稿，
 * 出来的稿子还顺手给出三种不同写法，挑一篇改几个字就能发。
 */
import { jget, jpost } from "../api.js";
import { h, mount } from "../util.js";
import { S, emit, setPersonaSet, showStudio, startChat } from "../state.js";

const T = { ideas: [], loading: false, error: "", busyId: "", set: null };

export function todayState() { return T; }

export async function enterToday() {
  if (!T.ideas.length && !T.loading && !T.error) loadIdeas();
  render();
}

async function loadIdeas() {
  T.loading = true; T.error = "";
  render();
  try {
    const r = await jget("/api/daily?limit=4");
    T.ideas = r.ideas || [];
    if (!T.ideas.length) T.error = "今天暂时没有可推荐的选题，可以到「工作台」自己指定。";
  } catch (e) {
    T.error = e.message + (e.hint ? " " + e.hint : "");
  }
  T.loading = false;
  render();
}

/** 一键创作：先给新品事实卡，再同时给出三种人设写法。 */
async function createFromIdea(idea) {
  if (T.busyId) return;
  T.busyId = idea.idea_id;
  render();
  try {
    // 先拿事实卡：让销售员在等稿子的几秒里看清「这台机器能说什么」
    jget(`/api/factcard/${encodeURIComponent(idea.model_id)}`)
      .then((c) => { S.factCard = c; emit("factCard", "side"); })
      .catch(() => {});
    const r = await jpost("/api/personas", {
      text: `${idea.title}（${idea.model_name}，${idea.season_tag}）`,
      model_ids: [idea.model_id],
      scenario: idea.scenario,
      platform: idea.platform,
    });
    setPersonaSet(r);
    showStudio();
  } catch (e) {
    T.error = e.message + (e.hint ? " " + e.hint : "");
  }
  T.busyId = "";
  render();
}

function ideaCard(idea) {
  const busy = T.busyId === idea.idea_id;
  const card = h("article", { class: "idea", dataset: { id: idea.idea_id } },
    h("header", {},
      h("span", { class: "chip season", text: idea.season_tag }),
      h("span", { class: "chip plat", text: idea.platform_label || idea.platform })),
    h("h3", { text: idea.title }),
    h("p", { class: "model", text: `${idea.model_name} · ${idea.reason}` }),
    h("button", {
      class: "btn primary", type: "button", disabled: busy,
      "aria-busy": busy ? "true" : "false",
      onclick: () => createFromIdea(idea),
    }, busy ? "正在写…" : "一键写这篇"),
  );
  return card;
}

function render() {
  const root = document.getElementById("today");
  if (!root) return;
  const kids = [];
  kids.push(
    h("section", { class: "today-hero" },
      h("h2", { text: "今天写什么" }),
      h("p", { class: "lede", text: "不用填表。选一条今天值得写的，点一下就有稿子，还会顺手给出三种不同写法——挑一篇，改几个字就能发。" }),
    ),
  );

  if (T.loading) {
    kids.push(h("div", { class: "state", role: "status" },
      h("p", { text: "正在按今天的时间和门店情况挑选题…" })));
  } else if (T.error) {
    kids.push(h("div", { class: "state error", role: "alert" },
      h("h3", { text: "推荐暂时没拿到" }), h("p", { text: T.error }),
      h("div", { class: "actions" },
        h("button", { class: "btn primary", type: "button", onclick: loadIdeas }, "重试"))));
  } else {
    const grid = h("div", { class: "idea-grid" });
    for (const idea of T.ideas) grid.append(ideaCard(idea));
    kids.push(grid);
    kids.push(h("section", { class: "today-alt" },
      h("h3", { text: "想自己指定？" }),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: () => showStudio() },
          "打开工作台，自己选机型和渠道"),
        h("button", { class: "btn", type: "button", onclick: () => startChat() },
          "让 Agent 问我几个问题"),
      ),
    ));
  }
  mount(root, ...kids);
}
