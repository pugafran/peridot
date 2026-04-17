import sys
import types

import peridot


def test_parse_simple_version():
    assert peridot.parse_simple_version("0.4.5") == (0, 4, 5)
    assert peridot.parse_simple_version("v0.4.5") == (0, 4, 5)
    assert peridot.parse_simple_version("1.2.3rc1") == (1, 2, 3)
    assert peridot.parse_simple_version("1.2") == (1, 2, 0)
    assert peridot.parse_simple_version("v1.2") == (1, 2, 0)
    assert peridot.parse_simple_version("7") == (7, 0, 0)
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

    # The update suggestion is only shown on interactive stderr.
    monkeypatch.setattr(peridot.sys.stderr, "isatty", lambda: True)

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

    # Force interactive stderr so we know the silence comes from the flag.
    monkeypatch.setattr(peridot.sys.stderr, "isatty", lambda: True)

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


def test_maybe_suggest_self_update_is_silent_when_stderr_not_tty(monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PERIDOT_UPDATE_CHECK", raising=False)

    # Non-interactive stderr should suppress the update hint.
    monkeypatch.setattr(peridot.sys.stderr, "isatty", lambda: False)

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

    def _fetch(*a, **k):
        raise AssertionError("fetch_latest_pypi_version should not be called when stderr is not a TTY")

    monkeypatch.setattr(peridot, "fetch_latest_pypi_version", _fetch)

    args = types.SimpleNamespace(json=False)
    peridot.maybe_suggest_self_update(args)

    captured = capsys.readouterr()
    assert (captured.err + captured.out).strip() == ""


def test_cmd_self_update_requires_yes_in_noninteractive(monkeypatch):
    # If stdin is not a TTY, self-update should not run unless -y/--yes is set.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    called = {"n": 0}

    def _check_call(cmd):
        called["n"] += 1
        raise AssertionError("subprocess.check_call should not be invoked")

    monkeypatch.setattr(peridot.subprocess, "check_call", _check_call)

    args = types.SimpleNamespace(yes=False)
    try:
        peridot.cmd_self_update(args)
        raise AssertionError("expected SystemExit")
    except SystemExit:
        pass

    assert called["n"] == 0


def test_cmd_self_update_runs_with_yes_in_noninteractive(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    captured = {"cmd": None}

    def _check_call(cmd):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(peridot.subprocess, "check_call", _check_call)

    args = types.SimpleNamespace(yes=True)
    peridot.cmd_self_update(args)

    assert captured["cmd"] is not None
    assert captured["cmd"][0] == peridot.sys.executable
