import json
import threading
import time

import pytest


def _has_fastapi():
    try:
        import fastapi  # noqa: F401
        import starlette.testclient  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed (gui extra)")
def test_gui_api_meta_and_settings_smoke():
    from peridot_gui import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    r2 = client.get("/api/settings")
    assert r2.status_code == 200
    data = r2.json()
    assert "settings" in data


@pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed (gui extra)")
def test_gui_api_pack_scan_uses_preset_defaults_when_paths_empty():
    from peridot_gui import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    meta = client.get("/api/meta").json()
    presets = meta.get("presets") or []
    assert presets, "expected at least one preset exposed by /api/meta"

    preset_key = presets[0]["key"]
    r = client.post("/api/pack/scan", json={"preset": preset_key, "paths": [], "excludes": []})
    assert r.status_code == 200
    out = r.json()
    assert out.get("preset") == preset_key
    assert "missing_paths" in out
    assert "files" in out
    assert "sensitive" in out


@pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed (gui extra)")
def test_gui_sse_events_stream_job_updates():
    # Ensure /api/jobs/{id}/events yields valid SSE messages.
    import peridot_gui
    from peridot_gui import Job, create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    jid = "test-job-1"
    job = Job(id=jid, kind="pack", status="running", created_ts=time.time(), started_ts=time.time())
    peridot_gui._JOBS[jid] = job

    def finisher():
        time.sleep(0.15)
        job.status = "done"
        job.result = {"ok": True, "output": "dummy.peridot"}
        job.finished_ts = time.time()

    threading.Thread(target=finisher, daemon=True).start()

    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        assert r.status_code == 200
        # Read a few lines and ensure at least one data: event is present.
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            if "data: " in buf:
                break
        assert "data: " in buf

        # Ensure the payload is JSON parseable.
        line = [ln for ln in buf.splitlines() if ln.startswith("data: ")][0]
        payload = json.loads(line[len("data: ") :])
        assert payload["id"] == jid

    peridot_gui._JOBS.pop(jid, None)
