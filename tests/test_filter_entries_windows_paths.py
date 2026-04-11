from pathlib import Path

from peridot import FileEntry, filter_entries


def _entry(relative_path: str) -> FileEntry:
    return FileEntry(source=Path("dummy"), relative_path=relative_path, size=1, mode=0o644)


def test_filter_entries_normalizes_windows_separators() -> None:
    entries = [_entry(".ssh\\config"), _entry("notes/readme.md")]

    filtered = filter_entries(entries, excludes=[".ssh/*"])

    assert [e.relative_path for e in filtered] == ["notes/readme.md"]
