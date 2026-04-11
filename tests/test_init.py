from pathlib import Path

import json

import peridot


def test_init_creates_key_and_settings(tmp_path: Path, capsys):
    key_path = tmp_path / "peridot.key"

    # Force settings to be created in this temp HOME.
    # We rely on DEFAULT_SETTINGS_STORE under Path.home().
    # Patch HOME so Path.home() points into tmp.
    # The default settings path is captured at import time (DEFAULT_SETTINGS_STORE),
    # so we assert against that constant directly.
    peridot.main(["--key", str(key_path), "init", "--force"])

    out = capsys.readouterr().out
    assert "Peridot initialized" in out
    assert key_path.exists()
    assert peridot.DEFAULT_SETTINGS_STORE.exists()


def test_init_json_output(tmp_path: Path, capsys):
    key_path = tmp_path / "peridot.key"

    peridot.main(["--key", str(key_path), "init", "--force", "--json"])

    out = capsys.readouterr().out
    assert "Peridot initialized" not in out
    payload = json.loads(out)
    assert payload["key_path"].endswith("peridot.key")
    assert payload["fingerprint"]
    assert payload["settings_path"] == str(peridot.DEFAULT_SETTINGS_STORE)
    assert payload["created_settings"] is True


def test_spanish_language_hint_does_not_pollute_json_output(tmp_path: Path, capsys, monkeypatch):
    key_path = tmp_path / "peridot.key"

    # Force an isolated settings store so we can ensure it does not exist.
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(peridot, "DEFAULT_SETTINGS_STORE", settings_path)

    monkeypatch.delenv("PERIDOT_LANG", raising=False)
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")

    peridot.main(["--key", str(key_path), "init", "--force", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["settings_path"] == str(settings_path)
    assert "system language looks Spanish" not in captured.err
