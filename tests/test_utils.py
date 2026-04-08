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
    assert peridot.sanitize_language("es_ES.UTF-8") == "es"
    assert peridot.sanitize_language("en_US.UTF8") == "en"


def test_sanitize_language_falls_back_to_default():
    assert peridot.sanitize_language("fr") == peridot.DEFAULT_SETTINGS["language"]
    assert peridot.sanitize_language("") == peridot.DEFAULT_SETTINGS["language"]


def test_decode_aesgcm_key_bytes_accepts_unpadded_base64url():
    raw_key = bytes(range(32))
    encoded = peridot.base64.urlsafe_b64encode(raw_key).rstrip(b"=")
    assert peridot.decode_aesgcm_key_bytes(encoded) == raw_key


def test_decode_aesgcm_key_bytes_accepts_string_and_whitespace():
    raw_key = bytes(range(32))
    encoded = peridot.base64.urlsafe_b64encode(raw_key).rstrip(b"=").decode("ascii")
    encoded_wrapped = f"\n  {encoded[:10]}\n{encoded[10:]}  \n"
    assert peridot.decode_aesgcm_key_bytes(encoded_wrapped) == raw_key


def test_decode_aesgcm_key_bytes_accepts_hex():
    raw_key = bytes(range(32))
    hex_key = raw_key.hex()
    assert peridot.decode_aesgcm_key_bytes(hex_key) == raw_key
    assert peridot.decode_aesgcm_key_bytes(f"\n {hex_key[:20]}\n{hex_key[20:]} \n") == raw_key


def test_load_profiles_rejects_non_dict(tmp_path):
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text("[]\n")
    try:
        peridot.load_profiles(profile_path=profiles_path)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected SystemExit")
