import os
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Use the in-repo module rather than requiring an installed `peridot` binary.
    import sys

    # Windows-first: avoid hardcoding `python3` which doesn't exist on Windows.
    # Also quote sys.executable because it may contain spaces (e.g. Program Files).
    exe = sys.executable
    if " " in exe and not (exe.startswith('"') and exe.endswith('"')):
        exe = f"\"{exe}\""
    monkeypatch.setenv("PERIDOT_EXE", f"{exe} -m peridot")

    # Ensure pack outputs go to the temp dir if the test triggers a pack.
    monkeypatch.chdir(tmp_path)

    import peridot_gui  # noqa: WPS433

    app = peridot_gui.create_app()
    return TestClient(app)


def test_meta_smoke(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "runtime" in j
    assert "presets" in j


def test_settings_smoke(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j


def test_pack_scan_smoke(client, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")

    r = client.post(
        "/api/pack/scan",
        json={"paths": [str(p)], "excludes": []},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["files"] >= 1
    assert "sensitive" in j


def test_pack_job_and_events_smoke(client, tmp_path):
    # Keep it tiny: a single file.
    p = tmp_path / "b.txt"
    p.write_text("hello", encoding="utf-8")
    out = tmp_path / "bundle.peridot"

    r = client.post(
        "/api/pack",
        json={"name": "bundle", "paths": [str(p)], "output": str(out), "excludes": []},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Poll until done (SSE is hard to assert deterministically in TestClient,
    # but this ensures the job runner path works end-to-end).
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        jr = client.get(f"/api/jobs/{job_id}")
        assert jr.status_code == 200
        last = jr.json()
        if last["status"] in {"done", "error"}:
            break
        time.sleep(0.25)

    assert last is not None
    assert last["status"] == "done", last
    assert Path(last["result"]["output"]).exists()
