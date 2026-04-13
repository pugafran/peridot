import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def _make_client(monkeypatch):
    # Ensure the GUI uses a deterministic CLI invocation in tests.
    # Using sys.executable avoids relying on a `python` shim on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app), peridot_gui


def test_api_meta_smoke(monkeypatch):
    client, _ = _make_client(monkeypatch)

    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()

    assert "gui" in j
    assert "base_url" in j["gui"]
    assert isinstance(j.get("peridot_cmd"), list)
    assert "runtime" in j
    assert "presets" in j


def test_api_settings_smoke(monkeypatch):
    client, _ = _make_client(monkeypatch)

    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()

    assert "settings_path" in j
    assert "settings" in j


def test_api_doctor_smoke(monkeypatch):
    client, _ = _make_client(monkeypatch)

    r = client.get("/api/doctor")
    assert r.status_code == 200
    j = r.json()

    # doctor JSON shape isn't strictly fixed, but it should be JSON.
    assert isinstance(j, (dict, list))


def test_api_pack_scan_uses_real_paths(monkeypatch, tmp_path: Path):
    client, _ = _make_client(monkeypatch)

    # Create a tiny directory with one file to scan.
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    r = client.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": [str(root)],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    j = r.json()

    assert j["files"] >= 1
    assert j["bytes"] >= 1
    assert j["missing_paths"] == []


def test_sse_events_endpoint_finishes(monkeypatch):
    client, peridot_gui = _make_client(monkeypatch)

    # Create a fake job and ensure the events stream yields messages until done.
    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=time.time(),
        started_ts=time.time(),
        finished_ts=time.time(),
        result={"output": "x.peridot"},
    )

    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in (r.headers.get("content-type") or "")

        # Read a few lines; there should be at least one `data:` message.
        buf = ""
        for line in r.iter_text():
            buf += line
            if "data:" in buf:
                break

        assert "data:" in buf

    # Clean up so this test doesn't leak state across tests.
    peridot_gui._JOBS.pop(jid, None)
