import peridot


def test_checkbox_unavailable_reason_when_stdout_not_tty(monkeypatch):
    monkeypatch.setattr(peridot, "QUESTIONARY_AVAILABLE", True)
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(peridot.sys.stdout, "isatty", lambda: False)
    assert peridot.checkbox_unavailable_reason() == "no_tty"


def test_interactive_select_config_groups_does_not_try_questionary_when_stdout_not_tty(monkeypatch):
    # Regression guard: interactive_select_config_groups should not even attempt to
    # build / run a Questionary checkbox UI if stdout isn't an interactive TTY.
    # In those scenarios checkbox_prompt() returns None and we should fall back to
    # defaults without calling questionary at all.
    from pathlib import Path

    monkeypatch.setattr(peridot, "QUESTIONARY_AVAILABLE", True)
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(peridot.sys.stdout, "isatty", lambda: False)

    called = {"checkbox": 0}

    class _FakeQuestionary:
        def checkbox(self, *args, **kwargs):
            called["checkbox"] += 1
            raise AssertionError("questionary.checkbox should not be called when stdout is not a TTY")

    monkeypatch.setattr(peridot, "questionary", _FakeQuestionary())

    group = peridot.ConfigGroup(
        key="core",
        category="Core",
        label="Core",
        description="Core group",
        paths=("/tmp/does-not-matter",),
        default=True,
    )
    monkeypatch.setattr(peridot, "config_groups_for_os", lambda os_name: [group])
    monkeypatch.setattr(peridot, "existing_paths", lambda paths: [])

    selected = peridot.interactive_select_config_groups(os_name="linux", shell_name="bash")
    assert isinstance(selected, list)
    assert called["checkbox"] == 0


def test_checkbox_unavailable_reason_when_questionary_missing(monkeypatch):
    monkeypatch.setattr(peridot, "QUESTIONARY_AVAILABLE", False)
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(peridot.sys.stdout, "isatty", lambda: True)
    assert peridot.checkbox_unavailable_reason() == "missing_questionary"


def test_checkbox_unavailable_reason_available(monkeypatch):
    monkeypatch.setattr(peridot, "QUESTIONARY_AVAILABLE", True)
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(peridot.sys.stdout, "isatty", lambda: True)
    assert peridot.checkbox_unavailable_reason() is None
