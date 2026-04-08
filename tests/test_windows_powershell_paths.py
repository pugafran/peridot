import peridot


def test_windows_powershell_preset_includes_legacy_and_modern_profiles():
    preset = peridot.PRESET_LIBRARY["windows-powershell"]
    paths = set(preset["paths"])
    assert "~/Documents/PowerShell" in paths
    assert "~/Documents/WindowsPowerShell" in paths


def test_windows_catalog_group_includes_legacy_and_modern_profiles():
    groups = peridot.config_groups_for_os("windows")
    ps = next(g for g in groups if g.key == "shell-powershell")
    joined = "\n".join(ps.paths)
    assert "WindowsPowerShell" in joined
    assert "Documents/PowerShell" in joined
