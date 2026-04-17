from __future__ import annotations

import time
from pathlib import Path

import pytest


def _client():
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    from fastapi.testclient import TestClient

    import peridot_gui as pg

    app = pg.create_app()
    return TestClient(app), pg


def test_gui_api_meta_smoke():
    client, _pg = _client()
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "gui" in data
    assert "runtime" in data
    assert isinstance(data.get("presets"), list)


def test_gui_api_settings_smoke():
    client, _pg = _client()
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data
    assert "settings_path" in data


def test_gui_api_doctor_smoke():
    client, _pg = _client()
    r = client.get("/api/doctor")
    assert r.status_code == 200
    data = r.json()
    # The shape can evolve; just ensure it's JSON and contains a few expected fields.
    assert isinstance(data, (dict, list))
    if isinstance(data, dict):
        assert "ok" in data or "checks" in data or "issues" in data
    else:
        assert data and isinstance(data[0], dict)
        assert "check" in data[0] or "status" in data[0]


def test_gui_api_pack_scan_in_process(tmp_path: Path):
    client, _pg = _client()

    # Create a tiny directory structure to scan.
    root = tmp_path / "cfg"
    root.mkdir()
    (root / "a.txt").write_text("hi", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")

    r = client.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": [str(root)],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["files"] >= 1
    assert isinstance(data.get("sensitive"), list)
    # Ensure we return the richer structure.
    assert all("path" in x and "reason" in x for x in data.get("sensitive") or [])


def test_gui_api_job_events_sse_smoke():
    client, pg = _client()

    # Create a synthetic job so we don't spawn subprocesses in tests.
    jid = "test-job"
    # Mark it done so the SSE generator terminates deterministically under TestClient.
    job = pg.Job(id=jid, kind="pack", status="done", created_ts=time.time(), finished_ts=time.time(), result={"ok": True})
    with pg._JOBS_LOCK:  # noqa: SLF001
        pg._JOBS[jid] = job  # noqa: SLF001

    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in (r.headers.get("content-type") or "")
        # The first chunk should be a comment or retry.
        first = next(r.iter_bytes())
        assert b":" in first or b"retry" in first

    # Cleanup
    with pg._JOBS_LOCK:  # noqa: SLF001
        pg._JOBS.pop(jid, None)  # noqa: SLF001
