import json
from types import SimpleNamespace

import pytest


def test_gui_api_endpoints_smoke(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    import peridot_gui

    # Avoid depending on a `peridot` executable in PATH.
    def fake_run_peridot_json(args):
        if args == ["doctor", "--json"]:
            return {"ok": True, "args": args}
        raise RuntimeError("unexpected args")

    monkeypatch.setattr(peridot_gui, "_run_peridot_json", fake_run_peridot_json)

    # Make /api/meta stable by faking subprocess.run used for `peridot --version`.
    def fake_subprocess_run(cmd, **kwargs):
        assert cmd[:1]
        if cmd[1:] == ["--version"] or cmd == ["peridot", "--version"]:
            return SimpleNamespace(returncode=0, stdout="peridot 0.0.0-test\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(peridot_gui.subprocess, "run", fake_subprocess_run)

    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta

    r = c.get("/api/doctor")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data


def test_gui_sse_streams_job_state():
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    import peridot_gui
    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    c = TestClient(app)

    jid = "test-job"
    peridot_gui._JOBS[jid] = peridot_gui.Job(id=jid, kind="pack", status="running", created_ts=0.0)

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        # Read a few SSE lines and ensure at least one data: payload appears.
        it = r.iter_lines()
        for _ in range(50):
            ln = next(it).decode("utf-8", errors="replace")
            if ln.startswith("data: "):
                payload = json.loads(ln[len("data: ") :])
                assert payload["id"] == jid
                break
        else:
            raise AssertionError("no SSE data line received")
