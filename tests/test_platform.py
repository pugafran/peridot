import peridot


def test_normalize_os_name_recognizes_msys_like_strings():
    assert peridot.normalize_os_name("MSYS_NT-10.0") == "windows"
    assert peridot.normalize_os_name("MINGW64_NT-10.0") == "windows"
    assert peridot.normalize_os_name("CYGWIN_NT-10.0") == "windows"
