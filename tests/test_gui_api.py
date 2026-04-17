import json
import os
import sys
import time
from pathlib import Path

import pytest


def _fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _fastapi_available(), reason="GUI deps not installed")


@pytest.fixture()
def gui_client(tmp_path, monkeypatch):
    """FastAPI client with an isolated HOME.

    Windows-first rationale: on Windows the GUI is often launched from a shortcut
    and cwd may be something like System32; also Peridot stores keys/settings in
    the user's home. For tests we isolate it.
    """

    from fastapi.testclient import TestClient

    # Isolate HOME-like variables.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "Downloads").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    # Ensure the GUI uses this repo's peridot module via the current interpreter.
    monkeypatch.setenv("PERIDOT_EXE", f"{os.environ.get('PYTHON', sys.executable)} -m peridot")

    from peridot_gui import create_app

    app = create_app()
    return TestClient(app)


def test_meta_settings_doctor(gui_client):
    meta = gui_client.get("/api/meta")
    assert meta.status_code == 200
    j = meta.json()
    assert "presets" in j
    assert "runtime" in j

    settings = gui_client.get("/api/settings")
    assert settings.status_code == 200
    sj = settings.json()
    assert "settings_path" in sj
    assert "settings" in sj

    doctor = gui_client.get("/api/doctor")
    assert doctor.status_code == 200
    dj = doctor.json()
    assert isinstance(dj, (dict, list))


def test_pack_scan_and_pack_job_sse(gui_client, tmp_path):
    # Create a tiny file tree to scan/pack.
    root = tmp_path / "data"
    root.mkdir()
    (root / "dotfile.txt").write_text("hello", encoding="utf-8")

    scan = gui_client.post(
        "/api/pack/scan",
        json={"paths": [str(root / "dotfile.txt")], "preset": "", "excludes": []},
    )
    assert scan.status_code == 200, scan.text
    sj = scan.json()
    assert sj["files"] >= 1
    assert "sensitive" in sj

    # Launch a real pack job.
    r = gui_client.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(root / "dotfile.txt")],
            "preset": "",
            "excludes": [],
            "output": "test-bundle.peridot",
        },
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert job_id

    # Consume SSE until we see terminal status (or stream ends).
    seen_terminal = False
    with gui_client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        assert s.status_code == 200
        for raw in s.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: ") :])
            if payload.get("status") in {"done", "error"}:
                seen_terminal = True
                break
    assert seen_terminal

    # Also verify we can fetch the final job state and the output exists.
    deadline = time.time() + 30
    final = None
    while time.time() < deadline:
        j = gui_client.get(f"/api/jobs/{job_id}")
        assert j.status_code == 200
        final = j.json()
        if final.get("status") in {"done", "error"}:
            break
        time.sleep(0.25)

    assert final is not None
    assert final["status"] == "done", final
    out_path = Path(final["result"]["output"])
    assert out_path.exists()
    assert out_path.is_file()
