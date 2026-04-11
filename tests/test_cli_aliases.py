import peridot


def test_export_alias_supports_json_flag():
    parser = peridot.build_parser()
    args = parser.parse_args(["export", "mybundle", "--json", "--output", "out.peridot"])

    assert args.command == "export"
    assert args.json is True


def test_import_alias_matches_apply_safety_flags():
    parser = peridot.build_parser()
    args = parser.parse_args(
        [
            "import",
            "bundle.peridot",
            "--dry-run",
            "--json",
            "--apply-token",
            "tok",
            "--no-verify",
            "--no-transactional",
        ]
    )

    assert args.command == "import"
    assert args.dry_run is True
    assert args.json is True
    assert args.apply_token == "tok"
    assert args.verify is False
    assert args.transactional is False
