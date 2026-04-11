from __future__ import annotations

import json

import peridot


def test_doctor_json_works_without_rich(monkeypatch, capsys):
    """Regression: JSON modes should work even if Rich is unavailable.

    We simulate missing Rich by flipping the runtime flag. The doctor command in
    --json mode should not attempt to render tables/panels.
    """

    monkeypatch.setattr(peridot, "RICH_AVAILABLE", False)

    peridot.main(["doctor", "--json"])

    captured = capsys.readouterr()
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert isinstance(payload, list)
    assert any(item.get("check") == "key" for item in payload)


def test_settings_json_works_without_rich(monkeypatch, capsys, tmp_path):
    """Regression: settings --json should not require Rich.

    This is useful for scripting (and for constrained envs where Rich isn't
    installed).
    """

    monkeypatch.setattr(peridot, "RICH_AVAILABLE", False)

    settings_path = tmp_path / "settings.json"
    peridot.main(["settings", "--json", "--settings-path", str(settings_path)])

    captured = capsys.readouterr()
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert payload["settings_path"].endswith("settings.json")
    assert isinstance(payload["settings"], dict)
    assert "compression_level" in payload["settings"]
    assert "jobs" in payload["settings"]
    assert "language" in payload["settings"]
