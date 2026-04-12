from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
# uvicorn not required for TestClient


def _make_client(monkeypatch: pytest.MonkeyPatch):
    # Ensure the GUI uses the local module without requiring a separately
    # installed `peridot` executable (Windows-friendly dev default).
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app)


def test_meta_settings_doctor_endpoints(monkeypatch: pytest.MonkeyPatch):
    c = _make_client(monkeypatch)

    r = c.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "runtime" in j
    assert "presets" in j

    r = c.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j

    r = c.get("/api/doctor")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, dict)


def test_pack_scan_and_pack_job_sse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    c = _make_client(monkeypatch)

    # Create a tiny tree to pack.
    root = tmp_path / "input"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    # Scan
    r = c.post("/api/pack/scan", json={"paths": [str(root)], "excludes": []})
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] >= 1

    # Pack (explicit output path so the test doesn't depend on cwd)
    out = tmp_path / "out.peridot"
    r = c.post(
        "/api/pack",
        json={"name": "test-bundle", "paths": [str(root)], "output": str(out), "excludes": []},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert job_id

    # SSE: read a few events until done/error.
    done = False
    last = None
    with c.stream("GET", f"/api/jobs/{job_id}/events") as s:
        assert s.status_code == 200
        start = time.time()
        for line in s.iter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                payload = line[len("data: ") :]
                last = payload
                # We don't parse JSON here to keep the test resilient to
                # incremental schema changes.
                if '"status": "done"' in payload or '"status": "error"' in payload:
                    done = True
                    break
            if time.time() - start > 15:
                break

    assert done, f"job did not finish in time; last event: {last!r}"

    # Verify output exists.
    assert out.exists(), "expected packed bundle to be written"
    assert out.stat().st_size > 0
