import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")


def _mk_client(monkeypatch):
    # Ensure the GUI uses a predictable Peridot CLI invocation in tests.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app)


def test_gui_meta_doctor_settings_endpoints(monkeypatch):
    client = _mk_client(monkeypatch)

    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "gui" in meta
    assert "runtime" in meta

    r = client.get("/api/doctor")
    assert r.status_code == 200
    doctor = r.json()
    assert isinstance(doctor, (dict, list))

    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "settings" in settings


def test_gui_pack_scan_pack_and_sse_events(monkeypatch, tmp_path):
    client = _mk_client(monkeypatch)

    # Create a small file so pack has something deterministic.
    root = tmp_path / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    scan = client.post(
        "/api/pack/scan",
        json={"paths": [str(root)]},
    )
    assert scan.status_code == 200
    scanj = scan.json()
    assert scanj["files"] >= 1
    assert isinstance(scanj.get("sensitive"), list)

    out_path = tmp_path / "out.peridot"
    pack = client.post(
        "/api/pack",
        json={"name": "test-bundle", "paths": [str(root)], "output": str(out_path)},
    )
    assert pack.status_code == 200
    job_id = pack.json()["job_id"]
    assert job_id

    # SSE should yield at least one message and eventually complete.
    seen = 0
    done = False
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        assert s.status_code == 200
        for chunk in s.iter_text():
            if not chunk:
                continue
            # EventSource frames are separated by blank lines. We only care
            # about data frames.
            if "data:" not in chunk:
                continue
            seen += 1
            if '"status": "done"' in chunk or '"status":"done"' in chunk:
                done = True
                break
            if '"status": "error"' in chunk or '"status":"error"' in chunk:
                pytest.fail(f"job failed via SSE: {chunk}")
            if seen > 200:
                break

    # Fallback: poll job status in case the stream ended early.
    deadline = time.time() + 30
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] == "done":
            done = True
            break
        if j["status"] == "error":
            pytest.fail(j.get("error") or "job error")
        time.sleep(0.15)

    assert seen >= 1
    assert done
    assert out_path.exists() and out_path.is_file()
    assert out_path.stat().st_size > 0
