from pathlib import Path

import peridot


def test_bench_smoke(tmp_path: Path, capsys):
    key_path = tmp_path / "peridot.key"
    # Run a tiny bench to ensure it doesn't crash.
    out_json = tmp_path / "bench.json"
    peridot.main(
        [
            "--key",
            str(key_path),
            "bench",
            "--files",
            "2",
            "--size-kb",
            "1",
            "--runs",
            "1",
            "--levels",
            "0",
            "--jobs",
            "1",
            "--out",
            str(out_json),
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert "Bench results" in out
    assert "MB/s" in out
    assert out_json.exists()
