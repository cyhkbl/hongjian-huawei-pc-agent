import { postBlob } from "./api.js";
import { active } from "./state.js";
import { plainText } from "./model.js";
import { copyText, download, toast, $ } from "./util.js";
import { drawPoster, canvasBlob } from "./poster.js";

export const EXPORTS = [
  { id: "copy", label: "复制正文" },
  { id: "md", label: "Markdown（.md）" },
  { id: "txt", label: "纯文本（.txt）" },
  { id: "html", label: "网页（.html）" },
  { id: "docx", label: "Word（.docx）" },
  { id: "json", label: "运行档案（.json）" },
  { id: "png", label: "海报图片（.png）", posterOnly: true },
];

export async function doExport(fmt) {
  const run = active();
  if (!run) return;
  try {
    if (fmt === "copy") {
      const ok = await copyText(plainText(run));
      toast(ok ? "正文已复制" : "复制失败，请手动选择文字复制", ok ? "info" : "error");
      return;
    }
    if (fmt === "png") {
      if (!run.article || run.article.platform !== "poster") { toast("只有门店海报可以导出 PNG", "error"); return; }
      let canvas = $("#poster-canvas");
      if (!canvas) { canvas = document.createElement("canvas"); await drawPoster(canvas, run.article, run); }
      const blob = await canvasBlob(canvas);
      download(blob, `hongjian-poster-${run.run_id}.png`);
      toast("海报已导出");
      return;
    }
    const { blob, filename } = await postBlob("/api/export", { run_id: run.run_id, format: fmt });
    download(blob, filename || `hongjian-${run.run_id}.${fmt}`);
    toast("已导出 " + (filename || fmt));
  } catch (e) {
    toast((e.message || "导出失败") + (e.hint ? "。" + e.hint : ""), "error");
  }
}
