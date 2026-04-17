"""Tests for the experimental FastAPI-based GUI.

These tests are intentionally lightweight and are skipped when optional GUI
dependencies are not installed.

We mainly validate that the API surface exists and that the most important
endpoints return a sane shape.
"""

from __future__ import annotations

import json

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from fastapi.testclient import TestClient  # noqa: E402


def _client():
    from peridot_gui import create_app  # noqa: WPS433 (import inside helper)

    return TestClient(create_app())


def test_meta_smoke():
    c = _client()
    r = c.get("/api/meta")
    assert r.status_code == 200
    data = r.json()

    assert "peridot_cmd" in data
    assert "runtime" in data
    assert "presets" in data

    # Presets should be a list of dicts with at least a key.
    presets = data.get("presets")
    assert isinstance(presets, list)
    assert all(isinstance(p, dict) and p.get("key") for p in presets)


def test_settings_smoke():
    c = _client()
    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings_path" in data
    assert "settings" in data


def test_pack_scan_accepts_paths_and_returns_sensitive_shape(tmp_path):
    c = _client()

    # Create a tiny tree with a known-sensitive file.
    root = tmp_path / "root"
    root.mkdir()
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "note.txt").write_text("hi\n", encoding="utf-8")

    r = c.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": [str(root)],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    data = r.json()

    assert data.get("files") >= 1
    assert "expanded_paths" in data

    # New preferred shape: sensitive is a list of {path, reason}.
    sensitive = data.get("sensitive")
    assert isinstance(sensitive, list)
    if sensitive:
        assert isinstance(sensitive[0], dict)
        assert "path" in sensitive[0]
        assert "reason" in sensitive[0]

    # Back-compat list also present.
    sensitive_paths = data.get("sensitive_paths")
    assert isinstance(sensitive_paths, list)


def test_job_events_sse_smoke():
    c = _client()

    # Create a fake job by calling a lightweight endpoint that launches a job.
    # We avoid relying on pack/apply because those can be slow or require
    # platform-specific fixtures.
    #
    # Instead, we insert a minimal job via the internal module globals.
    import time
    import uuid

    import peridot_gui as gui

    jid = str(uuid.uuid4())
    job = gui.Job(id=jid, kind="test", status="done", created_ts=time.time(), finished_ts=time.time(), result={"ok": True})
    with gui._JOBS_LOCK:  # noqa: SLF001 (tests)
        gui._JOBS[jid] = job  # noqa: SLF001

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        # Read a couple of SSE chunks and ensure at least one data line appears.
        it = r.iter_text()
        chunks = []
        for _ in range(16):
            try:
                ch = next(it)
            except StopIteration:
                break
            chunks.append(ch)
            if "data:" in ch:
                break
        joined = "".join(chunks)
        assert "data:" in joined
        # Validate payload is JSON.
        line = [ln for ln in joined.splitlines() if ln.startswith("data: ")][0]
        payload = json.loads(line.replace("data: ", "", 1))
        assert payload.get("id") == jid
        assert payload.get("status") in {"done", "error", "running", "queued"}
