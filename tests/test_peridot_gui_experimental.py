import json
from pathlib import Path

import pytest


def _client():
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    pytest.importorskip("starlette")

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    return TestClient(app)


def test_gui_api_meta_smoke():
    c = _client()
    r = c.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "runtime" in data
    assert "presets" in data


def test_gui_api_settings_smoke():
    c = _client()
    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data


def test_gui_api_pack_scan_smoke(tmp_path: Path):
    c = _client()

    # create a real file so scan has something to count
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")

    r = c.post(
        "/api/pack/scan",
        json={
            "preset": "",
            "paths": [str(tmp_path)],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["files"] >= 1
    assert "sensitive" in data


def test_gui_sse_job_events_stream():
    c = _client()

    import peridot_gui

    # Keep this test pure/in-process: it validates the SSE stream format without
    # depending on subprocess behavior.
    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=0.0,
        started_ts=0.0,
        finished_ts=0.0,
        result={"output": "x.peridot"},
        error=None,
    )

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        text = "".join(list(r.iter_text())[:10])

    # The stream must contain at least one data: JSON message.
    assert "data:" in text
    # Validate JSON payload shape from the first data: line.
    for ln in text.splitlines():
        if ln.startswith("data: "):
            payload = json.loads(ln[len("data: ") :])
            assert payload["id"] == jid
            assert payload["status"] == "done"
            break
    else:
        raise AssertionError("no data line found")


def test_gui_pack_job_end_to_end(tmp_path: Path, monkeypatch):
    c = _client()

    # Force the GUI to spawn the Peridot module via the current interpreter.
    # This is Windows-friendly and works in editable checkouts.
    import sys

    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    root = tmp_path / "src"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")

    out = tmp_path / "out.peridot"

    r = c.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(root)],
            "output": str(out),
            "excludes": [],
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Poll until completion (the job runs in a background thread).
    import time

    deadline = time.time() + 15
    while time.time() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in {"done", "error"}:
            break
        time.sleep(0.2)

    assert j["status"] == "done", j
    assert Path(j["result"]["output"]).exists()
