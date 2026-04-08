from pathlib import Path
from types import SimpleNamespace

import pytest

import peridot


def test_apply_transactional_rolls_back_on_failure(tmp_path: Path, monkeypatch):
    # Prepare target with an existing file.
    target = tmp_path / "target"
    target.mkdir()
    existing = target / "a.txt"
    existing.write_text("OLD")

    # Build a real peridot bundle with two files.
    key_path = tmp_path / "peridot.key"
    key = peridot.load_key(key_path, create=True)

    bundle = tmp_path / "bundle.peridot"
    peridot.write_bundle_from_raw(
        output=bundle,
        bundle_name="test",
        description="",
        platform="linux",
        shell="bash",
        arch="x86_64",
        tags=[],
        notes="",
        after_steps=[],
        files={
            "a.txt": {"raw": b"NEW1", "mode": 0o644},
            "b.txt": {"raw": b"NEW2", "mode": 0o644},
        },
        key=key,
        compression_level=0,
    )

    manifest = peridot.manifest_from_zip(bundle)
    b_entry = next(x for x in manifest["files"] if x["path"] == "b.txt")

    # Make decrypt_payload fail only for b.txt to simulate mid-apply error.
    real_decrypt = peridot.decrypt_payload

    def boom(encrypted: bytes, file_entry: dict, key_bytes: bytes) -> bytes:
        if file_entry.get("path") == b_entry["path"]:
            raise ValueError("invalid key")
        return real_decrypt(encrypted, file_entry, key_bytes)

    monkeypatch.setattr(peridot, "decrypt_payload", boom)

    args = SimpleNamespace(
        package=bundle,
        target=target,
        backup_dir=None,
        dry_run=False,
        ignore_platform=True,
        select=[],
        yes=True,
        key=key_path,
        transactional=True,
        verify=True,
    )

    with pytest.raises(SystemExit):
        peridot.cmd_apply(args)

    # Should have rolled back a.txt to OLD and not leave b.txt behind.
    assert existing.read_text() == "OLD"
    assert not (target / "b.txt").exists()
