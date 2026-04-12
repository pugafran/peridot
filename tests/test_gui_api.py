import json
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def test_gui_api_meta_settings_doctor_scan_sse(tmp_path, monkeypatch):
    # Ensure we can import the experimental GUI module even when running tests.
    import peridot_gui  # noqa: WPS433

    app = peridot_gui.create_app()

    from fastapi.testclient import TestClient

    client = TestClient(app)

    # /api/meta should always work (it degrades gracefully if the peridot CLI isn't on PATH).
    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "gui" in meta
    assert "runtime" in meta

    # /api/settings should work (it prefers in-process load_settings()).
    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "settings_path" in settings
    assert "settings" in settings

    # /api/doctor may depend on the CLI being available. Accept either success
    # or a clean FastAPI error.
    r = client.get("/api/doctor")
    assert r.status_code in {200, 500}
    if r.status_code == 500:
        assert "detail" in r.json()

    # /api/pack/scan should work end-to-end in-process.
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    r = client.post(
        "/api/pack/scan",
        json={"preset": "", "paths": [str(tmp_path)], "excludes": []},
    )
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] >= 1
    assert isinstance(scan["sensitive"], list)

    # SSE stream should send valid events and terminate when job is done.
    jid = "test-job-1"
    peridot_gui._JOBS[jid] = peridot_gui.Job(  # noqa: SLF001
        id=jid,
        kind="pack",
        status="done",
        created_ts=time.time(),
        started_ts=time.time(),
        finished_ts=time.time(),
        result={"ok": True},
    )

    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        assert s.status_code == 200
        ct = s.headers.get("content-type") or ""
        assert "text/event-stream" in ct
        body = b"".join(list(s.iter_bytes()))

    # Expect at least one data: JSON line.
    assert b"data:" in body
    # Ensure the JSON payload can be parsed from at least one event.
    line = next(ln for ln in body.splitlines() if ln.startswith(b"data: "))
    payload = json.loads(line[len(b"data: ") :].decode("utf-8"))
    assert payload["id"] == jid
    assert payload["status"] == "done"
