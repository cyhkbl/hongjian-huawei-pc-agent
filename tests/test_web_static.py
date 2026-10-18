"""Static front end sanity: offline-capable (no external URLs), modules resolve."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.server import STATIC_DIR, create_app
from tests.test_web_support import FakeServices

EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|@import\s+["']https?://""")


def test_no_external_assets():
    for f in STATIC_DIR.rglob("*"):
        if f.suffix in {".html", ".css", ".js", ".svg"}:
            assert not EXTERNAL.search(f.read_text(encoding="utf-8")), f"external asset in {f}"


def test_index_references_exist_and_are_served(tmp_path):
    c = TestClient(create_app(FakeServices(runs_dir=tmp_path)))
    html = c.get("/").text
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert refs
    for r in refs:
        assert c.get(r).status_code == 200, r


def test_js_imports_resolve():
    for f in (STATIC_DIR / "js").rglob("*.js"):
        for rel in re.findall(r'from\s+"(\.{1,2}/[^"]+)"', f.read_text(encoding="utf-8")):
            assert (f.parent / rel).resolve().is_file(), f"{f.name} imports missing {rel}"


def test_no_innerhtml_on_model_output():
    # generated copy must only enter the DOM through textContent / h()
    for f in (STATIC_DIR / "js").rglob("*.js"):
        txt = f.read_text(encoding="utf-8")
        for m in re.finditer(r"innerHTML\s*=\s*([^;]+);", txt):
            assert m.group(1).strip() in {'""', "''"}, f"{f.name}: innerHTML = {m.group(1)[:40]}"
