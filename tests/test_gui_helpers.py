from __future__ import annotations

from pathlib import Path
from unittest import mock

import peridot_gui


def test_expand_path_expands_user_and_env(tmp_path: Path, monkeypatch):
    # env var expansion
    monkeypatch.setenv("PERIDOT_GUI_TEST", str(tmp_path))
    p = peridot_gui._expand_path("$PERIDOT_GUI_TEST")
    assert str(tmp_path) in p

    # user expansion (at least should not crash)
    p2 = peridot_gui._expand_path("~")
    assert p2


def test_compute_output_path_defaults_to_sane_dir(tmp_path: Path):
    # Force default output dir to tmp_path so the test is stable across OSes.
    with mock.patch.object(peridot_gui, "_default_output_dir", return_value=tmp_path):
        out = peridot_gui._compute_output_path(name="My Bundle", output_raw=None)
        assert Path(out).parent == tmp_path
        assert Path(out).name.endswith(".peridot")

        out2 = peridot_gui._compute_output_path(name="abc", output_raw="custom.peridot")
        # If only a filename is provided, we still place it in the default output dir.
        assert Path(out2).parent == tmp_path
        assert Path(out2).name == "custom.peridot"


def test_compute_output_path_directory_input(tmp_path: Path):
    with mock.patch.object(peridot_gui, "_default_output_dir", return_value=tmp_path):
        d = tmp_path / "outdir"
        d.mkdir()
        out = peridot_gui._compute_output_path(name="bundle", output_raw=str(d))
        assert Path(out).parent == d
        assert Path(out).name.endswith(".peridot")
