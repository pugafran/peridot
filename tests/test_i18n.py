import peridot


def test_tr_spanish_passthrough():
    peridot.set_current_language("es")
    assert peridot.tr("Bench results") == "Bench results"  # Spanish mode returns input unchanged


def test_tr_english_translation_known_keys():
    peridot.set_current_language("en")
    assert peridot.tr("Bench results") == "Bench results"
    assert peridot.tr("Next steps") == "Next steps"
    assert peridot.tr("Peridot initialized") == "Peridot initialized"
    assert peridot.tr("Error: falta la dependencia 'cryptography'.") == "Error: missing 'cryptography' dependency."
    assert peridot.tr("Instalala con 'python3 -m pip install .'.") == "Install it with 'python3 -m pip install .'."
