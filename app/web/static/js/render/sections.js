// 四段中的“一 场景判断”“二 知识库依据”。
import { S } from "../state.js";
import { h, fmtMs, PLATFORM_NAME, SCENARIO_NAME } from "../util.js";
import { modelOf } from "../model.js";
import { extLink, badge } from "./common.js";
import { imgUrl } from "../api.js";

export function sceneSection(run) {
  const st = run.strategy;
  const t = run.task;
  const wrap = h("div", null,
    h("h2", { class: "sec" }, "一、场景判断"),
    h("p", { class: "lead", text: "先判断写给谁、用在哪、要解决什么，再决定怎么写。" }));
  if (!st) {
    wrap.append(h("div", { class: "note-box", text: "这次运行没有走到策略阶段，所以没有场景判断。" }));
    return wrap;
  }
  const dl = h("dl", { class: "facts-grid" });
  const cell = (k, v, wide) => { if (v) dl.append(h("div", { class: wide ? "wide" : "" }, h("dt", { text: k }), h("dd", { text: v }))); };
  cell("目标人群", st.audience);
  cell("使用场景", st.usage_scene);
  cell("场景", st.scenario_label || SCENARIO_NAME[t.scenario]);
  cell("平台", st.platform_label || PLATFORM_NAME[t.platform]);
  cell("购买阶段", st.purchase_stage);
  cell("语气", st.tone);
  cell("用户问题", (st.pain_points || []).join("；"), true);
  cell("内容目标", st.goal, true);
  cell("切入角度", st.hook, true);
  cell("篇幅与配图", [st.length, st.image_count ? `${st.image_count} 张图` : ""].filter(Boolean).join(" · "));
  cell("行动引导", st.cta);
  wrap.append(dl);

  if (t.confusion_notes && t.confusion_notes.length) {
    wrap.append(h("div", { class: "note-box" }, h("b", { text: "机型确认：" }), t.confusion_notes.join("；")));
  }
  if (t.blocked_requests && t.blocked_requests.length) {
    wrap.append(h("div", { class: "note-box warn" }, h("b", { text: "没有照办的要求：" }), t.blocked_requests.join("；")));
  }

  wrap.append(h("h3", { class: "block-title", text: "卖点顺序与理由" }));
  wrap.append(h("ol", { class: "rank" }, (st.selling_points || []).map((sp) => h("li", null,
    h("b", { text: sp.label }), h("div", { class: "why", text: sp.why }),
    sp.fact_ids && sp.fact_ids.length ? h("div", { class: "small muted", text: "依据：" + sp.fact_ids.map((id) => modelOf(run).refOf.get(id) || id).join("、") }) : null))));

  if (st.image_slots && st.image_slots.length) {
    wrap.append(h("h3", { class: "block-title", text: "配图计划" }));
    wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
      h("thead", null, h("tr", null, ["位置", "用途", "优先画面"].map((x) => h("th", { text: x })))),
      h("tbody", null, st.image_slots.map((s) => h("tr", null, h("td", { text: s.slot }), h("td", { text: s.purpose }), h("td", { text: (s.prefer_tags || []).join("、") })))))));
  }

  wrap.append(h("h3", { class: "block-title", text: "策略解释" }));
  wrap.append(h("ul", { class: "rationale" }, (st.rationale || []).map((r) => h("li", { text: r }))));
  if (st.structure && st.structure.length) {
    wrap.append(h("h3", { class: "block-title", text: "结构" }));
    wrap.append(h("div", { class: "chips" }, st.structure.map((s, i) => h("span", { class: "badge mute", text: `${i + 1}. ${s}` }))));
  }
  return wrap;
}

