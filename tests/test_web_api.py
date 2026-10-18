from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.web.server import create_app
from tests.test_web_support import FAKE_API_KEY, FAKE_CLIENT_ID, FAKE_LLM_KEY, FakeServices


@pytest.fixture()
def svc(tmp_path):
    return FakeServices(runs_dir=tmp_path / "runs")


@pytest.fixture()
def client(svc):
    return TestClient(create_app(svc))


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in text.split("\n\n"):
        ev, data = None, None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


# ---- basics -------------------------------------------------------------
def test_health_and_index(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
    # index is served when the front end exists
    idx = client.get("/")
    assert idx.status_code == 200 and "text/html" in idx.headers["content-type"]
    assert "鸿笺" in idx.text


def test_options_shape(client):
    d = client.get("/api/options").json()
    assert len(d["scenarios"]) == 8 and len(d["platforms"]) == 4
    assert {p["id"] for p in d["platforms"]} == {"wechat_mp", "xiaohongshu", "moments", "poster"}
    assert len(d["models"]) == 4 and d["models"][0]["model_id"] == "pro-hm"
    assert len(d["examples"]) >= 8
    cats = {e["category"] for e in d["examples"]}
    assert {"基础生成", "换场景", "换平台", "追问", "拒绝", "改稿"} <= cats


def test_kb_status_and_refresh(client, svc):
    d = client.get("/api/kb/status").json()
    assert d["mode"] == "local_mirror" and d["api_key_hint"] == "****10"
    assert svc.kb_.refreshed == 0
    client.get("/api/kb/status?refresh=1")
    assert svc.kb_.refreshed == 1


# ---- run ----------------------------------------------------------------
def test_run_ok_persists_and_lists(client):
    r = client.post("/api/run", json={"text": "给 MateBook Pro 写开学季小红书"})
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "ok" and run["article"]["blocks"]
    got = client.get(f"/api/runs/{run['run_id']}")
    assert got.status_code == 200 and got.json()["run_id"] == run["run_id"]
    lst = client.get("/api/runs").json()["runs"]
    assert lst and lst[0]["run_id"] == run["run_id"]


def test_run_clarification_and_refusal(client):
    c = client.post("/api/run", json={"text": "想买个轻薄本"}).json()
    assert c["status"] == "needs_clarification" and c["clarifications"][0]["options"]
    f = client.post("/api/run", json={"text": "写上国补立减2000"}).json()
    assert f["status"] == "refused" and f["refusal"]


def test_run_empty_and_too_long(client):
    assert client.post("/api/run", json={}).json()["error"]["code"] == "empty_task"
    r = client.post("/api/run", json={"text": "字" * 2001})
    assert r.status_code == 422 and r.json()["error"]["code"] == "text_too_long"


def test_invalid_payload_structured(client):
    r = client.post("/api/run", json={"platform": "weibo", "text": "x"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "invalid_request" and "Traceback" not in json.dumps(body)


# ---- SSE ----------------------------------------------------------------
def test_run_stream_event_order(client):
    r = client.post("/api/run/stream", json={"text": "给 MateBook Pro 写开学季小红书"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-1] == "result"
    stages = [d["stage"] for e, d in events if e == "stage"]
    assert stages == ["parse", "strategy", "retrieve", "extract", "compose",
                      "verify_fact", "verify_image", "compliance", "finalize"]
    result = events[-1][1]
    assert result["status"] == "ok" and result["article"]["title"]


def test_stream_clarification_is_a_result(client):
    events = parse_sse(client.post("/api/run/stream", json={"text": "想买个轻薄本"}).text)
    assert events[-1][0] == "result" and events[-1][1]["status"] == "needs_clarification"


def test_stream_error_event_has_no_stack(tmp_path):
    svc = FakeServices(runs_dir=tmp_path, fail_with=RuntimeError("boom /secret/path " + FAKE_API_KEY))
    c = TestClient(create_app(svc))
    events = parse_sse(c.post("/api/run/stream", json={"text": "x"}).text)
    assert events[-1][0] == "error"
    err = events[-1][1]
    assert err["code"] == "internal_error" and err["retryable"] is True
    blob = json.dumps(err, ensure_ascii=False)
    assert "boom" not in blob and "secret/path" not in blob and FAKE_API_KEY not in blob
    # the slot was released: another request still works
    ok = TestClient(create_app(FakeServices(runs_dir=tmp_path)))
    assert ok.post("/api/run", json={"text": "x"}).status_code == 200


def test_sync_run_error_is_structured(tmp_path):
    c = TestClient(create_app(FakeServices(runs_dir=tmp_path, fail_with=ValueError("bad"))),
                   raise_server_exceptions=False)
    r = c.post("/api/run", json={"text": "x"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "bad" not in r.text and "Traceback" not in r.text


# ---- revise -------------------------------------------------------------
def test_revise_chain(client):
    first = client.post("/api/run", json={"text": "给 MateBook Pro 写开学季小红书"}).json()
    r = client.post("/api/revise", json={"run_id": first["run_id"], "instruction": "再短一点"})
    assert r.status_code == 200
    second = r.json()
    assert second["parent_run_id"] == first["run_id"] and second["revision_note"] == "再短一点"
    assert len(second["article"]["blocks"]) < len(first["article"]["blocks"])
    events = parse_sse(client.post("/api/revise/stream",
                                   json={"run_id": second["run_id"], "instruction": "换成朋友圈",
                                         "platform": "moments"}).text)
    assert events[-1][0] == "result" and events[-1][1]["article"]["platform"] == "moments"


def test_revise_unknown_run_and_bad_id(client):
    r = client.post("/api/revise", json={"run_id": "nope", "instruction": "再短一点"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "run_not_found"
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/runs/a.b").json()["error"]["code"] == "run_not_found"
    assert client.post("/api/revise", json={"run_id": "x", "instruction": " "}).status_code == 422


def test_runs_survive_in_disk_for_new_app(svc, tmp_path):
    first = TestClient(create_app(svc)).post("/api/run", json={"text": "x"}).json()
    again = TestClient(create_app(FakeServices(runs_dir=tmp_path / "runs")))
    assert again.get(f"/api/runs/{first['run_id']}").status_code == 200


# ---- image --------------------------------------------------------------
def test_image_ok_cache_and_404(client):
    r = client.get("/api/image/hwpc_matebook-pro_front_01.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers["cache-control"] and r.content[:4] == b"\x89PNG"
    again = client.get("/api/image/hwpc_matebook-pro_front_01.png", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    miss = client.get("/api/image/not-in-kb.jpg")
    assert miss.status_code == 404 and miss.json()["error"]["code"] == "image_not_found"
    assert client.get("/api/image/..%5C..%5Cwindows%5Cwin.ini").status_code == 404


# ---- export -------------------------------------------------------------
def test_export_formats(client):
    run = client.post("/api/run", json={"text": "x"}).json()
    md = client.post("/api/export", json={"run_id": run["run_id"], "format": "md"})
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    assert FAKE_API_KEY not in md.text, "text exports are scrubbed as well"
    js = client.post("/api/export", json={"run_id": run["run_id"], "format": "json"})
    assert json.loads(js.content)["run_id"] == run["run_id"]
    assert client.post("/api/export", json={"run_id": run["run_id"], "format": "docx"}).status_code == 501
    assert client.post("/api/export", json={"run_id": run["run_id"], "format": "txt"}).status_code == 400
    assert client.post("/api/export", json={"run_id": run["run_id"], "format": "png"}).json()["error"]["code"] == "png_is_client_side"
    assert client.post("/api/export", json={"run_id": "zzz", "format": "md"}).status_code == 404


def test_export_nothing_for_clarification(client):
    run = client.post("/api/run", json={"text": "想买个轻薄本"}).json()
    r = client.post("/api/export", json={"run_id": run["run_id"], "format": "md"})
    assert r.status_code == 409


# ---- prompt / selftest --------------------------------------------------
def test_prompt_and_selftest(client):
    p = client.get("/api/prompt").json()
    assert p["version"] == "test-1" and "角色与任务" in p["text"] and p["sections"]
    cases = client.get("/api/selftest/cases").json()["cases"]
    assert len(cases) == 2
    ok = client.post("/api/selftest/run", json={"case_id": "t1"}).json()
    assert ok["passed"] is True
    assert client.post("/api/selftest/run", json={"case_id": "zz"}).status_code == 404


# ---- limits -------------------------------------------------------------
def test_body_size_limit(svc, monkeypatch):
    monkeypatch.setenv("WEB_MAX_BODY", "2048")
    c = TestClient(create_app(svc))
    r = c.post("/api/run", content=json.dumps({"text": "x" * 5000}), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    # a chunked body without content-length is counted as it streams
    def gen():
        for _ in range(10):
            yield b"x" * 1024
    r2 = c.post("/api/run", content=gen(), headers={"content-type": "application/json"})
    assert r2.status_code == 413


def test_rate_limit_heavy_and_general(svc, monkeypatch):
    monkeypatch.setenv("WEB_RATE_HEAVY", "3")
    monkeypatch.setenv("WEB_RATE_GENERAL", "5")
    c = TestClient(create_app(svc))
    codes = [c.post("/api/run", json={"text": "x"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = c.post("/api/run", json={"text": "x"})
    assert r.headers.get("retry-after") and r.json()["error"]["code"] == "rate_limited"
    # light endpoints use the general bucket (3 slots used by heavy are separate)
    gen = [c.get("/api/health").status_code for _ in range(7)]
    assert gen.count(200) >= 4 and 429 in gen


def test_rate_limit_is_per_ip(svc, monkeypatch):
    monkeypatch.setenv("WEB_RATE_HEAVY", "1")
    app = create_app(svc)
    a = TestClient(app, client=("203.0.113.5", 1111))
    b = TestClient(app, client=("203.0.113.6", 2222))
    assert a.post("/api/run", json={"text": "x"}).status_code == 200
    assert a.post("/api/run", json={"text": "x"}).status_code == 429
    assert b.post("/api/run", json={"text": "x"}).status_code == 200


def test_forwarded_for_only_trusted_from_private_peer(svc, monkeypatch):
    monkeypatch.setenv("WEB_RATE_HEAVY", "1")
    app = create_app(svc)
    # public peer cannot dodge the limit by rotating X-Forwarded-For
    pub = TestClient(app, client=("93.184.216.34", 1))
    assert pub.post("/api/run", json={"text": "x"}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert pub.post("/api/run", json={"text": "x"}, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 429
    # behind a private proxy the forwarded client is used
    proxy = TestClient(app, client=("10.0.0.2", 1))
    assert proxy.post("/api/run", json={"text": "x"}, headers={"x-forwarded-for": "9.9.9.9"}).status_code == 200
    assert proxy.post("/api/run", json={"text": "x"}, headers={"x-forwarded-for": "8.8.8.8"}).status_code == 200


# ---- credentials never leak ----------------------------------------------
def test_no_credentials_in_any_response(client):
    run = client.post("/api/run", json={"text": FAKE_API_KEY + " " + FAKE_CLIENT_ID + " 给 MateBook Pro 写小红书"}).json()
    rid = run["run_id"]
    bodies = [
        client.get("/api/health").text, client.get("/api/kb/status?refresh=1").text,
        client.get("/api/options").text, client.get("/api/runs").text, client.get(f"/api/runs/{rid}").text,
        client.get("/api/prompt").text, client.get("/api/selftest/cases").text,
        client.post("/api/run", json={"text": FAKE_LLM_KEY}).text,
        client.post("/api/run/stream", json={"text": FAKE_API_KEY}).text,
        client.post("/api/revise", json={"run_id": rid, "instruction": FAKE_API_KEY}).text,
        client.post("/api/export", json={"run_id": rid, "format": "md"}).text,
        client.post("/api/export", json={"run_id": rid, "format": "json"}).text,
        client.get("/api/nope").text, client.get(f"/api/image/{FAKE_API_KEY}").text,
    ]
    for b in bodies:
        for secret in (FAKE_API_KEY, FAKE_CLIENT_ID, FAKE_LLM_KEY):
            assert secret not in b


def test_security_headers_and_no_docs(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_unknown_api_returns_structured_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "http_error"
