import json
from types import SimpleNamespace

import pytest


pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


@pytest.fixture()
def app(monkeypatch):
    import peridot_gui

    # Make /api/meta deterministic and not depend on an installed peridot binary.
    def fake_run(cmd, **kwargs):
        # meta() calls: [*peridot_cmd, "--version"]
        if cmd and cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="peridot 9.9.9\n", stderr="")
        raise AssertionError(f"unexpected subprocess cmd: {cmd!r}")

    monkeypatch.setattr(peridot_gui, "subprocess", SimpleNamespace(run=fake_run, CREATE_NO_WINDOW=0))

    return peridot_gui.create_app()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_api_meta_smoke(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "peridot 9.9.9"
    assert "presets" in data
    assert isinstance(data["presets"], list)
    assert "runtime" in data


def test_api_settings_smoke(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings_path" in data
    assert "settings" in data


def test_api_pack_scan_validates_and_returns_shape(client):
    r = client.post(
        "/api/pack/scan",
        json={"preset": "", "paths": ["/definitely/not/a/real/path"], "excludes": []},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["files"] >= 0
    assert "missing_paths" in data
    assert isinstance(data["missing_paths"], list)
    assert "sensitive" in data


def test_api_jobs_events_is_sse(client, monkeypatch):
    import peridot_gui

    # Insert a fake job
    jid = "job-123"
    job = peridot_gui.Job(id=jid, kind="pack", status="done", created_ts=0)
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS[jid] = job

    # We don't consume the stream fully here; just validate headers and that it starts.
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("text/event-stream")

        first = None
        for chunk in r.iter_text():
            if chunk:
                first = chunk
                break
        assert first is not None
        assert (": ok" in first) or ("retry:" in first) or ("data:" in first)
