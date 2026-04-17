from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest


def _install_dummy_peridot(monkeypatch, *, tmp_path: Path):
    """Install a minimal in-memory `peridot` module for GUI API tests."""

    @dataclass
    class Entry:
        relative_path: str
        size: int

    m = types.ModuleType("peridot")
    m.DEFAULT_SETTINGS_STORE = tmp_path / "settings.json"
    m.DEFAULT_HISTORY_DIR = tmp_path / "history"
    m.DEFAULT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    def load_settings():
        return {"language": "en"}

    m.load_settings = load_settings

    m.PRESET_LIBRARY = {
        "win-powershell": {
            "description": "Windows PowerShell profile",
            "platform": "windows",
            "shell": "powershell",
            "tags": ["windows", "powershell"],
            "paths": [str(tmp_path / "proj")],
        }
    }

    def collect_files(paths):
        # Make the scan deterministic; pretend we discovered two files.
        return [
            Entry(relative_path="a.txt", size=10),
            Entry(relative_path=".env", size=5),
        ]

    def filter_entries(entries, excludes):
        excludes = set(excludes or [])
        out = []
        for e in entries:
            if e.relative_path in excludes:
                continue
            out.append(e)
        return out

    def detect_sensitive_entries(entries):
        return [e for e in entries if e.relative_path == ".env"]

    m.collect_files = collect_files
    m.filter_entries = filter_entries
    m.detect_sensitive_entries = detect_sensitive_entries

    monkeypatch.setitem(sys.modules, "peridot", m)
    return m


def test_gui_api_endpoints_smoke(monkeypatch, tmp_path: Path):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    pytest.importorskip("starlette")

    import peridot_gui

    _install_dummy_peridot(monkeypatch, tmp_path=tmp_path)

    # Avoid invoking a real CLI in /api/meta and /api/doctor.
    monkeypatch.setattr(peridot_gui, "_peridot_cmd_prefix", lambda: ["peridot"])  # pragma: no cover

    def fake_run(args):
        if args == ["doctor", "--json"]:
            return {"ok": True, "source": "fake"}
        if args == ["settings", "--json"]:
            return {"settings": {"language": "en"}}
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(peridot_gui, "_run_peridot_json", fake_run)

    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    client = TestClient(app)

    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "presets" in meta

    r = client.get("/api/doctor")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "settings" in r.json()

    # Scan should include sensitive list with reasons.
    r = client.post(
        "/api/pack/scan",
        json={"preset": "win-powershell", "paths": [], "excludes": []},
    )
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] >= 1
    assert any(x["path"] == ".env" for x in scan["sensitive"])


def test_gui_pack_job_and_sse_events(monkeypatch, tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    import peridot_gui

    _install_dummy_peridot(monkeypatch, tmp_path=tmp_path)

    # Force output dir to a temp dir so we don't write into cwd.
    monkeypatch.setattr(peridot_gui, "_default_output_dir", lambda: tmp_path)

    # Make job execution synchronous and deterministic.
    def fake_launch_job(job, peridot_args):
        job.status = "running"
        job.started_ts = 1.0
        job.result = {"output": str(tmp_path / "out.peridot"), "args": peridot_args}
        job.status = "done"
        job.finished_ts = 2.0

    monkeypatch.setattr(peridot_gui, "_launch_job", fake_launch_job)

    class _ImmediateThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            if self._target:
                self._target(*self._args)

    monkeypatch.setattr(peridot_gui.threading, "Thread", _ImmediateThread)

    from fastapi.testclient import TestClient

    app = peridot_gui.create_app()
    client = TestClient(app)

    r = client.post(
        "/api/pack",
        json={
            "preset": "win-powershell",
            "name": "bundle",
            "paths": [str(tmp_path)],
            "excludes": [],
            "output": "bundle.peridot",
        },
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]

    # Poll endpoint
    r2 = client.get(f"/api/jobs/{jid}")
    assert r2.status_code == 200
    j = r2.json()
    assert j["status"] == "done"
    assert j["result"]["output"].endswith(".peridot")

    # SSE endpoint should emit at least one JSON payload and finish.
    with client.stream("GET", f"/api/jobs/{jid}/events") as s:
        body = b"".join(list(s.iter_bytes()))

    # Find the first data: line and parse it.
    text = body.decode("utf-8", errors="replace")
    data_lines = [ln for ln in text.splitlines() if ln.startswith("data: ")]
    assert data_lines, text
    payload = json.loads(data_lines[-1].removeprefix("data: "))
    assert payload["id"] == jid
    assert payload["status"] == "done"
