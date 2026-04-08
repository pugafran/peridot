![Showcase](misc/showcase.png)

# Peridot

![CI](https://github.com/pugafran/peridot/actions/workflows/ci.yml/badge.svg)

Current release: `0.3.0`. See `CHANGELOG.md` for release notes.

Peridot es una herramienta de terminal para empaquetar configuraciones en bundles `.peridot`, inspeccionarlos antes de aplicar nada y restaurarlos en otra maquina con una UX visual cuidada.

La idea es simple:

- creas un bundle con tus dotfiles o carpetas de config
- el bundle lleva una ficha visible con metadata, plataforma objetivo y listado de archivos
- el contenido va comprimido y cifrado, pero el `manifest.json` queda accesible para poder revisar el paquete antes de aplicarlo
- todo ocurre en terminal; no hay dashboard web ni dependencia de frontend externo

Peridot comprime y luego cifra cada fichero. Eso reduce tamaño, pero puede hacer `pack` mas lento. Por defecto ahora usa compresion rapida (`compression_level = 1`) para priorizar velocidad. El codec principal es `zstd`; si la dependencia no esta disponible en ese Python, cae automaticamente a `gzip`. El contenedor `.peridot` exterior no recomprime payloads ya cifrados, asi que `pack` es mas rapido que antes.

## Que es un `.peridot`

Un archivo `.peridot` es un ZIP con esta estructura:

```text
my-setup.peridot
├── manifest.json
└── payloads/
    ├── 0001-....bin
    ├── 0002-....bin
    └── ...
```

`manifest.json` contiene la ficha del bundle:

- nombre y descripcion
- sistema objetivo: `macos`, `linux`, `windows` o `any`
- shell o runtime principal: `fish`, `zsh`, `bash`, `powershell`, etc.
- arquitectura objetivo
- tags
- host y usuario que generaron el bundle
- numero de archivos y peso total
- lista de archivos con `path`, `mode`, `sha256` y payload asociado

Los payloads contienen el contenido real de cada fichero, comprimido con `zstd` cuando compensa y con fallback a `gzip` si ese Python no tiene `zstandard`, y cifrado con `AES-GCM`.

## Instalacion

Recomendado (modo dev, con tests):

```bash
./install.sh
# opcional: instala dependencias de desarrollo (pytest, etc.)
PERIDOT_INSTALL_DEV=1 ./install.sh

peridot --version
```

Con `pip`:

```bash
python3 -m pip install .
```

Durante desarrollo:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Tests:

```bash
. .venv/bin/activate
pytest -q
```

Instalacion automatica del repo:

```bash
./install.sh
```

Eso crea una `.venv`, instala Peridot en modo editable y deja el comando `peridot` enlazado en `~/.local/bin/peridot`.

Si quieres incluir tambien dependencias de desarrollo (por ejemplo `pytest`):

```bash
PERIDOT_INSTALL_DEV=1 ./install.sh
```

## Flujo principal

Generar o comprobar la clave:

```bash
peridot keygen
```

Abrir el modo visual:

```bash
peridot ui
```

`peridot ui` abre un command center en terminal con:

- tabla de bundles `.peridot` detectados en el directorio actual
- catalogo clasificado de configuraciones detectables
- hub visual de acciones
- tabla de presets de dotfiles
- editor de settings persistentes
- asistente de empaquetado
- inspeccion guiada
- aplicacion guiada con `dry-run`, target y backups

Empaquetar tu setup actual:

```bash
peridot pack "MacBook Fish Setup" \
  --description "Dotfiles personales para macOS + fish" \
  --platform macos \
  --shell fish \
  --tag work \
  --tag terminal \
  --output macbook-fish.peridot \
  ~/.config/fish ~/.gitconfig ~/.zshrc
```

Si quieres priorizar velocidad:

```bash
peridot pack --compression-level 0 --jobs 8
```

Si quieres priorizar tamaño:

```bash
peridot pack --compression-level 9
```

Si quieres fijar defaults persistentes:

```bash
peridot settings
peridot settings --show
peridot settings --set compression_level=0 --set jobs=8
```

El editor `settings` muestra una barra textual del nivel de compresion y deja claro el tradeoff:

- `0` = mas rapido, bundles mas grandes
- `1-2` = rapido
- `3-6` = equilibrado
- `7-9` = mas pequeño, mas lento

`jobs` controla cuantos workers usa `pack` en paralelo. En general, subirlo ayuda cuando hay muchos archivos y CPU libre.

Peridot intenta ademas autorregular `pack` si detecta poca memoria disponible: puede arrancar con menos concurrencia, bajar trabajos en vuelo por mitades hasta `1` si hace falta, y volver a subirlos gradualmente hasta el maximo pedido cuando la memoria se recupera. Antes del empaquetado veras tambien una fase explicita de `Scanning files`, que suele ser la parte lenta antes de que aparezcan los avisos de sensibles.

Si ejecutas simplemente:

```bash
peridot pack
```

Peridot entra en modo asistido y te va preguntando:

- nombre del bundle
- descripcion
- plataforma objetivo
- shell principal
- arquitectura
- tags
- grupos clasificados de configuracion con toggles tipo checkbox
- edicion visual de rutas sugeridas con checkboxes en terminal
- rutas manuales solo como fallback
- nombre del archivo de salida

Puedes ver ese catalogo sin empezar un bundle:

```bash
peridot catalog
```

Tambien puedes arrancar desde un preset de dotfiles:

```bash
peridot pack --preset macos-fish
peridot pack --preset linux-zsh
peridot pack --preset windows-powershell
peridot pack --preset custom
```

Presets disponibles:

- `macos-fish`
- `macos-zsh`
- `linux-zsh`
- `linux-bash`
- `windows-powershell`

Inspeccionar la ficha antes de tocar nada:

```bash
peridot inspect macbook-fish.peridot --files
```

Previsualizar una aplicacion sin escribir:

```bash
peridot apply macbook-fish.peridot --dry-run
```

Aplicar el bundle con backups previos:

```bash
peridot apply macbook-fish.peridot \
  --backup-dir ~/.peridot-backups \
  --target ~
```

Comparar un bundle con tu sistema antes de aplicar:

```bash
peridot diff macbook-fish.peridot --target ~
```

Verificar integridad:

```bash
peridot verify macbook-fish.peridot
peridot verify macbook-fish.peridot --deep
```

Guardar un perfil reutilizable:

```bash
peridot profile save work-macos \
  --preset macos-fish \
  --platform macos \
  --shell fish \
  --path ~/.config/fish \
  --exclude '.ssh/*'
```

Usar un perfil:

```bash
peridot pack --profile work-macos
```

Rotar clave y migrar bundles:

```bash
peridot rekey --all-local
```

Exportar ficha CLI-friendly:

```bash
peridot share macbook-fish.peridot --format md
peridot share macbook-fish.peridot --format json
```

Fusionar y partir bundles:

```bash
peridot merge a.peridot b.peridot --output merged.peridot --name "Merged"
peridot split merged.peridot --prefix .config/fish --output fish-only.peridot --name "Fish Only"
```

Ver el manifest crudo:

```bash
peridot manifest macbook-fish.peridot
```

## Plataformas

Peridot no se limita a dotfiles Unix. Puedes generar bundles para distintos entornos:

- `macos`: `.zshrc`, `.config/fish`, `.gitconfig`, `Library/Application Support/...`
- `linux`: `.bashrc`, `.config`, `.local/share`, configuraciones de WM/terminal
- `windows`: `.gitconfig`, `.wslconfig`, `AppData/Roaming`, perfiles de PowerShell, Windows Terminal

El bundle guarda `platform.os`, `platform.shell` y `platform.arch`, y `peridot apply` comprueba compatibilidad antes de restaurar. Si quieres saltarte esa comprobacion, usa `--ignore-platform`.

## Comandos

- `peridot keygen`: crea o muestra la clave activa
- `peridot doctor`: diagnostica el entorno local
- `peridot ui`: abre el command center visual
- `peridot catalog`: enseña grupos clasificados detectables por plataforma
- `peridot pack`: crea un bundle `.peridot`
- `peridot inspect`: muestra la ficha visual del bundle
- `peridot apply`: restaura el bundle
- `peridot diff`: compara el bundle con un destino
- `peridot verify`: valida estructura e integridad
- `peridot share`: exporta una ficha en `md` o `json`
- `peridot history`: lista snapshots de un bundle
- `peridot manifest`: imprime el `manifest.json`
- `peridot rekey`: genera una nueva clave y migra paquetes existentes
- `peridot delete`: elimina paquetes `.peridot`
- `peridot profile`: guarda/lista/muestra/elimina perfiles reutilizables
- `peridot merge`: fusiona bundles
- `peridot split`: parte un bundle en otro

Tambien existen alias para la nomenclatura antigua:

- `peridot export` -> `peridot pack`
- `peridot import` -> `peridot apply`

## Filosofia del formato

Peridot intenta equilibrar tres cosas:

1. Portabilidad real. El bundle es un archivo unico, facil de subir, compartir o versionar.
2. Inspeccion previa. Puedes abrir el `manifest.json` sin descifrar el contenido.
3. Seguridad razonable. El payload va comprimido y cifrado; la clave se gestiona aparte.

Importante:

- sin la clave puedes inspeccionar el `manifest.json`, pero no leer ni aplicar los payloads cifrados
- si rotas la clave, usa `peridot rekey` para migrar los paquetes existentes a la nueva clave
- `pack` puede avisarte de rutas sensibles y aceptar exclusiones por glob

## Limitaciones actuales

- Los symlinks no se empaquetan todavia.
- No hay merge inteligente entre configuraciones; `apply` restaura ficheros completos.
- El cifrado depende de una clave local `AES-GCM`, que tienes que conservar junto al bundle si quieres moverlo a otra maquina.

## Roadmap natural

- soporte de symlinks
- perfiles declarativos por plataforma
- filtros de inclusion/exclusion por glob
- plugin system para apps concretas
- diff visual antes de sobrescribir archivos
