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


def test_pack_skipped_files_are_sorted_by_path(tmp_path: Path, capsys, monkeypatch):
    peridot.main(["init", "--force"])
    capsys.readouterr()

    ok = tmp_path / "ok.txt"
    bad_a = tmp_path / "a_nope.txt"
    bad_b = tmp_path / "b_nope.txt"
    ok.write_text("ok", encoding="utf-8")
    bad_a.write_text("a", encoding="utf-8")
    bad_b.write_text("b", encoding="utf-8")

    original = peridot.build_payload_job

    def patched_build_payload_job(source_path, relative_path, mode, payload_name, key, compression_level):
        if relative_path.endswith("a_nope.txt") or relative_path.endswith("b_nope.txt"):
            raise PermissionError("simulated permission error")
        return original(source_path, relative_path, mode, payload_name, key, compression_level)

    monkeypatch.setattr(peridot, "build_payload_job", patched_build_payload_job)

    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(peridot, "create_pack_executor", lambda requested_jobs: (ThreadPoolExecutor(max_workers=1), "threads"))

    out = tmp_path / "bundle.peridot"

    # Pass inputs in reverse order to ensure the manifest order is not just
    # reflecting CLI argument order.
    peridot.main(
        [
            "pack",
            "test",
            str(ok),
            str(bad_b),
            str(bad_a),
            "--yes",
            "--output",
            str(out),
            "--json",
            "--jobs",
            "1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"] == 2

    manifest = peridot.manifest_from_zip(out)
    skipped = manifest["bundle"].get("skipped_files")
    assert skipped
    paths = [item["path"] for item in skipped]
    assert paths == sorted(paths)
