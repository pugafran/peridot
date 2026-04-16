import json
import os
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
starlette_testclient = pytest.importorskip("starlette.testclient")


def _mk_app_and_client():
    from peridot_gui import create_app

    app = create_app()
    return starlette_testclient.TestClient(app)


def test_gui_api_meta_doctor_settings_smoke(monkeypatch):
    client = _mk_app_and_client()

    meta = client.get("/api/meta")
    assert meta.status_code == 200
    j = meta.json()
    assert "runtime" in j
    assert "presets" in j

    doctor = client.get("/api/doctor")
    assert doctor.status_code == 200
    # doctor output is CLI-defined; just ensure JSON decodes.
    assert isinstance(doctor.json(), (dict, list))

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    sj = settings.json()
    assert "settings_path" in sj
    assert "settings" in sj


def test_gui_api_pack_scan_real_files(tmp_path):
    # create a small file so collect_files() finds something
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    client = _mk_app_and_client()

    r = client.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": [str(root)],
            "excludes": [],
        },
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["files"] >= 1
    assert j["bytes"] >= 1
    assert "sensitive" in j
    assert "missing_paths" in j
    assert "skipped_paths" in j


def test_gui_api_job_sse_emits_json_event(monkeypatch):
    client = _mk_app_and_client()

    import peridot_gui

    # Insert a finished job so the SSE endpoint completes quickly.
    jid = "test-job-1"
    job = peridot_gui.Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=time.time(),
        started_ts=time.time(),
        finished_ts=time.time(),
        result={"output": "C:/tmp/out.peridot"},
        error=None,
    )
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS[jid] = job

    with client.stream("GET", f"/api/jobs/{jid}/events") as resp:
        assert resp.status_code == 200
        # Consume until we see a data line.
        payload = None
        for chunk in resp.iter_text():
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: ") :])
                    break
            if payload is not None:
                break

    assert payload is not None
    assert payload["id"] == jid
    assert payload["status"] == "done"
    assert payload["result"]["output"]
