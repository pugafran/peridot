from __future__ import annotations

import json
from pathlib import Path

import peridot


def test_doctor_respects_peridot_profiles_path_env(tmp_path: Path, monkeypatch, capsys):
    key_path = tmp_path / "peridot.key"
    profiles_path = tmp_path / "custom-profiles.json"

    # Ensure the file exists so doctor marks it as ok.
    profiles_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setenv("PERIDOT_PROFILES_PATH", str(profiles_path))

    peridot.main(["--key", str(key_path), "doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    profiles_row = next(item for item in payload if item["check"] == "profiles")
    assert profiles_row["status"] == "ok"
    assert profiles_row["detail"] == str(profiles_path)


def test_doctor_expands_vars_in_peridot_profiles_path_env(tmp_path: Path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    key_path = tmp_path / "peridot.key"
    profiles_path = fake_home / "profiles.json"
    profiles_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PERIDOT_PROFILES_PATH", "$HOME/profiles.json")

    peridot.main(["--key", str(key_path), "doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    profiles_row = next(item for item in payload if item["check"] == "profiles")
    assert profiles_row["detail"] == str(profiles_path)
