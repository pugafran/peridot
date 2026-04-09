from pathlib import Path

import peridot


def test_render_local_bundle_table_empty_does_not_crash(tmp_path, capsys):
    peridot.render_local_bundle_table(tmp_path)
    out = capsys.readouterr().out
    assert "peridot" in out.lower()  # message mentions .peridot bundles
