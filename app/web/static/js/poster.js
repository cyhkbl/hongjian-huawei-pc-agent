// 门店海报：用 canvas 渲染成品。主视觉按原始宽高比放进画框，不拉伸、不裁切。
import { imgUrl } from "./api.js";

const W = 1080;
const H = 1520;
const SERIF = '"Source Han Serif SC","Noto Serif SC","Songti SC","STSong","SimSun",serif';
const SANS = '"HarmonyOS Sans SC","PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif';

function loadImage(src) {
  return new Promise((resolve) => {
    const im = new Image();
    im.onload = () => resolve(im);
    im.onerror = () => resolve(null);
    im.src = src;
  });
}

/** Wrap text by measured width (works for CJK, which has no spaces). */
function wrap(ctx, text, maxW) {
  const lines = [];
  let line = "";
  for (const ch of Array.from(text || "")) {
    if (ch === "\n") { lines.push(line); line = ""; continue; }
    const t = line + ch;
    if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = ch; } else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

function drawLines(ctx, lines, x, y, lh, align = "left") {
  ctx.textAlign = align;
  lines.forEach((l, i) => ctx.fillText(l, x, y + i * lh));
  return y + lines.length * lh;
}

export async function drawPoster(canvas, art, run) {
  const p = art.poster || {};
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  const pad = 72;

  ctx.fillStyle = "#f8f5ee";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#c7000b";
  ctx.fillRect(0, 0, W, 18);
  ctx.fillStyle = "#1d1b19";
  ctx.fillRect(pad, 70, 64, 6);

  // titles
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#1d1b19";
  ctx.font = `700 76px ${SERIF}`;
  let y = drawLines(ctx, wrap(ctx, p.main_title || art.title, W - pad * 2), pad, 160, 96);
  ctx.fillStyle = "#4a443d";
  ctx.font = `500 32px ${SANS}`;
  y = drawLines(ctx, wrap(ctx, p.sub_title || art.intro || "", W - pad * 2), pad, y + 4, 46);

  // hero image: fit inside the frame, keep aspect
  const frameY = y + 28;
  const frameW = W - pad * 2;
  const frameH = 560;
  ctx.fillStyle = "#ece6d8";
  ctx.fillRect(pad, frameY, frameW, frameH);
  const imageId = p.image_id || (art.image_refs && art.image_refs[0] && art.image_refs[0].image_id);
  const img = imageId ? await loadImage(imgUrl(imageId)) : null;
  let imgBox = null;
  if (img) {
    const r = Math.min(frameW / img.naturalWidth, frameH / img.naturalHeight);
    const w = img.naturalWidth * r;
    const h = img.naturalHeight * r;
    const x = pad + (frameW - w) / 2;
    const yy = frameY + (frameH - h) / 2;
    ctx.drawImage(img, x, yy, w, h);
    imgBox = { w: img.naturalWidth, h: img.naturalHeight };
  } else {
    ctx.fillStyle = "#6b6358";
    ctx.font = `500 28px ${SANS}`;
    ctx.textAlign = "center";
    ctx.fillText("主视觉图片未能加载", W / 2, frameY + frameH / 2);
  }
  ctx.strokeStyle = "#1d1b19";
  ctx.lineWidth = 2;
  ctx.strokeRect(pad, frameY, frameW, frameH);

  // points (at most three)
  let py = frameY + frameH + 64;
  const points = (p.points || []).slice(0, 3);
  points.forEach((pt, i) => {
    ctx.fillStyle = "#c7000b";
    ctx.fillRect(pad, py - 30, 8, 44);
    ctx.fillStyle = "#1d1b19";
    ctx.textAlign = "left";
    ctx.font = `700 34px ${SERIF}`;
    ctx.fillText(pt.label || `卖点 ${i + 1}`, pad + 28, py);
    ctx.font = `400 30px ${SANS}`;
    ctx.fillStyle = "#2f2b27";
    const lines = wrap(ctx, pt.text || "", W - pad * 2 - 28 - 190);
    drawLines(ctx, lines, pad + 28 + 190, py, 42);
    py += Math.max(1, lines.length) * 42 + 26;
  });

  // event note + CTA
  ctx.fillStyle = "#6b6358";
  ctx.font = `400 26px ${SANS}`;
  const noteY = Math.max(py + 12, H - 250);
  drawLines(ctx, wrap(ctx, p.event_note || "", W - pad * 2), pad, noteY, 38);
  const ctaText = p.cta || art.cta || "";
  if (ctaText) {
    ctx.font = `700 32px ${SANS}`;
    const tw = Math.min(ctx.measureText(ctaText).width + 72, W - pad * 2);
    ctx.fillStyle = "#c7000b";
    ctx.fillRect(pad, H - 156, tw, 70);
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.fillText(ctaText.length > 16 ? ctaText.slice(0, 16) : ctaText, pad + tw / 2, H - 109);
  }
  ctx.fillStyle = "#6b6358";
  ctx.font = `400 22px ${SANS}`;
  ctx.textAlign = "left";
  const ref = art.image_refs && art.image_refs[0];
  ctx.fillText(ref ? `图片：${ref.model_name} · 来自知识库` : "", pad, H - 40);
  ctx.textAlign = "right";
  ctx.fillText("鸿笺生成 · 以官方渠道信息为准", W - pad, H - 40);
  return imgBox;
}

export function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    try { canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("toBlob"))), "image/png"); } catch (e) { reject(e); }
  });
}
