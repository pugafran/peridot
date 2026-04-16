import json
import threading
import time

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import peridot_gui


@pytest.fixture()
def client(monkeypatch):
    app = peridot_gui.create_app()
    return TestClient(app)


def test_api_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "runtime" in data
    assert "presets" in data


def test_api_settings(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data


def test_pack_scan_smoke(client):
    r = client.post("/api/pack/scan", json={"paths": ["."], "excludes": []})
    assert r.status_code == 200
    data = r.json()
    assert "files" in data
    assert "bytes" in data


def test_pack_job_and_sse_events(client, monkeypatch):
    # Avoid spawning the real CLI in tests; we only validate the API plumbing + SSE.
    def fake_launch_job(job, peridot_args):
        job.status = "running"
        job.started_ts = time.time()
        time.sleep(0.02)
        job.result = {"ok": True, "output": "dummy.peridot"}
        job.status = "done"
        job.finished_ts = time.time()

    monkeypatch.setattr(peridot_gui, "_launch_job", fake_launch_job)

    r = client.post("/api/pack", json={"preset": "dummy", "name": "x", "paths": ["."], "excludes": []})
    assert r.status_code == 200
    jid = r.json()["job_id"]

    # Poll job endpoint
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["id"] == jid

    # SSE should yield at least one data event with JSON.
    with client.stream("GET", f"/api/jobs/{jid}/events") as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "data:" in buf:
                break
        # Extract first data line.
        lines = [ln for ln in buf.splitlines() if ln.startswith("data: ")]
        assert lines
        payload = json.loads(lines[0][len("data: ") :])
        assert payload["id"] == jid
        assert payload["status"] in {"running", "done", "error"}
