import peridot


def test_load_settings_invalid_json_is_translated_when_language_en(tmp_path, capsys, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not-json}\n", encoding="utf-8")

    # Force a stable, plain stderr error message (no Rich markup).
    monkeypatch.setattr(peridot, "RICH_AVAILABLE", False)
    peridot.set_current_language("en")

    try:
        peridot.load_settings(settings_path)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    err = capsys.readouterr().err
    assert "Error:" in err
    assert "Settings store is invalid" in err


def test_load_settings_non_object_json_is_translated_when_language_en(tmp_path, capsys, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(peridot, "RICH_AVAILABLE", False)
    peridot.set_current_language("en")

    try:
        peridot.load_settings(settings_path)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    err = capsys.readouterr().err
    assert "Settings store must be a JSON object" in err
