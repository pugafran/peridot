import json
from pathlib import Path

import peridot


def test_pack_skips_unreadable_file_instead_of_crashing(tmp_path: Path, capsys, monkeypatch):
    peridot.main(["init", "--force"])
    capsys.readouterr()  # clear init output

    readable = tmp_path / "ok.txt"
    bad = tmp_path / "nope.txt"
    readable.write_text("ok", encoding="utf-8")
    bad.write_text("secret", encoding="utf-8")

    original = peridot.build_payload_job

    def patched_build_payload_job(source_path, relative_path, mode, payload_name, key, compression_level):
        if relative_path.endswith("nope.txt"):
            raise PermissionError("simulated permission error")
        return original(source_path, relative_path, mode, payload_name, key, compression_level)

    monkeypatch.setattr(peridot, "build_payload_job", patched_build_payload_job)

    # Ensure this test runs in-process (threads), so monkeypatches apply.
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(peridot, "create_pack_executor", lambda requested_jobs: (ThreadPoolExecutor(max_workers=1), "threads"))

    out = tmp_path / "bundle.peridot"
    peridot.main(
        [
            "pack",
            "test",
            str(readable),
            str(bad),
            "--yes",
            "--output",
            str(out),
            "--json",
            "--jobs",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"] == 1

    manifest = peridot.manifest_from_zip(out)
    skipped = manifest["bundle"].get("skipped_files")
    assert skipped and skipped[0]["path"].endswith("nope.txt")
