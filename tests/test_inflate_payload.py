import gzip

import peridot


def test_inflate_payload_none_falls_back_to_raw_when_not_gzip_or_zstd():
    raw = b"hello"
    assert peridot.inflate_payload(raw, None) == raw
    assert peridot.inflate_payload(raw, "") == raw


def test_inflate_payload_none_decompresses_when_gzipped():
    raw = b"hello"
    gz = gzip.compress(raw, compresslevel=6, mtime=0)
    assert peridot.inflate_payload(gz, None) == raw
    assert peridot.inflate_payload(gz, "") == raw


def test_inflate_payload_none_decompresses_when_zstd_and_compression_missing():
    if peridot.zstd is None:
        return
    raw = b"hello"
    zs = peridot.zstd.ZstdCompressor(level=3).compress(raw)
    assert peridot.inflate_payload(zs, None) == raw
    assert peridot.inflate_payload(zs, "") == raw


def test_inflate_payload_explicit_gzip_decompresses():
    raw = b"hello"
    gz = gzip.compress(raw, compresslevel=6, mtime=0)
    assert peridot.inflate_payload(gz, "gzip") == raw


def test_inflate_payload_explicit_zstd_missing_dependency_errors_with_install_hint(monkeypatch, capsys):
    raw = b"hello"
    monkeypatch.setattr(peridot, "zstd", None)

    try:
        peridot.inflate_payload(raw, "zstd")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("Expected SystemExit")

    captured = capsys.readouterr()
    text = (captured.err or "") + "\n" + (captured.out or "")
    assert "zstandard" in text
    assert "pip install" in text
