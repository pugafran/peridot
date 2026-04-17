import json

import pytest


def _has_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_gui_deps(), reason="peridot_gui optional deps (fastapi) not installed")


def test_gui_meta_smoke():
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    data = r.json()

    assert "gui" in data
    assert "runtime" in data
    assert "presets" in data


def test_gui_doctor_uses_cli_json(monkeypatch):
    from fastapi.testclient import TestClient

    import peridot_gui

    monkeypatch.setattr(peridot_gui, "_run_peridot_json", lambda args: {"ok": True, "args": args})

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.get("/api/doctor")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_gui_pack_flow_sse(monkeypatch):
    """End-to-end shape test for /api/pack -> jobs -> SSE stream.

    We stub out the worker so this stays fast and deterministic.
    """

    from fastapi.testclient import TestClient

    import peridot_gui

    def fake_launch_job(job, peridot_args):
        job.status = "done"
        job.result = {"output": "C:/tmp/test.peridot", "progress": {"type": "pack_done"}}
        job.error = None

    monkeypatch.setattr(peridot_gui, "_launch_job", fake_launch_job)

    app = peridot_gui.create_app()
    c = TestClient(app)

    # Start a pack job.
    r = c.post(
        "/api/pack",
        json={"name": "test", "paths": ["/tmp"], "excludes": [], "preset": ""},
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]

    # Polling endpoint.
    r = c.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    assert r.json()["status"] in {"done", "error"}

    # SSE endpoint should emit at least one data frame.
    with c.stream("GET", f"/api/jobs/{jid}/events") as s:
        chunk = next(s.iter_bytes())
        assert b"data:" in chunk or b":" in chunk  # initial comment is allowed

        # Read until we see a JSON payload.
        buf = chunk
        for _ in range(20):
            if b"data:" in buf:
                break
            try:
                buf += next(s.iter_bytes())
            except StopIteration:
                break

        assert b"data:" in buf
        # Extract the JSON after the first data: line.
        lines = [ln for ln in buf.split(b"\n") if ln.startswith(b"data: ")]
        assert lines
        payload = json.loads(lines[0].split(b"data: ", 1)[1].decode("utf-8"))
        assert payload["id"] == jid
