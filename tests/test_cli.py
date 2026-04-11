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


def test_doctor_json_includes_zstd_check(capsys):
    parser = peridot.build_parser()
    args = parser.parse_args(["doctor", "--json"])

    args.func(args)

    raw = capsys.readouterr().out
    payload = peridot.json.loads(raw)

    checks = {row["check"]: row for row in payload}
    assert "zstd" in checks
    assert checks["zstd"]["status"] in {"ok", "warn"}
    assert isinstance(checks["zstd"]["detail"], str)
    assert checks["zstd"]["detail"]
