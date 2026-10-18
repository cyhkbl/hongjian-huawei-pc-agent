"""Knowledge-base interface. The agent only talks to this; it never knows whether
facts came from the ima OpenAPI or the organiser's local copy."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.models import (
    Fact, ImageAsset, KBStatus, PriceRecord, ProductModel, SearchHit, TraceEntry,
)


@runtime_checkable
class KnowledgeBase(Protocol):
    def status(self) -> KBStatus:
        """Account / KB name / connection / last API response. Never exposes full keys."""

    # ---- structured access (same shape in ima and local mode)
    def models(self) -> list[ProductModel]: ...
    def get_model(self, model_id: str) -> Optional[ProductModel]: ...
    def find_models(self, text: str) -> list[tuple[ProductModel, float, str]]:
        """Alias match on free text. Returns (model, score 0..1, matched_alias), best first.
        Must keep confusable names apart (e.g. 'MateBook 14' alone is ambiguous between
        鸿蒙版 and 酷睿 Ultra -> return both with equal low score; 'D 16' vs 'D 16 SE')."""

    def facts(self, model_id: str, kinds: Optional[list[str]] = None,
              categories: Optional[list[str]] = None,
              tags: Optional[list[str]] = None) -> list[Fact]: ...
    def get_fact(self, fact_id: str) -> Optional[Fact]: ...

    def images(self, model_id: str, tags: Optional[list[str]] = None) -> list[ImageAsset]: ...
    def get_image(self, image_id: str) -> Optional[ImageAsset]: ...
    def image_bytes(self, image_id: str) -> tuple[bytes, str]:
        """(data, mime). Local read in mirror mode; get_media_info + download in ima mode."""

    def prices(self, model_id: str) -> list[PriceRecord]: ...

    # ---- live retrieval (this is what produces visible ima calls + trace)
    def search(self, query: str, model_id: Optional[str] = None, limit: int = 8) -> list[SearchHit]: ...
    def drain_trace(self) -> list[TraceEntry]:
        """Return and clear the trace entries recorded since the last drain (per-run)."""
