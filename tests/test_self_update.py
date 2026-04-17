import types

import peridot


def test_parse_simple_version():
    assert peridot.parse_simple_version("0.4.5") == (0, 4, 5)
    assert peridot.parse_simple_version("v0.4.5") == (0, 4, 5)
    assert peridot.parse_simple_version("1.2.3rc1") == (1, 2, 3)
    assert peridot.parse_simple_version("nope") is None


def test_should_check_for_updates_respects_interval(monkeypatch):
    settings = {
        "update_check_enabled": True,
        "update_check_last_ts": 100,
        "update_check_interval_hours": 24,
    }

    monkeypatch.delenv("PERIDOT_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("PERIDOT_UPDATE_CHECK_INTERVAL_HOURS", raising=False)

    assert peridot.should_check_for_updates(settings, now_ts=100) is False
    assert peridot.should_check_for_updates(settings, now_ts=100 + 24 * 3600) is True


def test_should_check_for_updates_env_interval_override(monkeypatch):
    settings = {
        "update_check_enabled": True,
        "update_check_last_ts": 100,
        "update_check_interval_hours": 24,
    }

    monkeypatch.delenv("PERIDOT_UPDATE_CHECK", raising=False)
    monkeypatch.setenv("PERIDOT_UPDATE_CHECK_INTERVAL_HOURS", "1")

    assert peridot.should_check_for_updates(settings, now_ts=100) is False
    assert peridot.should_check_for_updates(settings, now_ts=100 + 3600) is True


def test_should_check_for_updates_env_can_disable(monkeypatch):
    settings = {
        "update_check_enabled": True,
        "update_check_last_ts": 0,
        "update_check_interval_hours": 0,
    }

    monkeypatch.setenv("PERIDOT_UPDATE_CHECK", "0")
    assert peridot.should_check_for_updates(settings, now_ts=10) is False


def test_should_check_for_updates_env_can_force(monkeypatch):
    settings = {
        "update_check_enabled": False,
        "update_check_last_ts": 999999,
        "update_check_interval_hours": 999999,
    }

    monkeypatch.setenv("PERIDOT_UPDATE_CHECK", "1")
    assert peridot.should_check_for_updates(settings, now_ts=100) is True


def test_maybe_suggest_self_update_emits_message_when_newer(monkeypatch, capsys):
    # Avoid env/CI interference.
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PERIDOT_UPDATE_CHECK", raising=False)

    settings = {
        "update_check_enabled": True,
        "update_check_last_ts": 0,
        "update_check_interval_hours": 24,
        "language": "en",
        "compression_level": 3,
        "jobs": 2,
    }

    monkeypatch.setattr(peridot, "load_settings", lambda *a, **k: dict(settings))
    monkeypatch.setattr(peridot, "save_settings", lambda *a, **k: None)
    monkeypatch.setattr(peridot, "fetch_latest_pypi_version", lambda *a, **k: "999.0.0")

    args = types.SimpleNamespace(json=False)
    peridot.maybe_suggest_self_update(args)

    captured = capsys.readouterr()
    assert "Update available" in (captured.err + captured.out)


def test_maybe_suggest_self_update_can_be_disabled_by_flag(monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PERIDOT_UPDATE_CHECK", raising=False)

    settings = {
        "update_check_enabled": True,
        "update_check_last_ts": 0,
        "update_check_interval_hours": 0,
        "language": "en",
        "compression_level": 3,
        "jobs": 2,
    }

    monkeypatch.setattr(peridot, "load_settings", lambda *a, **k: dict(settings))
    monkeypatch.setattr(peridot, "save_settings", lambda *a, **k: None)
    monkeypatch.setattr(peridot, "fetch_latest_pypi_version", lambda *a, **k: "999.0.0")

    args = types.SimpleNamespace(json=False, no_update_check=True)
    peridot.maybe_suggest_self_update(args)

    captured = capsys.readouterr()
    assert (captured.err + captured.out).strip() == ""
