from pathlib import Path

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


def test_read_pyproject_version_missing(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='x'\n", encoding="utf-8")
    assert peridot.read_pyproject_version(pyproject) is None
