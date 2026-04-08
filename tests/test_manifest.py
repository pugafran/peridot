import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

import peridot


def make_zip(tmp_path: Path, manifest: dict) -> Path:
    p = tmp_path / "bundle.peridot"
    with ZipFile(p, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
    return p


def test_manifest_from_zip_ok(tmp_path: Path):
    p = make_zip(
        tmp_path,
        {
            "package_version": peridot.PACKAGE_VERSION,
            "bundle": {"name": "x"},
            "files": [],
        },
    )
    m = peridot.manifest_from_zip(p)
    assert m["package_version"] == peridot.PACKAGE_VERSION


def test_manifest_from_zip_missing_file(tmp_path: Path):
    with pytest.raises(SystemExit):
        peridot.manifest_from_zip(tmp_path / "nope.peridot")


def test_manifest_from_zip_missing_manifest(tmp_path: Path):
    p = tmp_path / "bundle.peridot"
    with ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(SystemExit):
        peridot.manifest_from_zip(p)
