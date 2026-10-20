"""鸿笺 HTTP service: JSON API, SSE progress streams and the static front end.

Design notes
- The service is a public, login-free demo. Safety comes from: no credential is
  ever serialised (a final scrub on every JSON / SSE / text export body), a
  request-body size cap, per-IP rate limits and structured errors without
  stack traces.
- `create_app(services=...)` takes any object with the method names of
  `app.web.services.Services`, which is how the tests run without the real
  knowledge base or pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

import pydantic_core
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models import (
    BatchRunRequest, ChatRequest, ExportRequest, PersonaRunRequest, ReviseRequest,
    RunRequest, RunResult, StageLog, TitleScoreRequest,
)
from app.web import options as opts
from app.web.services import BackendUnavailable, Services

log = logging.getLogger("hongjian.web")

APP_VERSION = "0.1.0"
STATIC_DIR = Path(__file__).resolve().parent / "static"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
MAX_TEXT = 2000
MAX_INSTRUCTION = 1000
STREAM_TIMEOUT_S = 300.0
HEARTBEAT_S = 12.0


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# helpers: scrubbing, JSON responses, errors
# --------------------------------------------------------------------------
class SelftestRequest(BaseModel):
    case_id: str


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = "",
                 headers: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint
        self.headers = headers or {}


def _scrub_factory(services) -> Callable[[bytes], bytes]:
    def scrub(data: bytes) -> bytes:
        try:
            secrets = services.secrets()
        except Exception:  # never let scrubbing break a response
            secrets = []
        for s in secrets:
            if s:
                data = data.replace(s.encode("utf-8"), b"****")
        return data
    return scrub


def _to_json_bytes(obj: Any) -> bytes:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json().encode("utf-8")
    return pydantic_core.to_json(obj, serialize_unknown=True, fallback=str)


def error_body(code: str, message: str, hint: str = "", **extra: Any) -> dict:
    body = {"code": code, "message": message}
    if hint:
        body["hint"] = hint
    body.update(extra)
    return {"error": body}


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------
class RateLimiter:
    """Sliding-window limiter keyed by (client ip, bucket)."""

    def __init__(self, general: int, heavy: int, soft: Optional[int] = None, window: float = 60.0):
        self.limits = {"general": general, "heavy": heavy,
                       "soft": soft if soft is not None else max(general, heavy * 4)}
        self.window = window
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    def check(self, ip: str, bucket: str) -> Optional[int]:
        """Return None if allowed, else seconds to wait."""
        limit = self.limits[bucket]
        now = time.monotonic()
        key = (ip, bucket)
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) > 20000:
                    self._hits.clear()
                q = self._hits[key] = deque()
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return None


def client_ip(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    # Behind a proxy (HF Space etc.) the peer is a private address; only then
    # trust the first X-Forwarded-For hop. A direct public peer cannot spoof it.
    try:
        trusted = ipaddress.ip_address(host).is_private
    except ValueError:
        trusted = False
    if trusted:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()[:64] or host
    return host


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy",
     b"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
     b"connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'"),
]


class GuardMiddleware:
    """Pure ASGI: per-IP rate limit on /api/* and security headers on every response."""

    def __init__(self, app, limiter: "RateLimiter"):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path.startswith("/api/"):
            if scope["method"] == "POST" and path in SOFT_PATHS:
                bucket = "soft"
            elif scope["method"] == "POST" and path in HEAVY_PATHS:
                bucket = "heavy"
            else:
                bucket = "general"
            wait = self.limiter.check(client_ip(Request(scope)), bucket)
            if wait is not None:
                body = json.dumps(error_body("rate_limited", "请求太频繁了", f"请 {wait} 秒后再试。"),
                                  ensure_ascii=False).encode()
                headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                           (b"retry-after", str(wait).encode()),
                           (b"content-length", str(len(body)).encode())] + SECURITY_HEADERS
                await send({"type": "http.response.start", "status": 429, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                have = {k.lower() for k, _ in msg.get("headers", [])}
                msg = dict(msg)
                msg["headers"] = list(msg.get("headers", [])) + [(k, v) for k, v in SECURITY_HEADERS if k not in have]
            await send(msg)

        await self.app(scope, receive, send_with_headers)


HEAVY_PATHS = {"/api/run", "/api/run/stream", "/api/revise", "/api/revise/stream",
               "/api/selftest/run", "/api/export"}
# 自测用例走独立配额：跑完 21 条不会吃掉演示用的生成额度
SOFT_PATHS = {"/api/selftest/run"}


class BodyLimitMiddleware:
    """Pure ASGI: reject oversized request bodies (declared or streamed)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        async def too_large():
            body = json.dumps(error_body("payload_too_large", "请求内容太大",
                                         f"请求体上限为 {self.max_bytes // 1024} KB。"),
                              ensure_ascii=False).encode()
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        for k, v in scope["headers"]:
            if k == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        return await too_large()
                except ValueError:
                    pass

        received = 0
        started = False
        exceeded = False

        async def counting_receive():
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return msg

        async def tracking_send(msg):
            nonlocal started
            if exceeded and not started:
                return  # swallow whatever the app tried to answer; 413 is sent below
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await too_large()


# --------------------------------------------------------------------------
# app factory
# --------------------------------------------------------------------------
def create_app(services: Optional[Any] = None) -> FastAPI:
    svc = services or Services()
    scrub = _scrub_factory(svc)
    limiter = RateLimiter(general=_env_int("WEB_RATE_GENERAL", 300),
                          heavy=_env_int("WEB_RATE_HEAVY", 40))
    max_body = _env_int("WEB_MAX_BODY", 64 * 1024)
    slots = threading.BoundedSemaphore(_env_int("WEB_MAX_CONCURRENT_RUNS", 8))

    mem_runs: "OrderedDict[str, RunResult]" = OrderedDict()
    mem_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        def warm():
            try:
                svc.warm()
            except Exception as e:  # backend may not be ready yet; requests report it
                log.warning("context warm-up failed: %s", type(e).__name__)
        threading.Thread(target=warm, daemon=True, name="ctx-warm").start()
        yield

    app = FastAPI(title="鸿笺 Hongjian", version=APP_VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = svc

    # ---- response helpers ------------------------------------------------
    def json_response(obj: Any, status: int = 200, headers: Optional[dict] = None) -> Response:
        h = {"Cache-Control": "no-store"}
        h.update(headers or {})
        return Response(scrub(_to_json_bytes(obj)), status_code=status,
                        media_type="application/json", headers=h)

    def err_response(e: ApiError) -> Response:
        return json_response(error_body(e.code, e.message, e.hint), e.status, e.headers)

    # ---- run storage -----------------------------------------------------
    def remember(run: RunResult) -> None:
        with mem_lock:
            mem_runs[run.run_id] = run
            mem_runs.move_to_end(run.run_id)
            while len(mem_runs) > 200:
                mem_runs.popitem(last=False)

    def runs_dir() -> Optional[Path]:
        try:
            d = svc.runs_dir()
            return Path(d) if d else None
        except Exception:
            return None

    def load_run(run_id: str) -> RunResult:
        if not RUN_ID_RE.match(run_id or ""):
            raise ApiError(404, "run_not_found", "找不到这次运行", "运行编号格式不对，请从运行记录里重新选择。")
        with mem_lock:
            hit = mem_runs.get(run_id)
        if hit is not None:
            return hit
        d = runs_dir()
        if d is not None:
            f = d / f"{run_id}.json"
            if f.is_file():
                try:
                    run = RunResult.model_validate_json(f.read_text(encoding="utf-8"))
                    remember(run)
                    return run
                except Exception:
                    raise ApiError(500, "run_unreadable", "运行记录无法读取",
                                   "文件可能已损坏，请重新生成一次。")
        raise ApiError(404, "run_not_found", "找不到这次运行", "服务重启后旧记录可能已被清理，请重新生成。")

    def summarize(run: RunResult) -> dict:
        art = run.article
        names = []
        if run.evidence:
            names = [m.short_name for m in run.evidence.models]
        return {
            "run_id": run.run_id, "created_at": run.created_at, "status": run.status,
            "parent_run_id": run.parent_run_id, "revision_note": run.revision_note,
            "title": (art.title if art else "") or run.task.raw[:60],
            "platform": art.platform if art else run.task.platform,
            "scenario": run.task.scenario, "models": names,
            "verdict": run.verification.verdict if run.verification else "",
        }

    # ---- concurrency guard ----------------------------------------------
    def acquire_slot() -> None:
        if not slots.acquire(blocking=False):
            raise ApiError(429, "busy", "现在同时生成的人有点多", "请等几秒再试。", {"Retry-After": "5"})

    def check_run_request(req: RunRequest) -> None:
        if len(req.text) > MAX_TEXT:
            raise ApiError(422, "text_too_long", f"任务描述最多 {MAX_TEXT} 字", "请精简后再提交。")
        if not (req.text.strip() or req.model_ids or req.platform or req.scenario):
            raise ApiError(422, "empty_task", "还没有任务内容",
                           "请描述要写什么，或者在左侧选择产品、场景和平台。")

    def check_revise_request(req: ReviseRequest) -> None:
        if len(req.instruction) > MAX_INSTRUCTION:
            raise ApiError(422, "instruction_too_long", f"修改要求最多 {MAX_INSTRUCTION} 字")
        if not (req.instruction.strip() or req.platform or req.scenario or req.selling_point):
            raise ApiError(422, "empty_instruction", "还没有修改要求", "写一句想怎么改，或点一个快捷按钮。")

    def convert_exc(e: Exception) -> ApiError:
        if isinstance(e, ApiError):
            return e
        if isinstance(e, BackendUnavailable):
            return ApiError(503, "backend_unavailable", str(e), "团队模块还在接入中，稍后再试。")
        eid = uuid.uuid4().hex[:8]
        log.exception("unhandled error [%s]", eid)
        return ApiError(500, "internal_error", "生成过程中出了点问题",
                        f"可以直接重试。若反复出现，请把编号 {eid} 告诉我们。")

    # ---- middleware ------------------------------------------------------
    # Pure ASGI middlewares: Starlette's BaseHTTPMiddleware cancels streaming
    # responses (SSE) on the client side in some browsers, so it is not used.
    app.add_middleware(GuardMiddleware, limiter=limiter)
    app.add_middleware(BodyLimitMiddleware, max_bytes=max_body)

    # ---- exception handlers ---------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return err_response(e)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        details = [{"loc": [str(p) for p in d.get("loc", [])], "msg": str(d.get("msg", ""))}
                   for d in e.errors()][:8]
        body = error_body("invalid_request", "请求格式不正确", "请检查字段取值后重试。", details=details)
        return json_response(body, 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        msg = {404: "找不到这个地址", 405: "这个地址不支持该操作"}.get(e.status_code, "请求没有成功")
        return json_response(error_body("http_error", msg), e.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        return err_response(convert_exc(e))

    # ---- basic endpoints -------------------------------------------------
    @app.get("/api/health")
    def health():
        backend = {}
        for name in ("app.kb", "app.agent.pipeline", "app.agent.export", "app.agent.prompts",
                     "app.agent.selftest"):
            try:
                backend[name.split(".", 1)[1]] = importlib.util.find_spec(name) is not None
            except (ImportError, ValueError):
                backend[name.split(".", 1)[1]] = False
        return json_response({"ok": True, "service": "hongjian", "version": APP_VERSION,
                              "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "backend": backend})

    @app.get("/api/kb/status")
    def kb_status(refresh: int = 0):
        try:
            st = svc.kb_status(bool(refresh))
        except Exception as e:
            raise convert_exc(e)
        return json_response(st)

    @app.get("/api/options")
    def options():
        models, models_error = [], ""
        try:
            for m in svc.kb().models():
                models.append({
                    "model_id": m.model_id, "name": m.name, "short_name": m.short_name,
                    "series": m.series, "os_family": m.os_family, "os_label": m.os_label,
                    "confusable_with": m.confusable_with, "has_public_price": m.has_public_price,
                })
        except Exception as e:
            models_error = convert_exc(e).message
        return json_response({
            "app": {"name": "鸿笺", "subtitle": "华为 PC 营销软文智能体", "version": APP_VERSION},
            "scenarios": opts.SCENARIOS, "platforms": opts.PLATFORMS, "models": models,
            "models_error": models_error, "audiences": opts.AUDIENCES,
            "selling_points": opts.SELLING_POINTS, "examples": opts.EXAMPLES,
            "revise_shortcuts": opts.REVISE_SHORTCUTS, "stages": opts.STAGES,
            "limits": {"max_text": MAX_TEXT, "max_instruction": MAX_INSTRUCTION},
        })

    # ---- run / revise ----------------------------------------------------
    def _do_run(req: RunRequest, on_stage=None) -> RunResult:
        res = svc.run(req, on_stage)
        remember(res)
        return res

    def _do_revise(req: ReviseRequest, on_stage=None) -> RunResult:
        prev = load_run(req.run_id)
        res = svc.revise(req, prev, on_stage)
        remember(res)
        return res

    @app.post("/api/run")
    def run_sync(req: RunRequest):
        check_run_request(req)
        acquire_slot()
        try:
            return json_response(_do_run(req))
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    @app.post("/api/revise")
    def revise_sync(req: ReviseRequest):
        check_revise_request(req)
        load_run(req.run_id)
        acquire_slot()
        try:
            return json_response(_do_revise(req))
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    def sse(event: str, data: Any) -> bytes:
        payload = scrub(_to_json_bytes(data)).decode("utf-8")
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")

    def stream_job(job: Callable[[Callable[[StageLog], None]], RunResult]) -> StreamingResponse:
        """Run a blocking pipeline call in a thread, relay on_stage as SSE."""
        acquire_slot()

        async def gen():
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()
            closed = threading.Event()

            def push(kind: str, payload: Any) -> None:
                if closed.is_set():
                    return
                try:
                    loop.call_soon_threadsafe(q.put_nowait, (kind, payload))
                except RuntimeError:  # loop already closed (client left)
                    pass

            def worker() -> None:
                try:
                    res = job(lambda s: push("stage", s))
                    push("result", res)
                except Exception as e:
                    ae = convert_exc(e)
                    push("error", {"code": ae.code, "message": ae.message, "hint": ae.hint,
                                   "retryable": ae.status >= 500})
                finally:
                    slots.release()

            threading.Thread(target=worker, daemon=True, name="pipeline-run").start()
            yield sse("start", {"ts": time.time()})
            deadline = time.monotonic() + STREAM_TIMEOUT_S
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        yield sse("error", {"code": "timeout", "message": "生成超时了",
                                            "hint": "可以直接重试。", "retryable": True})
                        return
                    try:
                        kind, payload = await asyncio.wait_for(q.get(), min(HEARTBEAT_S, remaining))
                    except asyncio.TimeoutError:
                        yield b": ping\n\n"
                        continue
                    yield sse(kind, payload)
                    if kind in ("result", "error"):
                        return
            finally:
                closed.set()

        return StreamingResponse(gen(), media_type="text/event-stream", headers={
            # "no-cache", not "no-store": Chromium flags no-store streamed bodies as ERR_ABORTED.
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/run/stream")
    def run_stream(req: RunRequest):
        check_run_request(req)
        return stream_job(lambda cb: _do_run(req, cb))

    @app.post("/api/revise/stream")
    def revise_stream(req: ReviseRequest):
        check_revise_request(req)
        load_run(req.run_id)
        return stream_job(lambda cb: _do_revise(req, cb))

    # ---- runs ------------------------------------------------------------
    @app.get("/api/runs")
    def list_runs(limit: int = 30):
        limit = max(1, min(limit, 100))
        found: dict[str, RunResult] = {}
        d = runs_dir()
        if d is not None and d.is_dir():
            files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
            for f in files:
                try:
                    r = RunResult.model_validate_json(f.read_text(encoding="utf-8"))
                    found[r.run_id] = r
                except Exception:
                    continue
        with mem_lock:
            for r in mem_runs.values():
                found[r.run_id] = r
        items = sorted(found.values(), key=lambda r: r.created_at, reverse=True)[:limit]
        return json_response({"runs": [summarize(r) for r in items]})

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return json_response(load_run(run_id))

    # ---- image -----------------------------------------------------------
    @app.get("/api/image/{image_id}")
    def get_image(image_id: str, request: Request):
        try:
            data, mime = svc.kb().image_bytes(image_id)
        except (KeyError, FileNotFoundError, LookupError):
            raise ApiError(404, "image_not_found", "知识库里没有这张图片")
        except BackendUnavailable as e:
            raise convert_exc(e)
        except Exception as e:
            ae = convert_exc(e)
            raise ApiError(502, "image_unavailable", "图片暂时取不到", ae.hint)
        if not data:
            raise ApiError(404, "image_not_found", "知识库里没有这张图片")
        if not (mime or "").startswith("image/"):
            mime = "application/octet-stream"
        etag = '"' + hashlib.sha1(data).hexdigest()[:20] + '"'
        headers = {"ETag": etag, "Cache-Control": "public, max-age=86400",
                   "Content-Disposition": "inline"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type=mime, headers=headers)

    # ---- export ----------------------------------------------------------
    @app.post("/api/export")
    def export(req: ExportRequest):
        if req.format == "png":
            raise ApiError(400, "png_is_client_side", "PNG 在浏览器里生成",
                           "海报 PNG 请在海报预览里点“导出 PNG”。")
        run = load_run(req.run_id)
        if run.article is None:
            raise ApiError(409, "nothing_to_export", "这次运行没有稿件可导出",
                           "追问或被拒绝的运行没有正文，可导出 JSON 运行档案。" if req.format != "json" else "")
        try:
            data, mime, filename = svc.export(run, req.format)
        except ValueError:
            raise ApiError(400, "unsupported_format", f"暂不支持 {req.format} 格式")
        except ImportError:
            raise ApiError(501, "format_unavailable", f"{req.format} 导出所需的组件没有安装",
                           "可以先导出 md 或 html。")
        except Exception as e:
            raise convert_exc(e)
        if mime.startswith("text/") or "json" in mime or "html" in mime:
            data = scrub(data)
        disp = "attachment; filename*=UTF-8''" + quote(filename, safe="")
        return Response(data, media_type=mime, headers={
            "Content-Disposition": disp, "Cache-Control": "no-store"})

    # ---- 对话式需求挖掘 ------------------------------------------------
    @app.post("/api/chat/start")
    def chat_start():
        acquire_slot()
        try:
            return json_response(svc.chat_start())
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        acquire_slot()
        try:
            return json_response(svc.chat(req))
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    # ---- 一稿四发 ------------------------------------------------------
    @app.post("/api/batch")
    def batch(req: BatchRunRequest):
        acquire_slot()
        try:
            return json_response(svc.batch(req))
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    # ---- 今日推荐 ------------------------------------------------------
    @app.get("/api/daily")
    def daily(limit: int = 4):
        try:
            return json_response({"ideas": svc.daily(max(1, min(int(limit), 8)))})
        except Exception as e:
            raise convert_exc(e)

    # ---- 新品事实卡 ----------------------------------------------------
    @app.get("/api/factcard/{model_id}")
    def factcard(model_id: str):
        try:
            return json_response(svc.factcard(model_id))
        except Exception as e:
            raise convert_exc(e)

    # ---- 一题三解 ------------------------------------------------------
    @app.post("/api/personas")
    def personas(req: PersonaRunRequest):
        acquire_slot()
        try:
            return json_response(svc.personas(req))
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    # ---- 标题评分 ------------------------------------------------------
    @app.post("/api/titles")
    def titles(req: TitleScoreRequest):
        try:
            return json_response({"titles": svc.score_titles(req.titles, req.platform, req.model_name)})
        except Exception as e:
            raise convert_exc(e)

    # ---- prompt / selftest ----------------------------------------------
    @app.get("/api/prompt")
    def prompt():
        try:
            text, version = svc.prompt()
        except Exception as e:
            raise convert_exc(e)
        sections = re.findall(r"^#{1,3}\s*(.+)$", text, flags=re.M)
        return json_response({"version": version, "text": text, "chars": len(text),
                              "sections": sections[:40]})

    @app.get("/api/selftest/cases")
    def selftest_cases():
        try:
            return json_response({"cases": svc.selftest_cases()})
        except Exception as e:
            raise convert_exc(e)

    @app.post("/api/selftest/run")
    def selftest_run(req: SelftestRequest):
        acquire_slot()
        try:
            return json_response(svc.selftest_run(req.case_id))
        except KeyError:
            raise ApiError(404, "case_not_found", "没有这个评测用例")
        except Exception as e:
            raise convert_exc(e)
        finally:
            slots.release()

    # ---- front end -------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index():
        f = STATIC_DIR / "index.html"
        if not f.is_file():
            raise ApiError(404, "no_frontend", "前端文件缺失")
        return FileResponse(f, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        f = STATIC_DIR / "favicon.svg"
        if f.is_file():
            return FileResponse(f, media_type="image/svg+xml")
        return Response(status_code=204)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
