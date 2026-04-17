import json

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401
        from fastapi.testclient import TestClient  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps not installed (fastapi/testclient)")
def test_gui_meta_endpoint_shape():
    from peridot_gui import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    j = r.json()

    assert "peridot_cmd" in j
    assert "gui" in j and "base_url" in j["gui"]
    assert "runtime" in j and "os_name" in j["runtime"]
    assert "presets" in j and isinstance(j["presets"], list)


@pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps not installed (fastapi/testclient)")
def test_gui_settings_endpoint_works_without_cli(monkeypatch, tmp_path):
    from peridot_gui import create_app
    from fastapi.testclient import TestClient

    # Force settings to be read from a temp store so the test is isolated.
    import peridot as peridot_mod

    monkeypatch.setattr(peridot_mod, "DEFAULT_SETTINGS_STORE", tmp_path / "settings.json", raising=False)
    (tmp_path / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings" in j
    assert j["settings"].get("language") == "en"


@pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps not installed (fastapi/testclient)")
def test_gui_pack_scan_uses_preset_paths_if_none_supplied(monkeypatch, tmp_path):
    from peridot_gui import create_app
    from fastapi.testclient import TestClient

    import peridot as peridot_mod

    # Create a fake preset that points at a temp directory (cross-platform).
    monkeypatch.setattr(
        peridot_mod,
        "PRESET_LIBRARY",
        {
            "test-preset": {
                "description": "test",
                "platform": "windows",
                "shell": "powershell",
                "tags": ["test"],
                "paths": [str(tmp_path)],
            }
        },
        raising=False,
    )

    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    r = client.post("/api/pack/scan", json={"preset": "test-preset", "paths": []})
    assert r.status_code == 200
    j = r.json()

    assert j["preset"] == "test-preset"
    assert j["files"] >= 1
    assert "expanded_paths" in j


@pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps not installed (fastapi/testclient)")
def test_gui_sse_events_stream_job_state(monkeypatch):
    from peridot_gui import Job, _JOBS, _JOBS_LOCK, create_app
    from fastapi.testclient import TestClient

    # Insert a completed job and ensure the SSE endpoint yields at least one event.
    job = Job(id="job-1", kind="pack", status="done", created_ts=1.0, started_ts=1.0, finished_ts=2.0, result={"ok": True})
    with _JOBS_LOCK:
        _JOBS[job.id] = job

    app = create_app()
    client = TestClient(app)

    with client.stream("GET", f"/api/jobs/{job.id}/events") as r:
        assert r.status_code == 200
        data = b"".join(list(r.iter_bytes()))

    # The stream contains at least one data: {json}\n\n payload.
    assert b"data: " in data
    # Clean up shared state for isolation.
    with _JOBS_LOCK:
        _JOBS.pop(job.id, None)
