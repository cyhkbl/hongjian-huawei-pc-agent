"""Knowledge layer. ``get_kb(settings)`` returns an object satisfying ``KnowledgeBase``."""
from __future__ import annotations

from typing import Optional

from app.config import Settings, get_settings
from app.kb.base import KnowledgeBase


def get_kb(settings: Optional[Settings] = None) -> KnowledgeBase:
    from app.kb.store import KB
    return KB(settings or get_settings())


__all__ = ["get_kb", "KnowledgeBase"]
