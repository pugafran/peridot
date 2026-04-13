import json

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

import peridot_gui  # noqa: E402


def test_meta_smoke():
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "gui" in data and "host" in data["gui"] and "port" in data["gui"]
    assert "runtime" in data and "os_name" in data["runtime"]
    assert "presets" in data and isinstance(data["presets"], list)


def test_settings_smoke():
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings_path" in data
    assert "settings" in data


def test_pack_scan_smoke():
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": ["."],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["files"] >= 0
    assert data["bytes"] >= 0
    assert "sensitive" in data and isinstance(data["sensitive"], list)


def test_job_events_sse_ends_for_done_job():
    app = peridot_gui.create_app()
    c = TestClient(app)

    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=0.0,
        started_ts=0.0,
        finished_ts=0.0,
        result={"ok": True},
        error=None,
    )

    with c.stream("GET", f"/api/jobs/{jid}/events") as resp:
        assert resp.status_code == 200
        raw = b"".join(resp.iter_bytes())

    # basic SSE framing should include at least one data event.
    assert b"data:" in raw
    # the JSON payload should be parseable.
    payload_lines = [ln for ln in raw.splitlines() if ln.startswith(b"data: ")]
    assert payload_lines
    last = payload_lines[-1].split(b"data: ", 1)[1]
    obj = json.loads(last.decode("utf-8"))
    assert obj["id"] == jid
    assert obj["status"] == "done"
