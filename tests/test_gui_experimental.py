import os
import sys
import time

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_gui_deps(), reason="GUI optional deps (fastapi/starlette) not installed")


def test_gui_api_endpoints_smoke(monkeypatch):
    # Force GUI to invoke the in-repo module rather than relying on an installed
    # `peridot` executable being on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from peridot_gui import create_app  # noqa: WPS433
    from starlette.testclient import TestClient  # noqa: WPS433

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "runtime" in j
    assert "presets" in j

    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j

    r = client.get("/api/doctor")
    assert r.status_code == 200


def test_gui_pack_scan_and_sse_headers(monkeypatch):
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from peridot_gui import Job, _JOBS, _JOBS_LOCK, create_app  # noqa: WPS433
    from starlette.testclient import TestClient  # noqa: WPS433

    app = create_app()
    client = TestClient(app)

    # pack scan should accept either explicit paths or a preset.
    r = client.post(
        "/api/pack/scan",
        json={"paths": ["."], "excludes": [".git/"]},
    )
    assert r.status_code == 200
    j = r.json()
    assert "files" in j
    assert "sensitive" in j

    # SSE should produce the right content type and not buffer forever.
    jid = "test-job"
    job = Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=time.time(),
        finished_ts=time.time(),
        result={"ok": True},
    )
    with _JOBS_LOCK:
        _JOBS[jid] = job

    # In the Starlette TestClient, disconnect detection isn't always reliable,
    # so only test the finite (done) stream.
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        ct = r.headers.get("content-type") or ""
        assert "text/event-stream" in ct

        # Read a few chunks and ensure we got at least one SSE payload.
        data = b""
        for chunk in r.iter_bytes():
            data += chunk
            if b"data:" in data:
                break
        assert b"data:" in data
