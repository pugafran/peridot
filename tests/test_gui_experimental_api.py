import json
import os
import sys
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def _client(monkeypatch):
    # Force the GUI to invoke the repo's Peridot via the current interpreter.
    # This is cross-platform and avoids relying on `peridot` being on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    from peridot_gui import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    return TestClient(app)


def test_meta_doctor_settings(monkeypatch):
    c = _client(monkeypatch)

    meta = c.get("/api/meta")
    assert meta.status_code == 200
    j = meta.json()
    assert "peridot_cmd" in j

    doctor = c.get("/api/doctor")
    assert doctor.status_code == 200
    # `peridot doctor --json` returns a JSON list of checks.
    assert isinstance(doctor.json(), list)

    settings = c.get("/api/settings")
    assert settings.status_code == 200
    sj = settings.json()
    assert "settings" in sj


def test_pack_scan_and_pack_job(monkeypatch, tmp_path: Path):
    c = _client(monkeypatch)

    # Create a small directory to pack.
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    scan = c.post(
        "/api/pack/scan",
        json={"paths": [str(root)], "excludes": []},
    )
    assert scan.status_code == 200
    sj = scan.json()
    assert sj["files"] >= 1
    assert isinstance(sj.get("sensitive"), list)

    out = tmp_path / "out.peridot"
    r = c.post(
        "/api/pack",
        json={"name": "bundle", "paths": [str(root)], "excludes": [], "output": str(out)},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Poll until done (job runs in a background thread).
    deadline = time.time() + 25
    last = None
    while time.time() < deadline:
        st = c.get(f"/api/jobs/{job_id}")
        assert st.status_code == 200
        last = st.json()
        if last["status"] in {"done", "error"}:
            break
        time.sleep(0.2)

    assert last is not None
    assert last["status"] == "done", f"job failed: {last}"
    assert last.get("result")
    assert Path(last["result"]["output"]).exists()


def test_sse_stream_starts(monkeypatch, tmp_path: Path):
    c = _client(monkeypatch)

    root = tmp_path / "src"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    out = tmp_path / "out.peridot"
    r = c.post(
        "/api/pack",
        json={"name": "bundle", "paths": [str(root)], "excludes": [], "output": str(out)},
    )
    job_id = r.json()["job_id"]

    # Starlette's TestClient supports streaming responses.
    with c.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        ct = resp.headers.get("content-type") or ""
        assert ct.startswith("text/event-stream")

        # Ensure at least one data: line arrives.
        buf = b""
        for chunk in resp.iter_raw():
            buf += chunk
            if b"data:" in buf:
                break
        assert b"data:" in buf

        # Parse one message payload best-effort.
        # (The stream may end quickly if the job finishes.)
        text = buf.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
        if lines:
            payload = json.loads(lines[-1].removeprefix("data: "))
            assert payload.get("id") == job_id
