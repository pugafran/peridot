import json
import time

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import peridot_gui


def test_gui_meta_settings_doctor_endpoints_smoke(monkeypatch):
    # Make sure /api/meta doesn't fail if the CLI isn't invokable.
    monkeypatch.setenv("PERIDOT_EXE", "definitely-not-a-real-command")
    app = peridot_gui.create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "runtime" in data
    assert "presets" in data

    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data

    # /api/doctor may fail if PERIDOT_EXE is invalid; ensure we get a clean error.
    r = client.get("/api/doctor")
    assert r.status_code in (200, 500)


def test_gui_sse_job_events_streams_until_done():
    app = peridot_gui.create_app()
    client = TestClient(app)

    # Inject a job directly (unit-test only).
    jid = "test-job"
    job = peridot_gui.Job(id=jid, kind="pack", status="running", created_ts=time.time())
    peridot_gui._JOBS[jid] = job

    # Flip the job to done shortly after the stream begins.
    def _finish():
        time.sleep(0.15)
        job.status = "done"
        job.finished_ts = time.time()
        job.result = {"output": "C:/tmp/out.peridot"}

    import threading

    threading.Thread(target=_finish, daemon=True).start()

    # Stream SSE and ensure we see at least one data event containing our job id.
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        raw = ""
        for chunk in r.iter_text():
            raw += chunk
            if "data:" in raw:
                break

    assert "data:" in raw
    # Extract the last data payload we saw and ensure it parses.
    last = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            last = line[len("data: ") :]
    assert last is not None
    payload = json.loads(last)
    assert payload["id"] == jid
    assert payload["status"] in ("running", "done")

    # Cleanup for isolation.
    peridot_gui._JOBS.pop(jid, None)
