import json
import os
import time
from pathlib import Path

import pytest


def _have_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _have_gui_deps(), reason="GUI deps (fastapi) not installed")


def test_gui_api_meta_settings_doctor_smoke():
    from fastapi.testclient import TestClient

    import peridot_gui

    app = peridot_gui.create_app()
    client = TestClient(app)

    meta = client.get("/api/meta").json()
    assert "runtime" in meta
    assert "presets" in meta

    settings = client.get("/api/settings").json()
    assert "settings_path" in settings
    assert "settings" in settings

    # doctor depends on the CLI JSON subcommand and can vary by platform,
    # but it should at least return JSON.
    doctor = client.get("/api/doctor").json()
    assert isinstance(doctor, (dict, list))


def test_gui_pack_scan_pack_and_sse_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    import peridot_gui

    # Use the in-tree module so subprocess calls are stable in tests.
    import sys

    # Use the current interpreter to run the in-tree module.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")

    # Create a tiny file to pack.
    src = tmp_path / "hello.txt"
    src.write_text("hello", encoding="utf-8")

    app = peridot_gui.create_app()
    client = TestClient(app)

    scan = client.post(
        "/api/pack/scan",
        json={"paths": [str(src)], "excludes": []},
    ).json()
    assert scan["files"] == 1
    assert scan["bytes"] >= 5

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    r = client.post(
        "/api/pack",
        json={
            "name": "test-bundle",
            "paths": [str(src)],
            "output": str(out_dir) + ("\\\\" if os.name == "nt" else "/"),
            "excludes": [],
        },
    ).json()
    jid = r["job_id"]

    # SSE should stream at least one event and finish.
    last = None
    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        for raw in s.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: ") :])
            last = payload
            if payload.get("status") in {"done", "error"}:
                break

    assert last is not None
    assert last["status"] == "done", last

    # Poll job endpoint for final payload (should be done already, but keep it robust)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in {"done", "error"}:
            last = j
            break
        time.sleep(0.1)

    assert last["status"] == "done", last
    out_path = Path(last["result"]["output"])
    assert out_path.exists(), out_path
    assert out_path.suffix == ".peridot"
