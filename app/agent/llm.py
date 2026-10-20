"""OpenAI 兼容 /chat/completions 客户端。未配置 → get_llm 返回 None（走确定性 Composer）。

约束：key 只出现在请求头里；日志、异常、返回值里一律不含 key。
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    """可读的 LLM 调用错误（不含凭证）。"""


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if not t:
        raise LLMError("模型返回为空")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    # 取最外层的大括号
    start = t.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(t[start:i + 1])
                        if isinstance(v, dict):
                            return v
                    except json.JSONDecodeError:
                        break
                    break
        start = t.find("{", start + 1)
    raise LLMError("模型返回中没有可解析的 JSON 对象")


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 240.0,
                 temperature: float = 0.3, transport: Optional[httpx.BaseTransport] = None,
                 max_retries: int = 3, backoff: float = 3.0,
                 sleep: "Optional[Callable[[float], None]]" = None):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key           # 仅用于请求头；不输出
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep or time.sleep
        self._transport = transport
        self.last_mode = ""               # "json_object" | "plain"

    def __repr__(self) -> str:            # 防止 key 被日志带出
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"

    # ---- internals
    def _url(self) -> str:
        return self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"

    def _post_once(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as c:
                r = c.post(self._url(), headers=headers, json=payload)
        except httpx.TimeoutException:
            raise LLMError(f"LLM 请求超时（>{self.timeout:.0f}s）") from None
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 网络错误：{type(e).__name__}") from None
        if r.status_code in (401, 403):
            raise LLMError(f"LLM 鉴权失败（HTTP {r.status_code}），请检查 LLM_API_KEY / 权限")
        if r.status_code == 404:
            raise LLMError("LLM 接口地址不存在（HTTP 404），请检查 LLM_BASE_URL 与 LLM_MODEL")
        if r.status_code == 429:
            raise LLMError("LLM 触发频率限制（HTTP 429）")
        if r.status_code >= 400:
            detail = ""
            try:
                j = r.json()
                err = j.get("error") or j.get("detail") or {}
                if isinstance(err, dict):
                    inner = err.get("error")
                    err = inner if isinstance(inner, dict) else err
                detail = str(err.get("message") if isinstance(err, dict) else err)[:160]
            except Exception:  # noqa: BLE001
                detail = r.text[:120]
            raise LLMError(f"LLM 返回 HTTP {r.status_code}：{self._scrub(detail)}")
        try:
            return r.json()
        except ValueError:
            raise LLMError("LLM 返回的不是 JSON") from None

    def _post(self, payload: dict) -> dict:
        """单次请求；429 / 5xx / 超时按退避重试。"""
        last: Optional[LLMError] = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._post_once(payload)
            except LLMError as e:
                msg = str(e)
                retryable = ("HTTP 429" in msg) or ("HTTP 5" in msg) or ("超时" in msg) or ("网络错误" in msg)
                last = e
                if not retryable or attempt >= self.max_retries:
                    raise
                # 频控线性拉长，其余翻倍
                delay = self.backoff * (attempt + 1) if "HTTP 429" in msg else self.backoff * (2 ** attempt)
                self._sleep(delay)
        raise last or LLMError("LLM 调用失败")

    def _scrub(self, s: str) -> str:
        return s.replace(self._api_key, "****") if self._api_key else s

    @staticmethod
    def _content(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM 返回结构异常（缺少 choices[0].message.content）") from None

    # ---- public
    def chat_json(self, system: str, user: str) -> dict:
        payload = {
            "model": self.model, "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            data = self._post({**payload, "response_format": {"type": "json_object"}})
            self.last_mode = "json_object"
        except LLMError as e:
            # 部分兼容服务不认识 response_format（400/422）→ 降级为纯文本再正则取 JSON
            if "HTTP 400" in str(e) or "HTTP 422" in str(e):
                data = self._post(payload)
                self.last_mode = "plain"
            else:
                raise
        return _extract_json(self._content(data))


def get_llm(settings: Settings) -> Optional[LLMClient]:
    if not settings.llm_configured:
        return None
    return LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
