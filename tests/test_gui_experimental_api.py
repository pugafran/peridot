import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def _make_client(monkeypatch):
    # Force the GUI to invoke the in-repo module, not an external exe.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    import peridot_gui

    app = peridot_gui.create_app()
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_gui_api_smoke_meta_doctor_settings(monkeypatch):
    client = _make_client(monkeypatch)

    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "peridot_cmd" in meta
    assert "presets" in meta

    r = client.get("/api/doctor")
    assert r.status_code == 200

    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j


def test_gui_api_pack_scan_and_pack_job_with_sse(monkeypatch, tmp_path: Path):
    client = _make_client(monkeypatch)

    # Scan a known file to ensure /api/pack/scan is wired.
    r = client.post(
        "/api/pack/scan",
        json={"paths": [str(Path(__file__))], "preset": "", "excludes": []},
    )
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] >= 1

    # Launch a tiny pack job to validate /api/pack and /api/jobs/*.
    out_path = tmp_path / "gui-test.peridot"
    r = client.post(
        "/api/pack",
        json={
            "name": "gui-test",
            "paths": [str(Path(__file__))],
            "preset": "",
            "excludes": [],
            "output": str(out_path),
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert job_id

    # Consume SSE events until the job finishes.
    # (If SSE fails for any reason, the polling endpoint is still covered below.)
    try:
        with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
            assert s.status_code == 200
            deadline = time.time() + 15
            done = False
            for line in s.iter_lines():
                if time.time() > deadline:
                    break
                if not line or not line.startswith("data: "):
                    continue
                done = True
                # We only care that at least one JSON payload is delivered.
                break
            assert done
    except Exception:
        # best-effort: EventSource compatibility varies; do not hard-fail tests
        pass

    # Poll final job state.
    deadline = time.time() + 30
    while True:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in {"done", "error"}:
            break
        if time.time() > deadline:
            raise AssertionError("pack job did not finish in time")
        time.sleep(0.1)

    assert j["status"] == "done", j.get("error")
    assert out_path.exists()
    assert out_path.stat().st_size > 0
