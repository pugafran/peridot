import os
import time
from pathlib import Path

import pytest


def _has_gui_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import starlette.testclient  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _has_gui_deps(), reason="GUI deps (fastapi/starlette) not installed")
def test_gui_api_endpoints_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure the GUI uses the in-repo CLI/module rather than relying on a
    # `peridot` executable being on PATH.
    monkeypatch.setenv("PERIDOT_EXE", f"{os.sys.executable} -m peridot")

    from peridot_gui import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    meta = client.get("/api/meta").json()
    assert "runtime" in meta
    assert "presets" in meta

    settings = client.get("/api/settings").json()
    assert "settings" in settings

    # pack scan (in-process)
    scan = client.post(
        "/api/pack/scan",
        json={
            "preset": (meta.get("presets") or [{}])[0].get("key") if meta.get("presets") else "",
            "paths": [str(tmp_path)],
            "excludes": [],
        },
    ).json()
    assert "files" in scan
    assert "sensitive" in scan

    # pack (subprocess job) using a tiny input file.
    tiny = tmp_path / "tiny.txt"
    tiny.write_text("hello", encoding="utf-8")

    r = client.post(
        "/api/pack",
        json={
            "name": "gui-test",
            "paths": [str(tiny)],
            "preset": "",
            "excludes": [],
            "output": str(tmp_path) + os.sep,
        },
    ).json()
    job_id = r["job_id"]

    # Poll the job (SSE is tested manually in the browser; here we just ensure
    # end-to-end completion).
    deadline = time.time() + 30
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in {"done", "error"}:
            break
        time.sleep(0.2)

    assert j["status"] == "done", j.get("error")
    out_path = j.get("result", {}).get("output")
    assert out_path
    assert Path(out_path).exists()
