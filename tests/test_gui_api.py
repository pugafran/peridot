import json
import time
from pathlib import Path

import pytest


pytest.importorskip("fastapi")


def test_gui_meta_doctor_settings_packscan_smoke(tmp_path, monkeypatch):
    import peridot_gui
    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    client = TestClient(app)

    # /api/meta
    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    # /api/settings
    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "settings_path" in settings
    assert "settings" in settings

    # /api/doctor
    r = client.get("/api/doctor")
    assert r.status_code == 200
    doc = r.json()
    assert isinstance(doc, (dict, list))

    # /api/pack/scan should work in-process.
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.txt").write_text("hello", encoding="utf-8")
    (d / "b.txt").write_text("world", encoding="utf-8")

    r = client.post(
        "/api/pack/scan",
        json={"paths": [str(d)], "preset": "", "excludes": []},
    )
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] >= 2
    assert scan["bytes"] >= 10
    assert "sensitive" in scan
    assert "missing_paths" in scan


def test_gui_pack_job_and_sse_events(tmp_path, monkeypatch):
    import peridot_gui
    from fastapi.testclient import TestClient

    # Patch _launch_job so the test doesn't depend on spawning subprocesses.
    def fake_launch_job(job, peridot_args):
        job.status = "running"
        job.started_ts = time.time()
        # Simulate progress then completion.
        job.result = {"progress": {"type": "pack_progress", "files_done": 1, "files_total": 1}}
        job.status = "done"
        job.finished_ts = time.time()

    monkeypatch.setattr(peridot_gui, "_launch_job", fake_launch_job)

    app = peridot_gui.create_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(tmp_path)],
            "preset": "",
            "excludes": [],
            "output": str(tmp_path / "out.peridot"),
        },
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert jid

    # Read SSE and confirm we eventually see a done status.
    got_done = False
    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        for line in s.iter_lines():
            if not line:
                continue
            # TestClient yields str lines.
            if line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
                if payload.get("status") == "done":
                    got_done = True
                    break

    assert got_done

    # And normal polling endpoint should match.
    r2 = client.get(f"/api/jobs/{jid}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "done"
