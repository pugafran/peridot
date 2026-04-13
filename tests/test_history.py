from __future__ import annotations

import json
from pathlib import Path

import peridot


def test_history_json_output(tmp_path: Path, capsys, monkeypatch):
    history_root = tmp_path / "history"
    monkeypatch.setattr(peridot, "DEFAULT_HISTORY_DIR", history_root)

    bundle_dir = history_root / "demo"
    bundle_dir.mkdir(parents=True)

    a = bundle_dir / "2026-01-01.peridot"
    b = bundle_dir / "2026-01-02.peridot"
    a.write_bytes(b"a" * 3)
    b.write_bytes(b"b" * 5)

    peridot.main(["history", "demo", "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)

    assert payload["bundle"] == "demo"
    assert payload["history_root"] == str(bundle_dir)
    assert [s["name"] for s in payload["snapshots"]] == ["2026-01-01.peridot", "2026-01-02.peridot"]
    assert payload["snapshots"][0]["size_bytes"] == 3
    assert payload["snapshots"][1]["size_bytes"] == 5
    assert payload["snapshots"][0]["modified_at"].endswith("+00:00")


def test_history_human_output_no_snapshots(tmp_path: Path, capsys, monkeypatch):
    history_root = tmp_path / "history"
    monkeypatch.setattr(peridot, "DEFAULT_HISTORY_DIR", history_root)

    peridot.main(["history", "missing"])

    out = capsys.readouterr().out
    assert "No snapshots" in out
