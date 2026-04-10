import peridot


def test_pack_error_messages_are_translated_to_english() -> None:
    peridot.set_current_language("en")

    assert (
        peridot.tr("No hay rutas para empaquetar. Pasa rutas explicitas o prepara tu HOME.")
        == "No paths to pack. Pass explicit paths or prepare your HOME."
    )
    assert (
        peridot.tr("No se encontro ningun archivo exportable.")
        == "No exportable files were found."
    )
    assert (
        peridot.tr("No quedan archivos tras aplicar exclusiones y filtros de seguridad.")
        == "No files remain after applying excludes and security filters."
    )
