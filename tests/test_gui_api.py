import os
import sys
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
starlette_testclient = pytest.importorskip("starlette.testclient")

from peridot_gui import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _force_cli_invocation(monkeypatch):
    # Ensure GUI subprocess calls are stable in CI and on Windows.
    # Using python -m peridot avoids PATH/peridot.exe issues.
    monkeypatch.setenv("PERIDOT_EXE", f"{sys.executable} -m peridot")


@pytest.fixture()
def client():
    app = create_app()
    return starlette_testclient.TestClient(app)


def test_meta_doctor_settings_end_to_end(client):
    meta = client.get("/api/meta")
    assert meta.status_code == 200
    j = meta.json()
    assert "runtime" in j
    assert "peridot_cmd" in j

    doctor = client.get("/api/doctor")
    assert doctor.status_code == 200
    dj = doctor.json()
    assert isinstance(dj, (dict, list))

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    sj = settings.json()
    assert "settings_path" in sj


def test_pack_scan_and_pack_job_and_sse(tmp_path: Path, client):
    # Make a tiny file and pack it.
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")

    scan = client.post(
        "/api/pack/scan",
        json={"paths": [str(src)], "preset": "", "excludes": []},
    )
    assert scan.status_code == 200
    sj = scan.json()
    assert sj["files"] >= 1

    out_path = tmp_path / "bundle.peridot"

    r = client.post(
        "/api/pack",
        json={
            "name": "bundle",
            "paths": [str(src)],
            "preset": "",
            "excludes": [],
            "output": str(out_path),
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # SSE: read until the job is done (or at least one event arrives).
    # Starlette TestClient uses a requests-like API.
    seen_data = False
    final = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        assert s.status_code == 200
        for chunk in s.iter_text():
            if "data:" not in chunk:
                continue
            seen_data = True
            # Pull the last data line in this chunk.
            for line in chunk.splitlines():
                if line.startswith("data:"):
                    payload = line[len("data:") :].strip()
                    if payload:
                        final = payload
            if final and '"status": "done"' in final:
                break
            if final and '"status": "error"' in final:
                break

    assert seen_data, "expected at least one SSE data event"

    # Also check the job endpoint.
    j = client.get(f"/api/jobs/{job_id}").json()
    assert j["status"] in {"done", "error"}

    if j["status"] == "done":
        assert out_path.exists()
        assert out_path.stat().st_size > 0
