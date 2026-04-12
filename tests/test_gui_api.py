from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi", reason="gui extra not installed")


def test_gui_api_meta_doctor_settings(monkeypatch):
    # Import lazily so the module doesn't become a hard dependency for base installs.
    import peridot_gui

    app = peridot_gui.create_app()

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        r = client.get("/api/meta")
        assert r.status_code == 200
        meta = r.json()
        assert "runtime" in meta
        assert "presets" in meta

        # settings should always succeed (in-process access)
        r = client.get("/api/settings")
        assert r.status_code == 200
        settings = r.json()
        assert "settings" in settings

        # doctor depends on the CLI, so we don't hard-fail if it errors in CI.
        # But it must return either 200 with JSON or 500 with a clean message.
        r = client.get("/api/doctor")
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)
        else:
            assert "detail" in r.json()


def test_gui_pack_scan_and_sse_events(tmp_path: Path, monkeypatch):
    import peridot_gui

    app = peridot_gui.create_app()

    from fastapi.testclient import TestClient

    # Build a small directory to scan.
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    with TestClient(app) as client:
        r = client.post(
            "/api/pack/scan",
            json={"preset": "", "paths": [str(root)], "excludes": []},
        )
        assert r.status_code == 200
        scan = r.json()
        assert scan["files"] >= 1
        assert scan["bytes"] >= 1

        # Inject a fake job that finishes quickly and ensure SSE yields JSON events.
        jid = "test-job"
        peridot_gui._JOBS[jid] = peridot_gui.Job(
            id=jid,
            kind="pack",
            status="running",
            created_ts=time.time(),
        )

        # Stream a few chunks; then mark done and ensure the generator can terminate.
        with client.stream("GET", f"/api/jobs/{jid}/events") as s:
            it = s.iter_bytes()

            # Read until we see a 'data:' line with JSON payload.
            buf = b""
            for _ in range(40):
                chunk = next(it)
                buf += chunk
                if b"data: " in buf:
                    break

            # There should be at least one JSON payload.
            data_lines = [ln for ln in buf.splitlines() if ln.startswith(b"data: ")]
            assert data_lines, buf.decode("utf-8", errors="replace")
            payload = json.loads(data_lines[-1][len(b"data: ") :].decode("utf-8"))
            assert payload["id"] == jid
            assert payload["status"] in {"running", "done", "error"}

            # Finish job; the server should stop streaming soon after.
            peridot_gui._JOBS[jid].status = "done"
            peridot_gui._JOBS[jid].finished_ts = time.time()

            # Drain a couple more chunks to let the generator observe 'done'.
            for _ in range(20):
                try:
                    next(it)
                except StopIteration:
                    break
