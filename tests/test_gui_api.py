from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest


def test_gui_api_meta_doctor_settings_pack_scan_and_sse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Lightweight end-to-end checks for the experimental GUI API.

    This intentionally avoids running real `peridot pack`/`apply` subprocesses.
    Instead we validate:
    - /api/meta, /api/doctor, /api/settings return JSON
    - /api/pack/scan works against real filesystem inputs
    - SSE stream (/api/jobs/{id}/events) emits at least one event and terminates
      when the job reaches done/error.
    """

    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"fastapi testclient unavailable: {exc}")

    import peridot_gui

    app = peridot_gui.create_app()
    client = TestClient(app)

    # --- /api/meta ---
    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    # --- /api/settings ---
    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "settings_path" in settings
    assert "settings" in settings

    # --- /api/doctor ---
    # This shells out to peridot CLI in JSON mode. It should work even when the
    # `peridot` executable isn't installed, because the GUI falls back to
    # `python -m peridot` when importable.
    r = client.get("/api/doctor")
    assert r.status_code == 200
    doctor = r.json()
    assert isinstance(doctor, (dict, list))

    # --- /api/pack/scan ---
    # Create a tiny directory with a sensitive-looking file.
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")
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
    scan = r.json()
    assert scan["files"] >= 1
    assert isinstance(scan.get("sensitive"), list)

    # --- SSE: /api/jobs/{id}/events ---
    jid = "test-job-1"
    job = peridot_gui.Job(id=jid, kind="pack", status="queued", created_ts=time.time())
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS[jid] = job

    def _finish_job():
        time.sleep(0.2)
        with peridot_gui._JOBS_LOCK:
            job.status = "done"
            job.finished_ts = time.time()
            job.result = {"ok": True}

    t = threading.Thread(target=_finish_job, daemon=True)
    t.start()

    # Stream and capture a few lines. We should see at least one `data:` event.
    got_data = False
    with client.stream("GET", f"/api/jobs/{jid}/events") as resp:
        assert resp.status_code == 200
        for raw in resp.iter_lines():
            line = (raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw))
            if line.startswith("data: "):
                got_data = True
                payload = json.loads(line[len("data: ") :])
                assert payload["id"] == jid
                if payload.get("status") in {"done", "error"}:
                    break

    assert got_data

    # Cleanup to avoid leaking global state across tests.
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS.pop(jid, None)
