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
