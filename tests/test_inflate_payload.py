import gzip

import peridot


def test_inflate_payload_none_falls_back_to_raw_when_not_gzip():
    raw = b"hello"
    assert peridot.inflate_payload(raw, None) == raw
    assert peridot.inflate_payload(raw, "") == raw


def test_inflate_payload_none_decompresses_when_gzipped():
    raw = b"hello"
    gz = gzip.compress(raw, compresslevel=6, mtime=0)
    assert peridot.inflate_payload(gz, None) == raw
    assert peridot.inflate_payload(gz, "") == raw


def test_inflate_payload_explicit_gzip_decompresses():
    raw = b"hello"
    gz = gzip.compress(raw, compresslevel=6, mtime=0)
    assert peridot.inflate_payload(gz, "gzip") == raw
