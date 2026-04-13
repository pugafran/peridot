import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("CI") == "true" and os.name == "nt", reason="flaky on some Windows CI browsers")
def test_gui_api_meta_smoke():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from peridot_gui import create_app

    app = create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert "runtime" in data
    assert "presets" in data
    assert "gui" in data


def test_gui_api_settings_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from peridot_gui import create_app

    # Ensure we don't touch a real user HOME config when running tests.
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    app = create_app()
    c = TestClient(app)

    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings_path" in data
    assert "settings" in data


def test_gui_api_pack_scan_returns_missing_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from peridot_gui import create_app

    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    existing = tmp_path / "exists.txt"
    existing.write_text("ok", encoding="utf-8")

    app = create_app()
    c = TestClient(app)

    r = c.post(
        "/api/pack/scan",
        json={
            "paths": [str(existing), str(tmp_path / "missing.txt")],
            "excludes": ["*.nope"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["files"] >= 1
    assert data["missing_paths"], "expected missing path to be reported"


def test_gui_api_sse_events_smoke(monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import peridot_gui
    from peridot_gui import Job, create_app

    app = create_app()
    c = TestClient(app)

    # Insert a finished job and ensure the SSE endpoint yields at least one data event.
    jid = "test-job"
    peridot_gui._JOBS[jid] = Job(
        id=jid,
        kind="pack",
        status="done",
        created_ts=0.0,
        started_ts=0.0,
        finished_ts=0.0,
        result={"ok": True},
        error=None,
    )

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        chunks = b"".join(r.iter_bytes())

    # We should see at least one 'data: {json}' message.
    assert b"data:" in chunks
    # And it should be valid JSON somewhere.
    payloads = []
    for line in chunks.splitlines():
        if line.startswith(b"data: "):
            payloads.append(json.loads(line[len(b"data: ") :].decode("utf-8")))
    assert payloads
    assert payloads[-1]["status"] in {"done", "error"}
