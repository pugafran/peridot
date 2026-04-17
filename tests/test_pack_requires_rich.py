from __future__ import annotations

import peridot


def test_pack_non_json_requires_rich(monkeypatch, tmp_path, capsys):
    """Non-JSON pack uses Rich progress/UI.

    When Rich is unavailable we should fail with a clear error message instead
    of crashing with a NoneType error.
    """

    monkeypatch.setattr(peridot, "RICH_AVAILABLE", False)

    src = tmp_path / "hello.txt"
    src.write_text("hi", encoding="utf-8")

    out = tmp_path / "bundle.peridot"

    try:
        peridot.main(["pack", str(src), "--output", str(out)])
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit(1)")

    captured = capsys.readouterr()
    assert "rich" in captured.err.lower()
