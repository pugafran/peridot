import json
import os
import tempfile
from pathlib import Path

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette.testclient  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps (fastapi/starlette) not installed")


def test_gui_api_meta_doctor_settings_smoke():
    from peridot_gui import create_app
    from starlette.testclient import TestClient

    app = create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    r = c.get("/api/doctor")
    assert r.status_code == 200

    r = c.get("/api/settings")
    assert r.status_code == 200


def test_gui_api_pack_scan_accepts_paths_and_excludes(tmp_path: Path):
    from peridot_gui import create_app
    from starlette.testclient import TestClient

    app = create_app()
    c = TestClient(app)

    f = tmp_path / "hello.txt"
    f.write_text("hello", encoding="utf-8")

    payload = {
        "paths": [str(f)],
        "excludes": ["*.nope"],
        "preset": "",
    }

    r = c.post("/api/pack/scan", json=payload)
    assert r.status_code == 200
    out = r.json()

    assert out["files"] >= 1
    assert out["bytes"] >= 1
    assert out["missing_paths"] == []


def test_gui_api_sse_events_endpoint_content_type():
    from peridot_gui import Job, _JOBS, create_app
    from starlette.testclient import TestClient

    app = create_app()
    c = TestClient(app)

    # Create a job that is already finished so the SSE generator exits quickly.
    jid = "test-job"
    _JOBS[jid] = Job(id=jid, kind="pack", status="done", created_ts=0.0, result={"ok": True})

    r = c.get(f"/api/jobs/{jid}/events")
    assert r.status_code == 200
    ct = r.headers.get("content-type") or ""
    assert "text/event-stream" in ct
    assert r.content

    _JOBS.pop(jid, None)
