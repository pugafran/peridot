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
    assert (
        peridot.tr(
            "Tip: tu idioma del sistema parece espanol. Puedes cambiar la UI/CLI de Peridot con PERIDOT_LANG=es o desde la UI de Settings."
        )
        == "Tip: your system language looks Spanish. You can switch Peridot UI/CLI with PERIDOT_LANG=es or via the Settings UI."
    )
    assert peridot.tr("Llavero") == "Keyring"
    assert peridot.tr("Clave disponible en") == "Key available at"
