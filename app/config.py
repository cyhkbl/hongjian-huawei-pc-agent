"""Runtime configuration. All secrets come from environment variables / .env
(never from source). Nothing in this file may hold a real key."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no dependency). Existing environment wins."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_dotenv(ROOT / ".env")


def _first(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


def mask(value: str, keep_tail: int = 2) -> str:
    """Never show a full credential. 'abcdef123' -> '****23'."""
    if not value:
        return ""
    if len(value) <= keep_tail + 2:
        return "****"
    return "****" + value[-keep_tail:]


@dataclass(frozen=True)
class Settings:
    # --- ima OpenAPI (official skill uses these two names; we accept both pairs)
    ima_client_id: str
    ima_api_key: str
    ima_base_url: str
    ima_kb_name: str
    # --- KB mode: auto (ima if configured, else local mirror) | ima | local
    kb_mode: str
    kb_local_dir: str          # path to the organiser's KB copy (NOT shipped in the repo)
    cache_dir: Path
    # --- public LLM (OpenAI-compatible /chat/completions). Empty => deterministic composer
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout: float
    # --- server
    host: str
    port: int
    runs_dir: Path

    @property
    def ima_configured(self) -> bool:
        return bool(self.ima_client_id and self.ima_api_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


def get_settings() -> Settings:
    return Settings(
        ima_client_id=_first("IMA_OPENAPI_CLIENTID", "IMA_CLIENT_ID"),
        ima_api_key=_first("IMA_OPENAPI_APIKEY", "IMA_API_KEY"),
        ima_base_url=_first("IMA_BASE_URL", default="https://ima.qq.com").rstrip("/"),
        ima_kb_name=_first("IMA_KB_NAME", default="任德耀新建华为PC知识库"),
        kb_mode=_first("KB_MODE", default="auto").lower(),
        kb_local_dir=_first("KB_LOCAL_DIR"),
        cache_dir=Path(_first("CACHE_DIR", default=str(ROOT / ".kb_cache"))),
        llm_base_url=_first("LLM_BASE_URL").rstrip("/"),
        llm_api_key=_first("LLM_API_KEY"),
        llm_model=_first("LLM_MODEL"),
        llm_timeout=float(_first("LLM_TIMEOUT", default="90")),
        host=_first("HOST", default="0.0.0.0"),
        port=int(_first("PORT", default="7860")),
        runs_dir=Path(_first("RUNS_DIR", default=str(ROOT / "runs"))),
    )
