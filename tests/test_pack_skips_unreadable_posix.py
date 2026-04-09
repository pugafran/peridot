import os
import stat
from pathlib import Path

import pytest

import peridot


@pytest.mark.skipif(os.name == "nt", reason="Windows chmod semantics differ; skip this POSIX-only test")
def test_pack_skips_unreadable_file_instead_of_crashing(tmp_path: Path, capsys):
    peridot.main(["init", "--force"])
    capsys.readouterr()  # clear init output

    readable = tmp_path / "ok.txt"
    unreadable = tmp_path / "nope.txt"
    readable.write_text("ok", encoding="utf-8")
    unreadable.write_text("secret", encoding="utf-8")

    # Remove read permissions.
    unreadable.chmod(0)
    try:
        unreadable.read_bytes()
        pytest.skip("Could not make file unreadable on this filesystem/user; skipping")
    except PermissionError:
        pass

    out = tmp_path / "bundle.peridot"
    peridot.main([
        "pack",
        "test",
        str(readable),
        str(unreadable),
        "--yes",
        "--output",
        str(out),
        "--json",
    ])

    captured = capsys.readouterr().out
    import json
    payload = json.loads(captured)
    assert payload["skipped"] == 1

    manifest = peridot.manifest_from_zip(out)
    skipped = manifest["bundle"].get("skipped_files")
    assert skipped and skipped[0]["path"].endswith("nope.txt")

    # Cleanup permissions for tmpdir removal.
    unreadable.chmod(stat.S_IRUSR | stat.S_IWUSR)
