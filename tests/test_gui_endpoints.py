import json
import time

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps (fastapi/starlette) not installed")


def test_gui_basic_endpoints():
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "gui" in meta

    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data


def test_gui_sse_job_events_smoke(monkeypatch):
    """Smoke-test SSE framing.

    We don't spawn real Peridot subprocesses here; we just insert a fake job into
    the in-memory job store and ensure the SSE endpoint yields at least one data
    frame.
    """

    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    c = TestClient(app)

    # Insert a fake job that's already done so the SSE stream terminates.
    jid = "test-job"
    job = peridot_gui.Job(id=jid, kind="pack", status="done", created_ts=time.time(), finished_ts=time.time(), result={"output": "C:/tmp/x.peridot"})
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS[jid] = job

    with c.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in (r.headers.get("content-type") or "")

        # Read a couple of lines; we should see either a comment or a data frame.
        lines = []
        for ln in r.iter_lines():
            if ln is None:
                continue
            s = ln.decode("utf-8") if isinstance(ln, (bytes, bytearray)) else str(ln)
            if s.strip() == "":
                # blank line separates SSE events
                if lines:
                    break
                continue
            lines.append(s)

        assert lines, "expected SSE prelude/data"

        # If we received a data: line, it must be valid JSON.
        data_lines = [x for x in lines if x.startswith("data: ")]
        if data_lines:
            payload = json.loads(data_lines[-1].removeprefix("data: "))
            assert payload["id"] == jid
            assert payload["status"] == "done"

    # cleanup
    with peridot_gui._JOBS_LOCK:
        peridot_gui._JOBS.pop(jid, None)
