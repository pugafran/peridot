import sys

import pytest


try:
    import fastapi  # noqa: F401
except Exception:  # pragma: no cover
    pytest.skip("fastapi not installed (gui extra)", allow_module_level=True)


def _make_client(monkeypatch):
    # Force peridot_gui to call the local module via the current interpreter,
    # so tests don't depend on an installed `peridot` executable.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app)


def test_api_meta(monkeypatch):
    c = _make_client(monkeypatch)
    r = c.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "runtime" in j
    assert "presets" in j


def test_api_settings(monkeypatch):
    c = _make_client(monkeypatch)
    r = c.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings_path" in j
    assert "settings" in j


def test_pack_scan_empty(monkeypatch):
    c = _make_client(monkeypatch)

    # Use an empty scan (no preset, no paths)
    r = c.post("/api/pack/scan", json={"paths": [], "excludes": []})
    assert r.status_code == 200
    j = r.json()
    assert j["files"] == 0
    assert j["bytes"] == 0


def test_sse_job_events_smoke(monkeypatch):
    c = _make_client(monkeypatch)

    # Create a tiny pack job; on empty paths it should error early in the CLI,
    # but we only care that the SSE endpoint responds and streams.
    r = c.post(
        "/api/pack",
        json={"name": "test-bundle", "paths": [], "excludes": []},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # The endpoint should be an SSE stream.
    with c.stream("GET", f"/api/jobs/{job_id}/events") as s:
        assert s.status_code == 200
        ct = s.headers.get("content-type", "")
        assert "text/event-stream" in ct

        # Read a little from the stream (should include at least an initial comment).
        chunk = next(s.iter_text())
        assert chunk
