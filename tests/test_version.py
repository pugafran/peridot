import peridot


def test_app_version_is_not_hardcoded():
    # The exact installed version varies by environment, but should not be the old hardcoded string.
    assert peridot.APP_VERSION != "0.4.4"
