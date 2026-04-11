import peridot


def test_checkbox_unavailable_reason_when_stdout_not_tty(monkeypatch):
    monkeypatch.setattr(peridot, "QUESTIONARY_AVAILABLE", True)
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(peridot.sys.stdout, "isatty", lambda: False)
    assert peridot.checkbox_unavailable_reason() == "no_tty"


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
