from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps not installed (fastapi/starlette/uvicorn)")


def test_gui_meta_smoke():
    from peridot_gui import create_app

    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()

    assert "gui" in data
    assert "runtime" in data
    assert "presets" in data


def test_gui_pack_scan_smoke(tmp_path: Path):
    from peridot_gui import create_app

    from fastapi.testclient import TestClient

    # Create a small fixture directory to scan.
    root = tmp_path / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    r = client.post("/api/pack/scan", json={"paths": [str(root)], "excludes": []})
    assert r.status_code == 200
    out = r.json()

    assert out["files"] >= 1
    assert isinstance(out.get("sensitive_paths"), list)
    assert isinstance(out.get("sensitive"), list)


def test_gui_pack_job_and_sse_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from peridot_gui import create_app

    from fastapi.testclient import TestClient

    # Use module invocation to avoid relying on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    root = tmp_path / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    out_path = tmp_path / "out.peridot"

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(root)],
            "excludes": [],
            "output": str(out_path),
        },
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]

    # Open SSE and read at least one message event.
    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        assert s.status_code == 200
        assert "text/event-stream" in (s.headers.get("content-type") or "")
        # Consume a couple of lines; we should get at least one `data: ...`.
        got_data = False
        it = s.iter_lines()
        for _ in range(200):
            line = next(it)
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            # Skip keepalive/comments/empty lines.
            if not line or line.startswith(":") or line.startswith("retry:"):
                continue
            if line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
                assert payload["id"] == jid
                got_data = True
                break
        assert got_data

    # Wait for job completion (should be quick).
    deadline = time.time() + 15
    while True:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in {"done", "error"}:
            break
        if time.time() > deadline:
            raise AssertionError("job did not finish in time")
        time.sleep(0.2)

    assert j["status"] == "done", j.get("error")
    assert out_path.exists(), "expected output bundle to be created"
