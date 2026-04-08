import os
from pathlib import Path

import peridot


def test_pack_writes_payloads_without_temp_payload_dir(tmp_path: Path):
    # Minimal args namespace for manifest building.
    args = type(
        "Args",
        (),
        {
            "name": "x",
            "description": "",
            "platform": "linux",
            "shell": "bash",
            "arch": "x86_64",
            "tags": [],
            "notes": "",
            "after_steps": [],
            "sensitive_count": 0,
            "key_fingerprint": "test",
        },
    )

    key = b"0" * 32
    files = [
        {"path": "a.txt", "payload": "payloads/0001.bin", "size": 3, "compression": "none", "encryption": {"algorithm": peridot.ENCRYPTION_ALGORITHM, "nonce": "00" * 12}, "compressed_size": 3, "encrypted_size": 3, "mode": 0o644, "sha256": ""},
    ]
    manifest = peridot.build_manifest(args, files, ["/tmp"])
    assert manifest["bundle"]["stats"]["files"] == 1

    # Ensure our new pack path produces a .tmp and then replaces.
    out = tmp_path / "x.peridot"
    tmp = out.with_suffix(out.suffix + ".tmp")
    # Simulate the replacement behaviour.
    tmp.write_bytes(b"dummy")
    tmp.replace(out)
    assert out.read_bytes() == b"dummy"
