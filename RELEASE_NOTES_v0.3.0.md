# Peridot v0.3.0

Peridot pasa de script experimental a herramienta CLI publicable para empaquetar, inspeccionar y restaurar configuraciones en bundles `.peridot`.

## Highlights

- CLI rehecha con flujos para `pack`, `inspect`, `apply`, `diff`, `verify`, `doctor`, `history`, `merge`, `split`, `profile`, `settings`, `rekey` y `delete`.
- UI visual en terminal con command center, presets y catalogo clasificado de configuraciones detectables.
- `settings` persistentes para compresion, workers e idioma, con cambio de idioma aplicado en caliente.
- Internacionalizacion base `es/en` para la ayuda principal y los flujos interactivos visibles.
- Cifrado unificado en `AES-GCM` por fichero.
- Compresion mejorada con `zstd` como codec preferido y `gzip` como fallback automatico si `zstandard` no esta disponible.
- Mejoras de rendimiento en `pack`: fase visible de `Scanning files`, compresion adaptativa por fichero, control adaptativo de concurrencia y contenedor exterior que no recomprime payloads cifrados.
- Formato publicable con `pyproject.toml`, `install.sh`, `LICENSE`, `.gitignore` y `CHANGELOG.md`.

## Release metadata

- Tag: `v0.3.0`
- Commit: `8368394`
- Branch: `main`
- Remote: `origin`

## Recommended install

```bash
python3 -m pip install .
```

For local development:

```bash
./install.sh
```
