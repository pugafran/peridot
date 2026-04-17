import time
from pathlib import Path


def test_gui_meta_doctor_settings_endpoints_work(tmp_path):
    # FastAPI is an optional dependency of the GUI.
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    c = TestClient(app)

    meta = c.get("/api/meta")
    assert meta.status_code == 200
    j = meta.json()
    assert "gui" in j and "base_url" in j["gui"]
    assert "presets" in j and isinstance(j["presets"], list)

    # settings should be served even if CLI JSON settings changes.
    settings = c.get("/api/settings")
    assert settings.status_code == 200
    sj = settings.json()
    assert "settings" in sj

    # doctor should be real end-to-end (subprocess) so the GUI can debug installs.
    doctor = c.get("/api/doctor")
    assert doctor.status_code == 200
    dj = doctor.json()
    assert isinstance(dj, (dict, list))


def test_gui_pack_scan_and_pack_job_with_progress(tmp_path):
    from fastapi.testclient import TestClient

    import peridot_gui

    # Create a small directory to scan/pack.
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hello.txt").write_text("hi", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")

    app = peridot_gui.create_app()
    c = TestClient(app)

    scan = c.post(
        "/api/pack/scan",
        json={"paths": [str(root)], "excludes": []},
    )
    assert scan.status_code == 200
    scanj = scan.json()
    assert scanj["files"] >= 1
    sens = scanj.get("sensitive") or []
    assert any(str(x.get("path", "")).replace("\\", "/").endswith("/.env") or str(x.get("path", "")) == ".env" for x in sens)

    out_file = tmp_path / "out.peridot"

    r = c.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(root)],
            "output": str(out_file),
            # exclude the env file by path, just like the UI does
            "excludes": [".env"],
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Poll the job until completion. This exercises the background thread job runner.
    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        j = c.get(f"/api/jobs/{job_id}")
        assert j.status_code == 200
        last = j.json()
        if last["status"] in {"done", "error"}:
            break
        time.sleep(0.2)

    assert last is not None
    assert last["status"] == "done", last
    assert Path(last["result"]["output"]).exists()


def test_gui_job_events_sse_smoke(tmp_path):
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    c = TestClient(app)

    # Create a fast "pack" job so the SSE endpoint has something to stream.
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")

    out_file = tmp_path / "sse.peridot"
    r = c.post(
        "/api/pack",
        json={"name": "sse", "paths": [str(root)], "output": str(out_file)},
    )
    job_id = r.json()["job_id"]

    with c.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/event-stream" in ct
        # Read a small chunk. The endpoint starts with a comment line.
        chunk = next(resp.iter_bytes())
        assert chunk.startswith(b":")
