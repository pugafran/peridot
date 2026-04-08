![Showcase](misc/showcase.png)

# Peridot

![CI](https://github.com/pugafran/peridot/actions/workflows/ci.yml/badge.svg)

Versión actual: `0.4.1` (ver `CHANGELOG.md`).

Peridot es un CLI para crear **bundles portables de configuración** (`.peridot`) con una UX cuidada:

- `pack`: empaqueta dotfiles/carpetas de config en un bundle cifrado
- `inspect`/`manifest`: inspecciona qué hay dentro antes de aplicar
- `apply`: restaura en otra máquina (con `--dry-run` y modo transaccional)

## Quickstart (3 comandos)

```bash
peridot init
peridot pack "Mi bundle" --output mi-bundle.peridot ~/.config
peridot apply mi-bundle.peridot --dry-run
```

Notas:
- Recomendación: prueba siempre primero con `--dry-run`.
- En automatización (sin TTY), si no pasas nombre, Peridot genera uno por defecto.

## Qué es un `.peridot`

Un `.peridot` es un ZIP con:

```text
my-setup.peridot
├── manifest.json
└── payloads/
    ├── 0001-....bin
    ├── 0002-....bin
    └── ...
```

- `manifest.json` queda legible para poder revisar el contenido.
- Cada fichero se **comprime (si compensa)** y se **cifra (AES‑GCM)**.

## Instalación

### Recomendado (Windows/macOS/Linux): pipx

`pipx` instala CLIs Python en un entorno aislado y deja el comando en tu `PATH`.

1) Instala **Python 3.11+**.
2) Instala `pipx`:

- Windows (PowerShell):

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
```

Cierra y vuelve a abrir la terminal.

- macOS (Homebrew):

```bash
brew install pipx
pipx ensurepath
```

- Linux (según distro):

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

3) Instala Peridot desde PyPI:

```bash
pipx install peridot-cli
peridot --version
```

> Nota: en PyPI el paquete se llama **`peridot-cli`** ("peridot" ya está ocupado).

### macOS: Homebrew (opcional)

Si prefieres `brew`, una alternativa es instalar `pipx` con brew y seguir el método anterior.

### Desde el repo (modo dev)

```bash
./install.sh
# opcional: instala dependencias de desarrollo (pytest, etc.)
PERIDOT_INSTALL_DEV=1 ./install.sh

peridot --version
```

## Uso básico

Generar o comprobar la clave:

```bash
peridot keygen
```

Modo visual:

```bash
peridot ui
```

Benchmark de rendimiento de `pack`:

```bash
peridot bench --files 200 --size-kb 4 --levels 0,1,3 --runs 1
# guardar resultados en JSON
peridot bench --files 200 --size-kb 4 --levels 0,1,3 --runs 3 --out bench.json
```

Aplicar de forma segura:

```bash
peridot apply bundle.peridot --dry-run
peridot apply bundle.peridot
```

Por defecto, `apply` usa modo transaccional (rollback best‑effort) y verificación post‑escritura.

## Desarrollo

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

## Seguridad

- Cifrado: **AES‑GCM** por fichero.
- `apply` soporta rollback best‑effort y verificación de hash tras escribir.

## Licencia

MIT. Ver `LICENSE`.
