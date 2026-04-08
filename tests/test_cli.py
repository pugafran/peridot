import pytest

import peridot


def test_version_flag_prints_and_exits(capsys):
    parser = peridot.build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])

    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("peridot ")
    assert peridot.APP_VERSION in out
