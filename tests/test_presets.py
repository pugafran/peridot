import peridot


def test_linux_fish_preset_exists():
    assert "linux-fish" in peridot.PRESET_LIBRARY
    p = peridot.PRESET_LIBRARY["linux-fish"]
    assert p["platform"] == "linux"
    assert p["shell"] == "fish"


def test_recommended_preset_linux_fish(monkeypatch):
    monkeypatch.setattr(peridot, "normalize_os_name", lambda *a, **k: "linux")
    monkeypatch.setattr(peridot, "detect_shell", lambda: "fish")
    assert peridot.get_recommended_preset() == "linux-fish"
