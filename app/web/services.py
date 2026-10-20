"""Seam between the HTTP layer and the rest of the project.

`Services` binds lazily to the real modules (`app.context`, `app.agent.*`) so the
web layer can be imported, tested and started before every backend module exists.
Tests pass a fake with the same method names to `create_app(services=...)`.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

from app.models import ExportRequest, KBStatus, ReviseRequest, RunRequest, RunResult, StageLog

OnStage = Optional[Callable[[StageLog], None]]


class BackendUnavailable(RuntimeError):
    """A backend module has not been delivered (or failed to import)."""


def _load(module: str):
    try:
        return importlib.import_module(module)
    except ImportError as e:  # pragma: no cover - depends on teammates' progress
        raise BackendUnavailable(f"后端模块 {module} 尚未就绪") from e


class Services:
    """Real backend bindings. Every call resolves its module at call time."""

    def __init__(self) -> None:
        self._chat_states: dict[str, Any] = {}

    # ---- context ---------------------------------------------------------
    def ctx(self):
        from app.context import get_context
        return get_context()

    def settings(self):
        try:
            return self.ctx().settings
        except Exception:
            from app.config import get_settings
            return get_settings()

    def kb(self):
        return self.ctx().kb

    def secrets(self) -> list[str]:
        s = self.settings()
        vals = [getattr(s, n, "") for n in ("ima_client_id", "ima_api_key", "llm_api_key")]
        return [v for v in vals if v and len(v) >= 6]

    def runs_dir(self):
        return self.settings().runs_dir

    def warm(self) -> None:
        self.ctx()

    # ---- pipeline --------------------------------------------------------
    def run(self, req: RunRequest, on_stage: OnStage = None) -> RunResult:
        return _load("app.agent.pipeline").run(req, self.ctx(), on_stage)

    def revise(self, req: ReviseRequest, prev: RunResult, on_stage: OnStage = None) -> RunResult:
        return _load("app.agent.pipeline").revise(req, prev, self.ctx(), on_stage)

    def export(self, run: RunResult, fmt: str) -> tuple[bytes, str, str]:
        return _load("app.agent.export").export(run, fmt, self.kb())

    def prompt(self) -> tuple[str, str]:
        mod = _load("app.agent.prompts")
        return mod.SYSTEM_PROMPT, getattr(mod, "PROMPT_VERSION", "")

    # ---- self test -------------------------------------------------------
    def selftest_cases(self) -> list[dict]:
        return _load("app.agent.selftest").cases()

    def selftest_run(self, case_id: str) -> dict:
        return _load("app.agent.selftest").run_case(self.ctx(), case_id)

    # ---- 对话式需求挖掘 -------------------------------------------------
    def chat_start(self) -> dict:
        mod = _load("app.agent.converse")
        state = mod.start_session(self.kb())
        self._chat_states[state.session_id] = state
        return {"state": state.model_dump(), "task": mod._to_task(state).model_dump()}

    def chat(self, req) -> dict:
        mod = _load("app.agent.converse")
        kb = self.kb()
        state = self._chat_states.get(req.session_id)
        if state is None:
            state = mod.start_session(kb, req.session_id)
        state, task = mod.chat(req, kb, state)
        self._chat_states[state.session_id] = state
        out: dict = {"state": state.model_dump(), "task": task.model_dump()}
        if state.ready:
            from app.agent.pipeline import run as _run  # noqa: PLC0415
            from app.models import RunRequest  # noqa: PLC0415
            r = _run(RunRequest(model_ids=task.model_ids, platform=task.platform,
                                scenario=task.scenario, audience=task.audience,
                                selling_point=task.selling_point,
                                text=task.raw), self.ctx())
            out["run"] = r.model_dump()
        return out

    # ---- 一稿四发 -------------------------------------------------------
    def batch(self, req) -> dict:
        return _load("app.agent.batch").batch_run(req, self.ctx()).model_dump()

    # ---- 今日推荐 -------------------------------------------------------
    def daily(self, limit: int = 4) -> list[dict]:
        mod = _load("app.agent.daily")
        return [d.model_dump() for d in mod.daily_ideas(self.kb(), limit=limit)]

    # ---- 新品事实卡 -----------------------------------------------------
    def factcard(self, model_id: str) -> dict:
        return _load("app.agent.factcard").build_fact_card(model_id, self.kb()).model_dump()

    # ---- 一题三解 -------------------------------------------------------
    def personas(self, req) -> dict:
        return _load("app.agent.personas").persona_run(req, self.ctx()).model_dump()

    # ---- 标题评分 -------------------------------------------------------
    def score_titles(self, titles: list[str], platform: str, model_name: str = "") -> list[dict]:
        mod = _load("app.agent.title_score")
        return [t.model_dump() for t in mod.score_titles(titles, platform, model_name)]

    # ---- knowledge base --------------------------------------------------
    def kb_status(self, refresh: bool = False) -> KBStatus:
        kb = self.kb()
        if refresh:
            fn: Optional[Any] = getattr(kb, "refresh", None)
            if callable(fn):
                fn()
        return kb.status()
