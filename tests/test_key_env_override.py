from __future__ import annotations

import json
from pathlib import Path

import peridot


def test_doctor_respects_peridot_key_path_env(tmp_path: Path, monkeypatch, capsys):
    key_path = tmp_path / "custom.key"
    key_path.write_bytes(b"0" * 32)

    monkeypatch.setenv("PERIDOT_KEY_PATH", str(key_path))

    peridot.main(["doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    key_row = next(item for item in payload if item["check"] == "key")
    assert key_row["status"] == "ok"
    assert key_row["detail"] == str(key_path)


def test_doctor_expands_vars_in_peridot_key_path_env(tmp_path: Path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    key_path = fake_home / "peridot.key"
    key_path.write_bytes(b"0" * 32)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PERIDOT_KEY_PATH", "$HOME/peridot.key")

    peridot.main(["doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    key_row = next(item for item in payload if item["check"] == "key")
    assert key_row["status"] == "ok"
    assert key_row["detail"] == str(key_path)
