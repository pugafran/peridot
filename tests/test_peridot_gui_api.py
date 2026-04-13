from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import peridot_gui


def test_peridot_cmd_prefix_falls_back_to_python_module(monkeypatch):
    # Simulate a Windows-like "fresh" environment where `peridot` is not on PATH.
    monkeypatch.delenv("PERIDOT_EXE", raising=False)

    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)

    parts = peridot_gui._peridot_cmd_prefix()
    assert parts[:2] == [sys.executable, "-m"]
    assert parts[2] == "peridot"


def test_gui_api_meta_settings_and_pack_scan(tmp_path: Path, monkeypatch):
    # Ensure meta/settings/scan endpoints respond with JSON.
    # Use a small temp file for scan.
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert "runtime" in meta
    assert "presets" in meta

    r = c.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "settings_path" in j

    r = c.post("/api/pack/scan", json={"paths": [str(p)], "excludes": []})
    assert r.status_code == 200
    scan = r.json()
    assert scan["files"] == 1
    assert scan["missing_paths"] == []
