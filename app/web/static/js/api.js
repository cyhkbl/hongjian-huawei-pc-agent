// HTTP + SSE client. All failures surface as ApiFail with a readable message.

export class ApiFail extends Error {
  constructor(code, message, hint = "", status = 0, retryable = false) {
    super(message);
    this.code = code;
    this.hint = hint;
    this.status = status;
    this.retryable = retryable;
  }
}

async function failFrom(res) {
  let body = null;
  try { body = await res.json(); } catch { /* not json */ }
  const e = body && body.error;
  if (e) return new ApiFail(e.code || "error", e.message || "请求没有成功", e.hint || "", res.status, res.status >= 500 || res.status === 429);
  return new ApiFail("http_" + res.status, `服务返回了 ${res.status}`, "请稍后重试。", res.status, res.status >= 500);
}

const networkFail = () => new ApiFail("network", "无法连接到服务", "请检查网络，或确认服务仍在运行，然后重试。", 0, true);

export async function jget(path, signal) {
  let res;
  try { res = await fetch(path, { headers: { Accept: "application/json" }, signal }); } catch (e) {
    if (e.name === "AbortError") throw e;
    throw networkFail();
  }
  if (!res.ok) throw await failFrom(res);
  return res.json();
}

export async function jpost(path, body, signal) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST", signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw networkFail();
  }
  if (!res.ok) throw await failFrom(res);
  return res.json();
}

export async function postBlob(path, body) {
  let res;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch { throw networkFail(); }
  if (!res.ok) throw await failFrom(res);
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
  const filename = m ? decodeURIComponent(m[1]) : "";
  return { blob: await res.blob(), filename };
}

/** POST to an SSE endpoint; resolves with the `result` payload. */
export async function stream(path, body, { onStage, onStart, signal } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST", signal,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw networkFail();
  }
  if (!res.ok) throw await failFrom(res);
  if (!res.body) throw new ApiFail("no_stream", "浏览器不支持流式读取", "请换用新版 Chrome 或 Edge。");

  const reader = res.body.getReader();
  const dec = new TextDecoder("utf-8");
  let buf = "";
  let result = null;
  const handle = (chunk) => {
    let ev = "message";
    const data = [];
    for (const line of chunk.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    let payload;
    try { payload = JSON.parse(data.join("\n")); } catch { return; }
    if (ev === "stage") onStage && onStage(payload);
    else if (ev === "start") onStart && onStart(payload);
    else if (ev === "result") result = payload;
    else if (ev === "error") throw new ApiFail(payload.code || "error", payload.message || "生成失败", payload.hint || "", 0, !!payload.retryable);
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        handle(buf.slice(0, i));
        buf = buf.slice(i + 2);
      }
    }
    if (buf.trim()) handle(buf);
  } catch (e) {
    if (e instanceof ApiFail || e.name === "AbortError") throw e;
    throw new ApiFail("stream_broken", "连接中断了", "网络不稳定，请重试。", 0, true);
  }
  if (!result) throw new ApiFail("stream_closed", "没有收到结果就断开了", "请重试一次。", 0, true);
  return result;
}

export const imgUrl = (id) => "/api/image/" + encodeURIComponent(id);
