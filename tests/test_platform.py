import peridot


def test_normalize_os_name_recognizes_msys_like_strings():
    assert peridot.normalize_os_name("MSYS_NT-10.0") == "windows"
    assert peridot.normalize_os_name("MINGW64_NT-10.0") == "windows"
    assert peridot.normalize_os_name("CYGWIN_NT-10.0") == "windows"


def test_normalize_os_name_recognizes_linux_variants():
    assert peridot.normalize_os_name("linux2") == "linux"
    assert peridot.normalize_os_name("Linux-gnu") == "linux"
