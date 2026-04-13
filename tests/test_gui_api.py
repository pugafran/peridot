import json
import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
starlette_testclient = pytest.importorskip("starlette.testclient")

from peridot_gui import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _force_peridot_exe(monkeypatch):
    # Ensure the GUI uses the in-tree Peridot module via the current interpreter.
    # This is robust on Windows and in CI where `peridot` might not be on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")


@pytest.fixture()
def client():
    app = create_app()
    return starlette_testclient.TestClient(app)


def test_api_meta_smoke(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "runtime" in data
    assert "presets" in data
    assert "gui" in data and "base_url" in data["gui"]


def test_api_settings_smoke(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings_path" in data
    assert "settings" in data


def test_api_doctor_smoke(client):
    r = client.get("/api/doctor")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, (dict, list))


def test_pack_scan_and_pack_job_end_to_end(client, tmp_path: Path):
    # Create a tiny project.
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")

    scan = client.post(
        "/api/pack/scan",
        json={"paths": [str(tmp_path)]},
    )
    assert scan.status_code == 200
    scan_data = scan.json()
    assert scan_data["files"] >= 2
    assert scan_data["bytes"] >= 10
    assert isinstance(scan_data.get("sensitive"), list)

    out_path = tmp_path / "bundle.peridot"
    r = client.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(tmp_path)],
            "output": str(out_path),
            "excludes": [],
        },
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert jid

    # Poll for completion (job runs in a thread).
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{jid}")
        assert j.status_code == 200
        last = j.json()
        if last["status"] in {"done", "error"}:
            break
        time.sleep(0.15)

    assert last is not None
    assert last["status"] == "done", f"job failed: {last}"
    assert out_path.exists() and out_path.is_file()


def test_sse_events_smoke(client, tmp_path: Path):
    # Start a tiny pack job and ensure the SSE endpoint yields at least one event.
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    out_path = tmp_path / "bundle.peridot"
    r = client.post(
        "/api/pack",
        json={
            "name": "sse-bundle",
            "paths": [str(tmp_path)],
            "output": str(out_path),
            "excludes": [],
        },
    )
    jid = r.json()["job_id"]

    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        # Read the initial stream bytes.
        chunk = next(s.iter_bytes())
        assert b":" in chunk  # initial comment

        # Read until we see at least one data event.
        buf = chunk
        deadline = time.time() + 10
        while time.time() < deadline and b"data:" not in buf:
            try:
                buf += next(s.iter_bytes())
            except StopIteration:
                break
        assert b"data:" in buf

        # Best-effort: parse the first JSON payload.
        # (The stream may include comments/retry directives.)
        for ln in buf.splitlines():
            if ln.startswith(b"data:"):
                payload = json.loads(ln[len(b"data:") :].strip().decode("utf-8"))
                assert payload["id"] == jid
                assert payload["kind"] == "pack"
                break

    # Ensure job eventually completes.
    deadline = time.time() + 30
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in {"done", "error"}:
            assert j["status"] == "done", f"job failed: {j}"
            break
        time.sleep(0.2)
