import os

import peridot


def test_entropy_low_for_repeated_data():
    sample = b"a" * 4096
    assert peridot.shannon_entropy(sample) < 1.0


def test_entropy_high_for_random_data():
    sample = os.urandom(4096)
    assert peridot.shannon_entropy(sample) > 7.0


def test_likely_incompressible_skips_compression_for_random():
    raw = os.urandom(64 * 1024)
    compression, payload = peridot.choose_compression(raw, "file.bin", compression_level=3)
    assert compression == "none"
    assert payload == raw
