import json
import time
import uuid

import pytest


def _has_gui_deps():
    try:
        import fastapi  # noqa: F401
        import starlette.testclient  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _has_gui_deps(), reason="GUI deps not installed")


def test_api_meta_doctor_settings_smoke(monkeypatch):
    # Import inside test so skips work cleanly.
    from peridot_gui import create_app

    from starlette.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/meta")
        assert r.status_code == 200
        meta = r.json()
        assert "presets" in meta
        assert "runtime" in meta

        r = client.get("/api/settings")
        assert r.status_code == 200
        j = r.json()
        assert "settings_path" in j
        assert "settings" in j

        # doctor may fail if peridot CLI isn't available in PATH; but in tests it
        # should work via `python -m peridot` fallback.
        r = client.get("/api/doctor")
        assert r.status_code == 200
        data = r.json()
        # doctor output shape is CLI-defined; accept list or dict.
        assert isinstance(data, (list, dict))


def test_pack_scan_works_with_preset_defaults():
    import peridot as peridot_mod
    from peridot_gui import create_app

    from starlette.testclient import TestClient

    presets = list(getattr(peridot_mod, "PRESET_LIBRARY", {}).keys())
    assert presets, "Expected PRESET_LIBRARY to be non-empty"

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/api/pack/scan", json={"preset": presets[0], "paths": [], "excludes": []})
        assert r.status_code == 200
        out = r.json()
        assert out.get("preset") == presets[0]
        assert "missing_paths" in out
        assert "files" in out
        assert "sensitive" in out


def test_sse_events_stream_finishes_for_done_job():
    from peridot_gui import _JOBS, _JOBS_LOCK, Job, create_app

    from starlette.testclient import TestClient

    app = create_app()

    jid = str(uuid.uuid4())
    job = Job(id=jid, kind="pack", status="done", created_ts=time.time(), finished_ts=time.time(), result={"ok": True})
    with _JOBS_LOCK:
        _JOBS[jid] = job

    with TestClient(app) as client:
        # Use streaming so we can inspect SSE content.
        with client.stream("GET", f"/api/jobs/{jid}/events") as r:
            assert r.status_code == 200
            raw = b"".join(list(r.iter_raw()))

    text = raw.decode("utf-8", errors="replace")
    assert "retry:" in text
    assert "data:" in text
    # Data must be JSON.
    data_lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert data_lines
    payload = json.loads(data_lines[-1].replace("data: ", "", 1))
    assert payload["id"] == jid
    assert payload["status"] == "done"
