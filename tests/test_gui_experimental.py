import json

import pytest


def _have_fastapi():
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_fastapi(), reason="fastapi/starlette not installed (optional gui extra)")
def test_gui_endpoints_meta_settings_doctor_scan_pack_sse(tmp_path, monkeypatch):
    # Import lazily so skipif can run without GUI deps.
    import peridot_gui

    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    c = TestClient(app)

    # meta
    r = c.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert isinstance(meta.get("presets"), list)

    # settings
    r = c.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "settings" in data

    # doctor can be slow-ish / may fail if peridot isn't on PATH in some envs,
    # but in tests we at least want it to return HTTP 200 (it shells out).
    r = c.get("/api/doctor")
    assert r.status_code == 200

    # scan: explicit paths to keep test deterministic.
    p = tmp_path / "a.txt"
    p.write_text("hi", encoding="utf-8")

    r = c.post("/api/pack/scan", json={"preset": "", "paths": [str(p)], "excludes": []})
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] == 1

    # pack: write output to tmp dir
    out = tmp_path / "bundle.peridot"
    r = c.post(
        "/api/pack",
        json={
            "preset": "",
            "name": "t",
            "paths": [str(p)],
            "excludes": [],
            "output": str(out),
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # poll job
    r = c.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    job = r.json()
    assert job["status"] in {"queued", "running", "done", "error"}

    # SSE endpoint should at least start streaming and yield data: lines.
    with c.stream("GET", f"/api/jobs/{job_id}/events") as s:
        it = s.iter_bytes()

        # read a bit of the stream
        chunk = next(it)
        assert b":" in chunk or b"data:" in chunk

        # drain a couple messages and ensure JSON parses.
        buf = chunk
        for _ in range(6):
            try:
                buf += next(it)
            except StopIteration:
                break
        # find first data line
        for ln in buf.splitlines():
            if ln.startswith(b"data: "):
                payload = json.loads(ln[len(b"data: ") :].decode("utf-8"))
                assert payload["id"] == job_id
                break