export function basisSection(run) {
  const ev = run.evidence;
  const wrap = h("div", null,
    h("h2", { class: "sec" }, "二、知识库依据"),
    h("p", { class: "lead", text: "文中每个产品断言都对应下面的一条事实。红色边线表示这篇稿件用到了它。" }));
  if (!ev) {
    wrap.append(h("div", { class: "note-box", text: "这次运行没有检索知识库。" }));
    return wrap;
  }
  const m = modelOf(run);
  const used = new Set(ev.used_fact_ids && ev.used_fact_ids.length ? ev.used_fact_ids : [...m.refOf.keys()]);

  wrap.append(h("h3", { class: "block-title" }, "型号", h("small", { text: `${ev.models.length} 个` })));
  wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["型号", "系统", "易混淆", "资料基线", "官方链接"].map((x) => h("th", { text: x })))),
    h("tbody", null, ev.models.map((mo) => h("tr", null,
      h("td", { text: mo.name }), h("td", { text: mo.os_label }),
      h("td", { text: (mo.confusable_with || []).map((id) => m.modelName.get(id) || id).join("、") || "—" }),
      h("td", { text: mo.snapshot_date || "—" }),
      h("td", null, (mo.official_urls || []).slice(0, 2).map((u, i) => h("div", null, extLink(u, i ? "更多" : "官网"))))))))));

  const facts = ev.facts.slice().sort((a, b) => (used.has(b.id) ? 1 : 0) - (used.has(a.id) ? 1 : 0));
  wrap.append(h("h3", { class: "block-title" }, "事实点", h("small", { text: `${facts.length} 条，用到 ${facts.filter((f) => used.has(f.id)).length} 条` })));
  wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["事实", "限定条件", "资料标题", "知识库路径", "官方链接", "核验日期"].map((x) => h("th", { text: x })))),
    h("tbody", null, facts.map((f) => h("tr", { class: used.has(f.id) ? "used" : "" },
      h("td", null, f.text, m.refOf.get(f.id) ? h("sup", { class: "rf", text: m.refOf.get(f.id) }) : null),
      h("td", { text: (f.constraints || []).join("；") || "—" }),
      h("td", { text: f.source_title }),
      h("td", { class: "path", text: f.source_path }),
      h("td", null, (f.source_urls || []).slice(0, 2).map((u, i) => h("div", null, extLink(u, i ? "更多" : "官方页面")))),
      h("td", { text: f.verified_date || "—" })))))));

  if (ev.images && ev.images.length) {
    const usedImg = new Set(ev.used_image_ids || []);
    wrap.append(h("h3", { class: "block-title" }, "候选图片", h("small", { text: `${ev.images.length} 张，用到 ${[...usedImg].length} 张` })));
    wrap.append(h("div", { class: "imglist" }, ev.images.map((im) => h("div", { class: "imgcard" },
      h("div", { class: "th" }, h("img", { src: imgUrl(im.id), alt: im.caption || im.id, loading: "lazy", width: im.width || null, height: im.height || null })),
      h("div", { class: "t" }, usedImg.has(im.id) ? badge("bad", "已使用") : null, h("div", { text: im.caption || im.id }),
        h("div", { class: "muted", text: m.modelName.get(im.model_id) || im.model_id }))))));
  }
  if (ev.prices && ev.prices.length) {
    wrap.append(h("h3", { class: "block-title" }, "价格记录", h("small", { text: `${ev.prices.length} 条` })));
    wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
      h("thead", null, h("tr", null, ["款式", "口径", "金额", "条件", "核验时间", "来源"].map((x) => h("th", { text: x })))),
      h("tbody", null, ev.prices.map((p) => h("tr", null, h("td", { text: p.spec || p.product_name }), h("td", { text: p.price_type }),
        h("td", { text: p.amount != null ? `¥${p.amount}` : "无金额" }), h("td", { text: p.conditions || p.stock || "—" }),
        h("td", { text: p.verified_at || "—" }), h("td", null, p.url ? extLink(p.url, "官方页面") : "—")))))));
  }
  if (ev.trace && ev.trace.length) {
    wrap.append(h("h3", { class: "block-title" }, "本次检索记录", h("small", { text: `${ev.trace.length} 次调用` })));
    wrap.append(h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" },
      h("thead", null, h("tr", null, ["调用", "来源", "返回", "条数", "耗时"].map((x) => h("th", { text: x })))),
      h("tbody", null, ev.trace.map((t) => h("tr", null, h("td", { class: "mono", text: t.step }),
        h("td", { text: t.origin === "ima" ? "ima" : "本地镜像" }),
        h("td", { text: t.code == null ? "—" : `${t.code} ${t.msg || ""}` }), h("td", { text: t.count == null ? "—" : t.count }), h("td", { text: fmtMs(t.ms) })))))));
  }
  return wrap;
}
