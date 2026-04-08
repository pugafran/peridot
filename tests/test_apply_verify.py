from pathlib import Path
from types import SimpleNamespace

import pytest

import peridot


def test_apply_verify_detects_corruption_and_rolls_back(tmp_path: Path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()

    existing = target / "a.txt"
    existing.write_text("OLD")

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

    # Corrupt the write: write different bytes than requested.
    real_write_bytes = Path.write_bytes

    def corrupt_write(self: Path, data: bytes) -> int:
        if self.name == "a.txt":
            return real_write_bytes(self, b"CORRUPTED")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", corrupt_write)

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

    # Rolled back.
    assert existing.read_text() == "OLD"
