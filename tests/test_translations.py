import peridot


def test_install_hint_translation_is_dynamic():
    previous = peridot.CURRENT_LANGUAGE
    try:
        peridot.set_current_language("en")
        rendered = peridot.trf(
            "Usa el binario instalado con './install.sh' o ejecuta '{cmd}'.",
            cmd="python -m pip install -r requirements.txt",
        )
        assert rendered == (
            "Use the binary installed with './install.sh' or run 'python -m pip install -r requirements.txt'."
        )
    finally:
        peridot.set_current_language(previous)


def test_exported_label_is_localized():
    previous = peridot.CURRENT_LANGUAGE
    try:
        peridot.set_current_language("en")
        assert peridot.tr("Exportado") == "Exported"

        peridot.set_current_language("es")
        assert peridot.tr("Exportado") == "Exportado"
    finally:
        peridot.set_current_language(previous)
