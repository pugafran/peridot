from __future__ import annotations

import json
from pathlib import Path

import peridot


def test_init_respects_peridot_settings_path_env(tmp_path: Path, monkeypatch, capsys):
    key_path = tmp_path / "peridot.key"
    settings_path = tmp_path / "custom-settings.json"

    monkeypatch.setenv("PERIDOT_SETTINGS_PATH", str(settings_path))

    peridot.main(["--key", str(key_path), "init", "--force", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["settings_path"] == str(settings_path)
    assert settings_path.exists()


def test_init_expands_vars_in_peridot_settings_path_env(tmp_path: Path, monkeypatch, capsys):
    """PERIDOT_SETTINGS_PATH should support $HOME-style variables.

    This makes it easier to configure Peridot via shell profiles.
    """

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    key_path = tmp_path / "peridot.key"
    settings_path = fake_home / "custom-settings.json"

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PERIDOT_SETTINGS_PATH", "$HOME/custom-settings.json")

    peridot.main(["--key", str(key_path), "init", "--force", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["settings_path"] == str(settings_path)
    assert settings_path.exists()
