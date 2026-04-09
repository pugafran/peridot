from pathlib import Path
from types import SimpleNamespace

import peridot


def test_apply_does_not_write_through_existing_symlink(tmp_path: Path):
    # target/a.txt is a symlink to outside.txt. Applying a bundle that writes a.txt
    # must NOT overwrite outside.txt via symlink dereference.
    target = tmp_path / "target"
    target.mkdir()

    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE")

    (target / "a.txt").symlink_to(outside)

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
            "a.txt": {"raw": b"NEW", "mode": 0o644},
        },
        key=key,
        compression_level=0,
    )

    backup_dir = tmp_path / "backups"

    args = SimpleNamespace(
        package=bundle,
        target=target,
        backup_dir=backup_dir,
        dry_run=False,
        ignore_platform=True,
        select=[],
        yes=True,
        key=key_path,
        transactional=True,
        verify=True,
    )

    peridot.cmd_apply(args)

    # Outside file unchanged.
    assert outside.read_text() == "OUTSIDE"

    # Target path becomes a regular file with NEW.
    a_path = target / "a.txt"
    assert a_path.exists()
    assert not a_path.is_symlink()
    assert a_path.read_text() == "NEW"

    # Backup preserved the original symlink (not dereferenced).
    backup_a = backup_dir / "a.txt"
    assert backup_a.is_symlink()
    assert backup_a.resolve() == outside
