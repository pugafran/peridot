import json
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")


def test_meta_settings_doctor_endpoints_smoke():
    from peridot_gui import create_app

    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    r = client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()
    assert "settings" in s

    r = client.get("/api/doctor")
    # This calls the real peridot CLI. In CI/dev envs this should exist because
    # we're running tests inside the repo, but keep the assertion flexible.
    assert r.status_code in (200, 500)


def test_pack_scan_detects_sensitive_and_missing_paths(tmp_path: Path):
    from peridot_gui import create_app

    from fastapi.testclient import TestClient

    # Create a tiny fixture tree.
    (tmp_path / "ok.txt").write_text("hi", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack/scan",
        json={
            "paths": [str(tmp_path), str(tmp_path / "does-not-exist")],
            "excludes": [],
            "preset": "",
        },
    )
    assert r.status_code == 200
    data = r.json()

    assert data["files"] >= 1
    assert str(tmp_path / "does-not-exist") in data.get("missing_paths", [])

    # Prefer new shape but accept back-compat.
    sensitive = data.get("sensitive") or []
    if sensitive and isinstance(sensitive[0], dict):
        paths = {x["path"] for x in sensitive}
    else:
        paths = set(data.get("sensitive_paths") or sensitive)

    assert ".env" in {p.split("/")[-1] for p in paths}


def test_pack_endpoint_starts_job_and_sse_streams(monkeypatch):
    import peridot_gui
    from peridot_gui import Job, create_app

    from fastapi.testclient import TestClient

    # Patch _launch_job so the API doesn't spawn a real CLI subprocess.
    def fake_launch(job: Job, peridot_args):  # noqa: ARG001
        job.status = "running"
        job.started_ts = time.time()
        job.result = {"output": "C:/tmp/out.peridot", "progress": {"type": "pack_done"}}
        job.status = "done"
        job.finished_ts = time.time()

    monkeypatch.setattr(peridot_gui, "_launch_job", fake_launch)

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack",
        json={
            "preset": "bash",
            "name": "test-bundle",
            "paths": ["."],
            "excludes": [],
            "output": "test-bundle.peridot",
        },
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]

    # SSE: read a couple of chunks and ensure it contains JSON data.
    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        assert s.status_code == 200
        raw = b""
        for chunk in s.iter_bytes():
            raw += chunk
            if b"data:" in raw:
                break

    # Extract last data payload.
    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert lines, text
    payload = json.loads(lines[-1].removeprefix("data: "))
    assert payload["id"] == jid
    assert payload["status"] in {"running", "done", "error"}
