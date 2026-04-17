from pathlib import Path
import builtins
import sys

import peridot


def test_app_version_is_not_hardcoded():
    # The exact installed version varies by environment, but should not be the old hardcoded string.
    assert peridot.APP_VERSION != "0.4.4"


def test_read_pyproject_version_minimal(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "peridot-cli"
version = "1.2.3"
""".lstrip(),
        encoding="utf-8",
    )

    assert peridot.read_pyproject_version(pyproject) == "1.2.3"


def test_read_pyproject_version_poetry_fallback(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.poetry]
name = "peridot-cli"
version = "9.9.9"
""".lstrip(),
        encoding="utf-8",
    )

    assert peridot.read_pyproject_version(pyproject) == "9.9.9"


def test_read_pyproject_version_missing(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='x'\n", encoding="utf-8")
    assert peridot.read_pyproject_version(pyproject) is None


def test_read_pyproject_version_uses_tomli_fallback_when_tomllib_missing(tmp_path: Path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "peridot-cli"
version = "2.3.4"
""".lstrip(),
        encoding="utf-8",
    )

    # Simulate a runtime without stdlib tomllib (Python < 3.11), but with tomli installed.
    class FakeTomli:
        @staticmethod
        def loads(raw: str):
            # Minimal TOML parser for the test (we only need [project].version).
            assert "version" in raw
            return {"project": {"version": "2.3.4"}}

    monkeypatch.setitem(sys.modules, "tomli", FakeTomli)

    real_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert peridot.read_pyproject_version(pyproject) == "2.3.4"
