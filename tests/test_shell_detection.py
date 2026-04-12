import os

import peridot


def test_detect_shell_prefers_powershell_when_psmodulepath_present(monkeypatch):
    monkeypatch.setenv("COMSPEC", "C:/Windows/System32/cmd.exe")
    monkeypatch.setenv("PSModulePath", "C:/Users/x/Documents/PowerShell/Modules")
    assert peridot.detect_shell() == "powershell"


def test_detect_shell_cmd_when_comspec_cmd(monkeypatch):
    # Simulate a Windows-like environment (no SHELL).
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("COMSPEC", "C:/Windows/System32/cmd.exe")
    assert peridot.detect_shell() == "cmd"


def test_detect_shell_cmd_when_comspec_cmd_backslashes(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    assert peridot.detect_shell() == "cmd"


def test_detect_shell_powershell_when_comspec_is_quoted_with_spaces(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    # Common on Windows when COMSPEC (or SHELL) is set to a quoted path with spaces.
    monkeypatch.setenv("COMSPEC", '"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoLogo')
    assert peridot.detect_shell() == "powershell"


def test_detect_shell_unix(monkeypatch):
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert peridot.detect_shell() == "zsh"


def test_detect_shell_unix_with_args(monkeypatch):
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("SHELL", "/bin/bash -l")
    assert peridot.detect_shell() == "bash"


def test_detect_shell_quoted_path_with_args(monkeypatch):
    monkeypatch.delenv("PSModulePath", raising=False)
    monkeypatch.setenv("SHELL", '"/usr/local/bin/fish" --login')
    assert peridot.detect_shell() == "fish"


def test_detect_shell_unknown_when_env_missing(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.delenv("COMSPEC", raising=False)
    monkeypatch.delenv("PSModulePath", raising=False)
    assert peridot.detect_shell() == "unknown"
