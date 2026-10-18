"""Entry point: `python -m app.main` serves 鸿笺 on settings.host:settings.port."""
from __future__ import annotations

import logging

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("app.web.server:app", host=settings.host, port=settings.port,
                log_level="info", timeout_keep_alive=30, proxy_headers=False)


if __name__ == "__main__":
    main()
