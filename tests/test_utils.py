import peridot


def test_slugify_basic():
    assert peridot.slugify("Hola Mundo") == "hola-mundo"


def test_slugify_empty_or_none():
    assert peridot.slugify("") == "bundle"
    assert peridot.slugify(None) == "bundle"


def test_slugify_strips_weird_chars():
    assert peridot.slugify("  Foo / Bar!!! ") == "foo-bar"


def test_slugify_normalizes_accents():
    assert peridot.slugify("Canción") == "cancion"


def test_slugify_treats_common_symbols_as_separators():
    assert peridot.slugify("foo+bar") == "foo-bar"
    assert peridot.slugify("foo@bar") == "foo-bar"
    assert peridot.slugify("foo.bar") == "foo-bar"


def test_slugify_truncates_long_inputs_safely():
    raw = "a" * 200
    assert peridot.slugify(raw) == ("a" * 64)

    # Truncation should not leave trailing separators.
    raw = ("ab-" * 100)  # produces a long slug with dashes
    assert not peridot.slugify(raw).endswith("-")


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


def test_decode_aesgcm_key_bytes_accepts_standard_base64():
    # Standard base64 can contain '+' and '/' (vs base64url '-','_').
    raw_key = bytes([255, 254, 253, 252] + list(range(28)))
    encoded = peridot.base64.b64encode(raw_key).rstrip(b"=")
    assert b"+" in encoded or b"/" in encoded
    assert peridot.decode_aesgcm_key_bytes(encoded) == raw_key


def test_decode_aesgcm_key_bytes_accepts_string_and_whitespace():
    raw_key = bytes(range(32))
    encoded = peridot.base64.urlsafe_b64encode(raw_key).rstrip(b"=").decode("ascii")
    encoded_wrapped = f"\n  {encoded[:10]}\n{encoded[10:]}  \n"
    assert peridot.decode_aesgcm_key_bytes(encoded_wrapped) == raw_key


def test_decode_aesgcm_key_bytes_accepts_raw_bytes_with_trailing_newline():
    raw_key = bytes(range(32))
    assert peridot.decode_aesgcm_key_bytes(raw_key + b"\n") == raw_key
    assert peridot.decode_aesgcm_key_bytes(raw_key + b"\r") == raw_key
    assert peridot.decode_aesgcm_key_bytes(raw_key + b"\r\n") == raw_key


def test_decode_aesgcm_key_bytes_accepts_hex():
    raw_key = bytes(range(32))
    hex_key = raw_key.hex()
    assert peridot.decode_aesgcm_key_bytes(hex_key) == raw_key
    assert peridot.decode_aesgcm_key_bytes(f"\n {hex_key[:20]}\n{hex_key[20:]} \n") == raw_key


def test_decode_aesgcm_key_bytes_accepts_hex_with_0x_prefix():
    raw_key = bytes(range(32))
    hex_key = raw_key.hex()
    assert peridot.decode_aesgcm_key_bytes(f"0x{hex_key}") == raw_key
    assert peridot.decode_aesgcm_key_bytes(f"\n 0x{hex_key[:30]}\n{hex_key[30:]} \n") == raw_key


def test_should_exclude_entry_filters_common_basenames_outside_home(tmp_path):
    assert peridot.should_exclude_entry(tmp_path / ".DS_Store") is True
    assert peridot.should_exclude_entry(tmp_path / ".cache" / "foo.txt") is True
    assert peridot.should_exclude_entry(tmp_path / "regular" / "file.txt") is False


def test_collect_files_prunes_excluded_directories(monkeypatch, tmp_path):
    # Arrange a small tree where a directory should be excluded by basename.
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "secret.txt").write_text("nope")
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "ok.txt").write_text("ok")

    # Spy os.walk to ensure "dirs" is mutated in-place to drop excluded dirs.
    def fake_walk(start):
        assert peridot.Path(start) == tmp_path
        dirs = [".cache", "keep"]
        yield (str(tmp_path), dirs, [])

        # After the first yield, collect_files may have pruned dirs.
        if ".cache" in dirs:
            yield (str(tmp_path / ".cache"), [], ["secret.txt"])
        if "keep" in dirs:
            yield (str(tmp_path / "keep"), [], ["ok.txt"])

    monkeypatch.setattr(peridot.os, "walk", fake_walk)

    # Act
    entries = peridot.collect_files([tmp_path])

    # Assert: only the non-excluded file is collected.
    rels = {entry.relative_path.replace('\\', '/') for entry in entries}
    assert any(p.endswith("/keep/ok.txt") for p in rels)
    assert not any(p.endswith("/.cache/secret.txt") for p in rels)

def test_load_profiles_rejects_non_dict(tmp_path):
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text("[]\n")
    try:
        peridot.load_profiles(profile_path=profiles_path)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected SystemExit")


def test_detect_sensitive_entries_flags_common_dotfiles(tmp_path):
    entries = [
        peridot.FileEntry(source=tmp_path / ".netrc", relative_path=".netrc", size=1, mode=0o600),
        peridot.FileEntry(source=tmp_path / ".pypirc", relative_path=".pypirc", size=1, mode=0o600),
        peridot.FileEntry(source=tmp_path / "notes.txt", relative_path="notes.txt", size=1, mode=0o644),
    ]

    sensitive = peridot.detect_sensitive_entries(entries)
    sensitive_paths = {entry.relative_path for entry in sensitive}
    assert ".netrc" in sensitive_paths
    assert ".pypirc" in sensitive_paths
    assert "notes.txt" not in sensitive_paths


def test_filter_sensitive_entries_excludes_by_default_without_tty(tmp_path):
    entries = [
        peridot.FileEntry(source=tmp_path / ".netrc", relative_path=".netrc", size=1, mode=0o600),
        peridot.FileEntry(source=tmp_path / "notes.txt", relative_path="notes.txt", size=1, mode=0o644),
    ]
    sensitive = [entries[0]]
    args = peridot.SimpleNamespace(yes=False)

    filtered = peridot.filter_sensitive_entries(entries, sensitive, args, is_tty=False)
    filtered_paths = {entry.relative_path for entry in filtered}
    assert ".netrc" not in filtered_paths
    assert "notes.txt" in filtered_paths


def test_filter_sensitive_entries_keeps_when_yes_even_without_tty(tmp_path):
    entries = [
        peridot.FileEntry(source=tmp_path / ".netrc", relative_path=".netrc", size=1, mode=0o600),
        peridot.FileEntry(source=tmp_path / "notes.txt", relative_path="notes.txt", size=1, mode=0o644),
    ]
    sensitive = [entries[0]]
    args = peridot.SimpleNamespace(yes=True)

    filtered = peridot.filter_sensitive_entries(entries, sensitive, args, is_tty=False)
    filtered_paths = {entry.relative_path for entry in filtered}
    assert filtered_paths == {".netrc", "notes.txt"}
