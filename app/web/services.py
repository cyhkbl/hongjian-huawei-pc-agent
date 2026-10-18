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

    # ---- knowledge base --------------------------------------------------
    def kb_status(self, refresh: bool = False) -> KBStatus:
        kb = self.kb()
        if refresh:
            fn: Optional[Any] = getattr(kb, "refresh", None)
            if callable(fn):
                fn()
        return kb.status()
