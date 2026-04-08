from pathlib import Path
from types import SimpleNamespace

import peridot


def test_prepare_pack_inputs_noninteractive_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(peridot.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(peridot.platform, "node", lambda: "host")

    args = SimpleNamespace(
        name=None,
        description="",
        output=None,
        paths=[str(tmp_path)],
        tags=[],
        preset="",
        profile="",
        exclude=[],
        platform="linux",
        shell="bash",
        arch="x86_64",
    )

    paths, output = peridot.prepare_pack_inputs(args)
    assert args.name.startswith("host-linux-bundle")
    assert output.name.endswith(".peridot")
    assert paths
