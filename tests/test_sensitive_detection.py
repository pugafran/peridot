from pathlib import Path

from peridot import FileEntry, detect_sensitive_entries


def _entry(source_name: str, relative_path: str) -> FileEntry:
    return FileEntry(source=Path(source_name), relative_path=relative_path, size=1, mode=0o644)


def test_detect_sensitive_entries_flags_common_secret_files() -> None:
    entries = [
        _entry(".env", ".env"),
        _entry(".npmrc", ".npmrc"),
        _entry("id_rsa", ".ssh/id_rsa"),
        _entry("id_ed25519", ".ssh/id_ed25519"),
        _entry("known_hosts", ".ssh/known_hosts"),
        _entry("config", ".ssh/config"),
        _entry("my_token.txt", "secrets/my_token.txt"),
        _entry("config.json", "token/config.json"),
        _entry("creds", "credentials.json"),
    ]

    sensitive = detect_sensitive_entries(entries)
    assert {e.relative_path for e in sensitive} == {e.relative_path for e in entries}


def test_detect_sensitive_entries_avoids_token_substring_false_positive() -> None:
    entries = [
        _entry("stockton.txt", "notes/stockton.txt"),
        _entry("mytoken.txt", "notes/mytoken.txt"),
        _entry("tokenize.py", "src/tokenize.py"),
    ]

    sensitive = detect_sensitive_entries(entries)
    assert sensitive == []


def test_detect_sensitive_entries_does_not_flag_generic_config_files() -> None:
    entries = [
        _entry("config", "app/config"),
        _entry("config", "config"),
        _entry("config.yaml", "config.yaml"),
    ]

    sensitive = detect_sensitive_entries(entries)
    assert sensitive == []
