import json

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def _client():
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app)


def test_gui_meta_and_settings_smoke():
    c = _client()

    r = c.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "gui" in j
    assert "runtime" in j

    r = c.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j


def test_gui_pack_scan_empty_rejected():
    c = _client()

    # If neither paths nor preset is usable, scan should still be safe: it can
    # return an empty scan, but it must not crash.
    r = c.post("/api/pack/scan", json={"paths": []})
    assert r.status_code == 200
    j = r.json()
    assert j["files"] == 0
    assert isinstance(j["sensitive"], list)


def test_gui_jobs_sse_stream_smoke():
    c = _client()

    # Create a fake job entry directly (internal API), then ensure the SSE
    # endpoint streams at least one event.
    import peridot_gui

    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(id=jid, kind="test", status="done", created_ts=0.0, result={"ok": True})

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        buf = b""
        for chunk in r.iter_bytes():
            buf += chunk
            if b"data:" in buf:
                break

    # Must contain an SSE data frame with valid JSON.
    txt = buf.decode("utf-8", errors="replace")
    assert "data:" in txt
    line = [ln for ln in txt.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(line[len("data: ") :])
    assert payload["id"] == jid
    assert payload["status"] == "done"
