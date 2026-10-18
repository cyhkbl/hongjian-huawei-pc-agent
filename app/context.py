"""Process-wide singletons: settings, knowledge base, optional LLM client."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import Settings, get_settings
from app.kb.base import KnowledgeBase


@dataclass
class AppContext:
    settings: Settings
    kb: KnowledgeBase
    llm: Optional[Any] = None          # app.agent.llm.LLMClient | None  (None => deterministic composer)
    lock: threading.Lock = field(default_factory=threading.Lock)


_ctx: Optional[AppContext] = None
_guard = threading.Lock()


def build_context(settings: Optional[Settings] = None) -> AppContext:
    settings = settings or get_settings()
    from app.kb import get_kb            # kb-dev provides get_kb(settings)
    kb = get_kb(settings)
    llm = None
    try:
        from app.agent.llm import get_llm  # writer-dev provides get_llm(settings)
        llm = get_llm(settings)
    except ImportError:
        llm = None
    return AppContext(settings=settings, kb=kb, llm=llm)


def get_context() -> AppContext:
    global _ctx
    with _guard:
        if _ctx is None:
            _ctx = build_context()
        return _ctx


def set_context(ctx: Optional[AppContext]) -> None:
    """Tests / hot reload."""
    global _ctx
    with _guard:
        _ctx = ctx
