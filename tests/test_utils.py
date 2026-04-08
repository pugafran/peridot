import peridot


def test_slugify_basic():
    assert peridot.slugify("Hola Mundo") == "hola-mundo"


def test_slugify_strips_weird_chars():
    assert peridot.slugify("  Foo / Bar!!! ") == "foo-bar"


def test_format_bytes():
    assert peridot.format_bytes(0) == "0 B"
    assert peridot.format_bytes(1024) == "1.0 KB"


def test_sanitize_compression_level():
    assert peridot.sanitize_compression_level(0) == 0
    assert peridot.sanitize_compression_level(9) == 9


def test_sanitize_jobs(monkeypatch):
    monkeypatch.setattr(peridot.os, "cpu_count", lambda: 4)

    assert peridot.sanitize_jobs(1) == 1
    assert peridot.sanitize_jobs(999) == 8  # 2 * cpu_count


def test_sanitize_language_accepts_locales():
    assert peridot.sanitize_language("es") == "es"
    assert peridot.sanitize_language("en") == "en"
    assert peridot.sanitize_language("es-ES") == "es"
    assert peridot.sanitize_language("en_US") == "en"
    assert peridot.sanitize_language("EN-us") == "en"


def test_sanitize_language_falls_back_to_default():
    assert peridot.sanitize_language("fr") == peridot.DEFAULT_SETTINGS["language"]
    assert peridot.sanitize_language("") == peridot.DEFAULT_SETTINGS["language"]
