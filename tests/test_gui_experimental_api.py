import os
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")


def _mk_app():
    from peridot_gui import create_app

    return create_app()


def test_gui_meta_smoke():
    from fastapi.testclient import TestClient

    app = _mk_app()
    client = TestClient(app)
    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()

    assert "runtime" in j
    assert "presets" in j
    assert "gui" in j


def test_pack_scan_paths_smoke(tmp_path: Path):
    from fastapi.testclient import TestClient

    # Create a real file so collect_files() has something.
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("hello", encoding="utf-8")

    app = _mk_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack/scan",
        json={"paths": [str(d)], "excludes": []},
    )
    assert r.status_code == 200, r.text
    j = r.json()

    assert j["files"] >= 1
    assert j["bytes"] >= 1
    assert "missing_paths" in j


def test_sse_headers_smoke(monkeypatch):
    from fastapi.testclient import TestClient

    # Seed a fake job so the SSE route exists.
    import peridot_gui

    peridot_gui._JOBS.clear()
    peridot_gui._JOBS["jid"] = peridot_gui.Job(
        id="jid",
        kind="pack",
        status="done",
        created_ts=0.0,
        started_ts=0.0,
        finished_ts=0.0,
        result={"ok": True},
    )

    app = _mk_app()
    client = TestClient(app)

    with client.stream("GET", "/api/jobs/jid/events") as r:
        assert r.status_code == 200
        # Don't force-consume the stream; just validate key headers.
        assert r.headers.get("content-type", "").startswith("text/event-stream")
        assert "no-cache" in (r.headers.get("cache-control", ""))
