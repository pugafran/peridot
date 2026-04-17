import json
import time
from pathlib import Path

import pytest


def _get_app():
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")
    from peridot_gui import create_app

    return create_app()


def test_gui_meta_smoke():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _get_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "runtime" in j
    assert "presets" in j
    assert "gui" in j and "base_url" in j["gui"]


def test_gui_pack_scan_returns_shape(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # create a tiny directory to scan
    d = tmp_path / "demo"
    d.mkdir()
    (d / "a.txt").write_text("hello", encoding="utf-8")

    app = _get_app()
    c = TestClient(app)

    r = c.post(
        "/api/pack/scan",
        json={"preset": "", "paths": [str(d)], "excludes": []},
    )
    assert r.status_code == 200
    j = r.json()

    assert j["files"] >= 1
    assert isinstance(j["expanded_paths"], list)
    assert "sensitive" in j and isinstance(j["sensitive"], list)
    # Ensure the UI-friendly keys are present even if empty
    assert "missing_paths" in j and isinstance(j["missing_paths"], list)
    assert "skipped_paths" in j and isinstance(j["skipped_paths"], list)


def test_gui_sse_events_stream_done_job():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from peridot_gui import Job, _JOBS, _JOBS_LOCK

    app = _get_app()
    c = TestClient(app)

    jid = "test-job"
    job = Job(id=jid, kind="pack", status="done", created_ts=time.time(), finished_ts=time.time(), result={"ok": True})
    with _JOBS_LOCK:
        _JOBS[jid] = job

    # Stream should yield at least one data event with our payload
    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        buf = b""
        for chunk in r.iter_bytes():
            buf += chunk
            if b"data:" in buf and b"test-job" in buf:
                break

    text = buf.decode("utf-8", errors="replace")
    # Extract first data payload (best-effort)
    lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert lines, text
    payload = json.loads(lines[0].removeprefix("data: "))
    assert payload["id"] == jid
    assert payload["status"] == "done"
