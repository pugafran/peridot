from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import peridot_gui


def test_gui_meta_smoke() -> None:
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.get("/api/meta")
    assert r.status_code == 200
    j = r.json()
    assert "gui" in j
    assert "runtime" in j
    assert "presets" in j


def test_gui_pack_scan_on_temp_dir(tmp_path: Path) -> None:
    # Create a couple of files to ensure collect_files can see something.
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.post(
        "/api/pack/scan",
        json={
            "paths": [str(tmp_path)],
            "excludes": [],
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j["files"] >= 2
    assert j["bytes"] >= 10
    assert "sensitive" in j


def test_gui_sse_job_events_done() -> None:
    app = peridot_gui.create_app()
    c = TestClient(app)

    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=time.time(),
        started_ts=time.time(),
        finished_ts=time.time(),
        result={"ok": True},
    )

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        buf = b""
        for chunk in r.iter_bytes():
            buf += chunk
            if b"data: " in buf:
                break
        # Extract the first `data: ...` payload.
        text = buf.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
        assert lines, f"no data lines in SSE stream: {text!r}"
        payload = json.loads(lines[0][len("data: ") :])
        assert payload["id"] == jid
        assert payload["status"] == "done"

    # Cleanup to avoid leaking between tests.
    peridot_gui._JOBS.pop(jid, None)
