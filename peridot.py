#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
import difflib
import fnmatch
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Callable, Iterable
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ModuleNotFoundError:
    InvalidTag = None  # type: ignore[assignment]
    AESGCM = None  # type: ignore[assignment]


def require_cryptography():
    """Fail fast when cryptography-backed features are used.

    We intentionally avoid aborting at import time so lightweight operations
    such as --version/--help can still work in constrained environments.
    """

    if AESGCM is None:
        hint = venv_activation_hint()
        runtime = python_runtime_hint()
        pip_hint = install_hint(".")

        extra_lines: list[str] = []
        if runtime:
            extra_lines.append(runtime)
        if hint:
            extra_lines.append(hint)

        print(
            tr("Error: falta la dependencia 'cryptography'.")
            + " "
            + trf("Instalala con '{cmd}'.", cmd=pip_hint)
            + (("\n" + "\n".join(extra_lines)) if extra_lines else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)
    return AESGCM, InvalidTag

try:
    import zstandard as zstd
except ModuleNotFoundError:
    zstd = None

RICH_AVAILABLE = True

try:
    from rich.align import Align
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.prompt import Confirm
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
except ModuleNotFoundError:
    # Keep import-time lightweight so `peridot --help/--version` can run even in
    # constrained environments. Commands that require Rich will error later.
    RICH_AVAILABLE = False

    class Console:  # type: ignore[override]
        def print(self, *args, **kwargs):  # noqa: ANN002, ANN003
            print(*args)

    Align = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Progress = None  # type: ignore[assignment]
    SpinnerColumn = None  # type: ignore[assignment]
    TextColumn = None  # type: ignore[assignment]
    TimeElapsedColumn = None  # type: ignore[assignment]
    TimeRemainingColumn = None  # type: ignore[assignment]
    BarColumn = None  # type: ignore[assignment]
    Confirm = None  # type: ignore[assignment]
    Prompt = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]

try:
    import questionary
    from questionary import Choice
except ModuleNotFoundError:
    questionary = None
    Choice = None


QUESTIONARY_AVAILABLE = questionary is not None and Choice is not None


def read_pyproject_version(pyproject_path: Path) -> str | None:
    """Read the PEP 621 project.version from pyproject.toml.

    This is a lightweight fallback for source checkouts where the package isn't
    installed (so importlib.metadata can't resolve the distribution).
    """

    try:
        import tomllib  # py3.11+
    except Exception:
        return None

    try:
        raw = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        data = tomllib.loads(raw)
    except Exception:
        return None

    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()

    # Optional fallback: Poetry-style metadata used by some repos.
    # This keeps --version useful even when PEP 621 [project] is not present.
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            version = poetry.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()

    return None


try:
    APP_VERSION = metadata.version("peridot-cli")
except Exception:
    # Fallback for source checkouts / non-installed runs.
    APP_VERSION = read_pyproject_version(Path(__file__).with_name("pyproject.toml")) or "0.0.0"

PACKAGE_VERSION = 1
DEFAULT_COMPRESSION_LEVEL = 1
DEFAULT_JOBS = max(2, min(8, os.cpu_count() or 2))
DEFAULT_KEY = Path.home() / ".config" / "peridot" / "peridot.key"
DEFAULT_PROFILE_STORE = Path.home() / ".config" / "peridot" / "profiles.json"
DEFAULT_HISTORY_DIR = Path.home() / ".config" / "peridot" / "history"
DEFAULT_SETTINGS_STORE = Path.home() / ".config" / "peridot" / "settings.json"


def default_key_path() -> Path:
    """Return the effective key path.

    Priority:
    1) PERIDOT_KEY_PATH environment variable
    2) DEFAULT_KEY constant

    Mirrors PERIDOT_SETTINGS_PATH / PERIDOT_PROFILES_PATH so CI/tests/power users
    can redirect the key location without needing per-command flags.
    """

    raw = (os.environ.get("PERIDOT_KEY_PATH") or "").strip()
    if raw:
        try:
            expanded = os.path.expandvars(raw)
            return Path(expanded).expanduser()
        except Exception:
            return DEFAULT_KEY
    return DEFAULT_KEY


def default_history_dir() -> Path:
    """Return the effective history root directory.

    Priority:
    1) PERIDOT_HISTORY_DIR environment variable
    2) DEFAULT_HISTORY_DIR constant

    Mirrors PERIDOT_SETTINGS_PATH / PERIDOT_PROFILES_PATH so CI/tests/power users
    can redirect history snapshots without changing code.
    """

    raw = (os.environ.get("PERIDOT_HISTORY_DIR") or "").strip()
    if raw:
        try:
            expanded = os.path.expandvars(raw)
            return Path(expanded).expanduser()
        except Exception:
            return DEFAULT_HISTORY_DIR
    return DEFAULT_HISTORY_DIR


def default_settings_store() -> Path:
    """Return the effective settings store path.

    Priority:
    1) PERIDOT_SETTINGS_PATH environment variable
    2) DEFAULT_SETTINGS_STORE constant

    This keeps the default stable, while allowing test suites and power users
    to redirect the settings store without needing per-command flags.
    """

    raw = (os.environ.get("PERIDOT_SETTINGS_PATH") or "").strip()
    if raw:
        try:
            # Allow $VARS / %VARS% in addition to ~ expansion.
            expanded = os.path.expandvars(raw)
            return Path(expanded).expanduser()
        except Exception:
            # Fall back to the default if the env var is malformed.
            return DEFAULT_SETTINGS_STORE
    return DEFAULT_SETTINGS_STORE


def default_profile_store() -> Path:
    """Return the effective profiles store path.

    Priority:
    1) PERIDOT_PROFILES_PATH environment variable
    2) DEFAULT_PROFILE_STORE constant

    Matches the behavior of PERIDOT_SETTINGS_PATH for settings.
    """

    raw = (os.environ.get("PERIDOT_PROFILES_PATH") or "").strip()
    if raw:
        try:
            expanded = os.path.expandvars(raw)
            return Path(expanded).expanduser()
        except Exception:
            return DEFAULT_PROFILE_STORE
    return DEFAULT_PROFILE_STORE

DEFAULT_EXCLUDES = {
    ".DS_Store",
    ".Trash",
    ".cache",
    ".git",
    ".hg",
    ".svn",
    ".npm",
    ".pnpm-store",
    ".yarn",
    ".local/share/Trash",
    ".config/peridot",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # Common Python tooling output
    ".tox",
    ".nox",
    ".hypothesis",
    ".coverage",
    "coverage.xml",
    "htmlcov",
    "node_modules",
    ".idea",
}
SENSITIVE_PATTERNS = (
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "known_hosts",
    "credentials",
    "token",
    ".env",
    ".npmrc",
    ".netrc",
    ".pypirc",
    ".gnupg",
)

DEFAULT_SETTINGS = {
    "compression_level": DEFAULT_COMPRESSION_LEVEL,
    "jobs": DEFAULT_JOBS,
    "language": "en",
    # Update checks
    "update_check_enabled": True,
    "update_check_last_ts": 0,
    "update_check_interval_hours": 24,
}
ENCRYPTION_ALGORITHM = "aes-gcm"
INCOMPRESSIBLE_SUFFIXES = {
    ".7z",
    ".avi",
    ".bz2",
    ".class",
    ".dmg",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".otf",
    ".pdf",
    ".png",
    ".rar",
    ".tar",
    ".tgz",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xz",
    ".zip",
}

PRIMARY_COMPRESSION = "zstd"
FALLBACK_COMPRESSION = "gzip"
CURRENT_LANGUAGE = "en"

TRANSLATIONS = {
    "en": {
        "Peridot initialized": "Peridot initialized",
        "Next steps": "Next steps",
        "Bench results": "Bench results",
        "Verificacion fallida": "Verification failed",
        "Verificacion OK": "Verification OK",
        "Inspeccionar": "Inspect",
        "Mostrar lista de ficheros?": "Show file list?",
        "Mostrar manifest JSON?": "Show manifest JSON?",
        "Aplicar": "Apply",
        "Hacer dry-run primero?": "Dry run first?",
        "Directorio destino": "Target directory",
        "Guardar backups antes de sobrescribir?": "Save backups before overwrite?",
        "Directorio de backups": "Backup directory",
        "Ignorar mismatch de plataforma?": "Ignore platform mismatch?",
        "Verificar": "Verify",
        "Verificacion profunda (descifrar)?": "Deep verify with decryption?",
        "Compartir": "Share",
        "Formato": "Format",
        "Fichero de salida (vacio = imprimir)": "Output file (leave empty to print)",
        "Nombre del bundle": "Bundle name",
        "Accion de perfil": "Profile action",
        "Nombre del perfil": "Profile name",
        "Rekey todos los bundles locales?": "Rekey all local bundles?",
        "Borrar todos los bundles locales?": "Delete all local bundles?",
        "Borrar": "Delete",
        "Portable config bundles for humans": "Portable config bundles for humans",
        "Bundles portables de configuracion para humanos": "Portable config bundles for humans",
        "Error": "Error",
        "El store de settings es invalido ({path}): {exc}": "Settings store is invalid ({path}): {exc}",
        "El store de settings debe ser un objeto JSON.": "Settings store must be a JSON object.",
        "Compression": "Compression",
        "Level": "Level",
        "Codec": "Codec",
        "Mode": "Mode",
        "Tradeoff": "Tradeoff",
        "Rule": "Rule",
        "menos compresion, mas velocidad": "less compression, more speed",
        "equilibrado entre tamano y velocidad": "balanced between size and speed",
        "mas compresion, mas lentitud": "more compression, slower speed",
        "0 = mas rapido y mas grande | 9 = mas lento y mas pequeno": "0 = faster and bigger | 9 = slower and smaller",
        "Dot Presets": "Dot Presets",
        "Preset desconocido: {preset}. Disponibles: {available}": "Unknown preset: {preset}. Available: {available}",
        "Quizás quisiste decir: {suggestions}": "Did you mean: {suggestions}",
        "Config Catalog": "Config Catalog",
        "Checkbox UI no disponible:": "Checkbox UI unavailable:",
        "esta sesion no tiene un TTY interactivo real.": "this session does not have a real interactive TTY.",
        "Ejecuta Peridot directamente en una terminal interactiva.": "Run Peridot directly in an interactive terminal.",
        "No hay un TTY interactivo; se excluyen rutas sensibles por defecto. Usa --yes para incluirlas.": "No interactive TTY detected; excluding sensitive paths by default. Use --yes to include them.",
        "No hay rutas para empaquetar. Pasa rutas explicitas o prepara tu HOME.": "No paths to pack. Pass explicit paths or prepare your HOME.",
        "No se encontro ningun archivo exportable.": "No exportable files were found.",
        "No quedan archivos tras aplicar exclusiones y filtros de seguridad.": "No files remain after applying excludes and security filters.",
        "falta la dependencia 'questionary' en este Python.": "the 'questionary' dependency is missing in this Python.",
        "Usa el binario instalado con './install.sh' o ejecuta '{cmd}'.": "Use the binary installed with './install.sh' or run '{cmd}'.", 
        "Selecciona grupos": "Select groups",
        "Selecciona rutas": "Select paths",
        "Selecciona rutas para este bundle": "Select paths for this bundle",
        "Selecciona grupos de configuracion": "Select config groups",
        "Espacio para marcar, Enter para confirmar": "Space to toggle, Enter to confirm",
        "Como quieres construir este bundle?": "How do you want to build this bundle?",
        "Bundle source: preset, catalog or empty": "Bundle source: preset, catalog or empty",
        "Base selection": "Base selection",
        "Preset": "Preset",
        "Bundle name": "Bundle name",
        "Description": "Description",
        "Target OS": "Target OS",
        "Primary shell/runtime": "Primary shell/runtime",
        "Target architecture": "Target architecture",
        "Tags (comma separated)": "Tags (comma separated)",
        "Selected paths": "Selected paths",
        "Edit this selection?": "Edit this selection?",
        "Add extra paths manually?": "Add extra paths manually?",
        "Extra paths (comma separated)": "Extra paths (comma separated)",
        "Usando entrada manual.": "Falling back to manual input.",
        "Paths to include (comma separated)": "Paths to include (comma separated)",
        "No has seleccionado ninguna ruta, se usara la seleccion sugerida.": "No path was selected; the suggested selection will be used.",
        "Output package": "Output package",
        "Pack Preview": "Pack Preview",
        "Files": "Files",
        "Bundle": "Bundle",
        "Package": "Package",
        "Target": "Target",
        "Payload": "Payload",
        "Tags": "Tags",
        "Created": "Created",
        "From": "From",
        "Notes": "Notes",
        "Sensitive": "Sensitive",
        "Bundle Card": "Bundle Card",
        "Bundles locales": "Local Bundles",
        "No hay bundles .peridot en este directorio": "No .peridot bundles in this directory",
        "Elegir accion": "Choose action",
        "Centro de acciones": "Action Hub",
        "Atajos: 1=pack 2=catalog 3=presets 4=inspect 5=apply 6=diff 7=verify 8=doctor 9=share 10=manifest 11=history 12=profile 13=settings 14=keygen 15=rekey 16=delete 17=quit": "Quick keys: 1=pack 2=catalog 3=presets 4=inspect 5=apply 6=diff 7=verify 8=doctor 9=share 10=manifest 11=history 12=profile 13=settings 14=keygen 15=rekey 16=delete 17=quit",
        "Compatible con esta maquina": "Compatible with this machine",
        "Compatibility": "Compatibility",
        "Scanning files": "Scanning files",
        "Scanning files done": "Scanning files done",
        # Canonical (es) keys
        "Rutas sensibles detectadas": "Sensitive paths detected",
        "Incluir estas rutas sensibles?": "Include these sensitive paths?",
        # Backwards-compat (old en keys)
        "Sensitive paths detected": "Sensitive paths detected",
        "Include these sensitive paths?": "Include these sensitive paths?",
        "Adaptive pack:": "Adaptive pack:",
        "reduciendo ventana inicial de {requested} a {initial} ({reason}). Puede volver a subir si la memoria acompana.": "reducing initial active window from {requested} to {initial} ({reason}). It can grow again if memory allows it.",
        "Process pool no disponible en este sistema; usando threads.": "Process pool is not available on this system; using threads.",
        "subiendo ventana activa {previous} -> {current} ({label}).": "raising active window {previous} -> {current} ({label}).",
        "bajando ventana activa {previous} -> {current} ({label}).": "lowering active window {previous} -> {current} ({label}).",
        "Created {output}": "Created {output}",
        "Previous snapshot saved to {path}": "Previous snapshot saved to {path}",
        "Show file list?": "Show file list?",
        "Show manifest JSON?": "Show manifest JSON?",
        "Dry run first?": "Dry run first?",
        "Target directory": "Target directory",
        "Save backups before overwrite?": "Save backups before overwrite?",
        "Backup directory": "Backup directory",
        "Ignore platform mismatch?": "Ignore platform mismatch?",
        "Dry run: no se ha escrito nada.": "Dry run: nothing was written.",
        "Apply this bundle?": "Apply this bundle?",
        "Operacion cancelada.": "Operation cancelled.",
        "La clave no coincide con el paquete.": "The key does not match the package.",
        "Apply Summary": "Apply Summary",
        "Restored": "Restored",
        "Backups": "Backups",
        "Backup dir": "Backup dir",
        "Post apply": "Post apply",
        "Post-apply checklist": "Post-apply checklist",
        "Verify failed": "Verify failed",
        "Verify ok": "Verify ok",
        "Settings": "Settings",
        "workers para pack; mas puede ir mas rapido si hay CPU libre": "workers for pack; more can go faster if CPU is available",
        "cifrado fijo: rapido, moderno y estandar": "fixed encryption: fast, modern and standard",
        "preparado para internacionalizacion CLI": "ready for CLI internationalization",
        "Compression: 0 = mas rapido y mas grande, 9 = mas lento y mas pequeno.": "Compression: 0 = faster and bigger, 9 = slower and smaller.",
        "Compression level": "Compression level",
        "Pack workers": "Pack workers",
        "CPU detectada: {cpu} | workers activos: {jobs}": "Detected CPU: {cpu} | active workers: {jobs}",
        "Language": "Language",
        "Save settings?": "Save settings?",
        "Settings saved {path}": "Settings saved {path}",
        "Settings updated {path}": "Settings updated {path}",
        "Doctor": "Doctor",
        "Check": "Check",
        "Status": "Status",
        "Detail": "Detail",
        "History": "History",
        "Profiles": "Profiles",
        "Profile saved {name}": "Profile saved {name}",
        "Profile deleted {name}": "Profile deleted {name}",
        "Deleted {count} package(s)": "Deleted {count} package(s)",
        "Rekey Summary": "Rekey Summary",
        "Packages": "Packages",
        "New key": "New key",
        "Backup key": "Backup key",
        "'x' marca los grupos recomendados por defecto para esta plataforma/shell. No significa que ya vayan dentro de ningun bundle.": "'x' marks the default recommended groups for this platform/shell. It does not mean they are already in any bundle.",
        "Leaving Peridot UI.": "Leaving Peridot UI.",
        "Press enter to return to the command center": "Press enter to return to the command center",
        "Empaqueta, inspecciona y aplica bundles de configuracion .peridot": "Pack, inspect and apply .peridot configuration bundles",
        "Crea un paquete .peridot": "Create a .peridot package",
        "Muestra la ficha de un paquete": "Show a package card",
        "Aplica un paquete .peridot": "Apply a .peridot package",
        "Compara un bundle con un directorio destino": "Compare a bundle with a target directory",
        "Verifica integridad del bundle": "Verify bundle integrity",
        "Diagnostico del entorno local": "Run local environment diagnostics",
        "Exporta una ficha CLI-friendly del bundle": "Export a CLI-friendly bundle card",
        "Fusiona varios bundles en uno": "Merge several bundles into one",
        "Extrae un subset de un bundle en otro bundle": "Extract a subset of a bundle into another bundle",
        "Lista snapshots historicos de un bundle": "List historical snapshots for a bundle",
        "Imprime el manifest de un paquete": "Print a package manifest",
        "Elimina paquetes .peridot": "Delete .peridot packages",
        "Genera una nueva clave y migra paquetes existentes": "Generate a new key and migrate existing packages",
        "Lista grupos clasificados de configuracion detectables": "List detectable categorized configuration groups",
        "Gestiona perfiles reutilizables": "Manage reusable profiles",
        "Gestiona defaults persistentes de Peridot": "Manage persistent Peridot defaults",
        "Genera o muestra la clave activa": "Generate or show the active key",
        "Lanza el command center visual": "Launch the visual command center",
        "Alias de pack": "Alias for pack",
        "Alias de apply": "Alias for apply",
        "Muestra la version y sale": "Show the version and exit",
        "Ruta de la clave AES-GCM (por defecto: {path})": "AES-GCM key path (default: {path})",
        "Error: falta la dependencia 'cryptography'.": "Error: missing 'cryptography' dependency.",
        "Error: falta la dependencia 'rich'.": "Error: missing 'rich' dependency.",
        "Instalala con 'python3 -m pip install .'.": "Install it with 'python3 -m pip install .'.",
        "Instalala con '{cmd}'.": "Install it with '{cmd}'.",
        "Tip: activa el entorno virtual con '{cmd}'.": "Tip: activate the virtualenv with '{cmd}'.",
        "Tip: activa el entorno virtual con '. .venv/bin/activate'.": "Tip: activate the virtualenv with '. .venv/bin/activate'.",
        "Tip: para automatizar (MCP), ejecuta 'apply --dry-run --json' para obtener un apply_token.": "Tip: for automation (MCP), run 'apply --dry-run --json' to obtain an apply_token.",
        "Python actual: {exe} (v{ver}).": "Current Python: {exe} (v{ver}).",
        "Tip: tu idioma del sistema parece espanol. Puedes cambiar la UI/CLI de Peridot con PERIDOT_LANG=es o desde la UI de Settings.": "Tip: your system language looks Spanish. You can switch Peridot UI/CLI with PERIDOT_LANG=es or via the Settings UI.",
        "Actualizacion disponible: {latest} (instalada: {current}). Ejecuta: {cmd}": "Update available: {latest} (installed: {current}). Run: {cmd}",
        "Actualiza peridot-cli usando pip": "Update peridot-cli using pip",
        "Actualizar peridot-cli a la ultima version? [y/N] ": "Update peridot-cli to the latest version? [y/N] ",
        "No se encontro pip en este Python. Instala pip o usa tu gestor de paquetes.": "pip was not found for this Python. Install pip or use your package manager.",
        "Fallo al actualizar peridot-cli (exit={code}).": "peridot-cli update failed (exit={code}).",
        "Llavero": "Keyring",
        "Clave disponible en": "Key available at",
    }
}

console = Console()
PRESET_LIBRARY = {
    "macos-fish": {
        "description": "macOS + fish dotfiles",
        "platform": "macos",
        "shell": "fish",
        "tags": ["dotfiles", "fish", "macos"],
        "paths": [
            "~/.config/fish",
            "~/.gitconfig",
            "~/.ssh",
            "~/.tool-versions",
        ],
    },
    "macos-zsh": {
        "description": "macOS + zsh dotfiles",
        "platform": "macos",
        "shell": "zsh",
        "tags": ["dotfiles", "zsh", "macos"],
        "paths": [
            "~/.zshrc",
            "~/.zprofile",
            "~/.gitconfig",
            "~/.ssh",
        ],
    },
    "linux-zsh": {
        "description": "Linux + zsh dotfiles",
        "platform": "linux",
        "shell": "zsh",
        "tags": ["dotfiles", "zsh", "linux"],
        "paths": [
            "~/.zshrc",
            "~/.zprofile",
            "~/.config",
            "~/.gitconfig",
        ],
    },
    "linux-fish": {
        "description": "Linux + fish dotfiles",
        "platform": "linux",
        "shell": "fish",
        "tags": ["dotfiles", "fish", "linux"],
        "paths": [
            "~/.config/fish",
            "~/.local/share/fish",
            "~/.config",
            "~/.gitconfig",
        ],
    },
    "linux-bash": {
        "description": "Linux + bash dotfiles",
        "platform": "linux",
        "shell": "bash",
        "tags": ["dotfiles", "bash", "linux"],
        "paths": [
            "~/.bashrc",
            "~/.bash_profile",
            "~/.config",
            "~/.gitconfig",
        ],
    },
    "windows-powershell": {
        "description": "Windows + PowerShell dotfiles",
        "platform": "windows",
        "shell": "powershell",
        "tags": ["dotfiles", "powershell", "windows"],
        "paths": [
            "~/.gitconfig",
            "~/.wslconfig",
            # PowerShell 7+ / Windows Terminal
            "~/Documents/PowerShell",
            # Windows PowerShell (legacy)
            "~/Documents/WindowsPowerShell",
            "~/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState",
        ],
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_current_language(language: str) -> None:
    global CURRENT_LANGUAGE
    CURRENT_LANGUAGE = sanitize_language(language)


def detect_runtime_language() -> str:
    # Backwards-compatible env override.
    #
    # PERIDOT_LANG is the documented knob, but PERIDOT_LANGUAGE is a common
    # expectation (used by other tools), so we accept it as an alias.
    env_language = os.environ.get("PERIDOT_LANG") or os.environ.get("PERIDOT_LANGUAGE")
    if env_language:
        normalized = env_language.strip().lower()
        if normalized in {"auto", "system"}:
            return detect_system_language_hint() or DEFAULT_SETTINGS["language"]
        return sanitize_language(env_language)
    try:
        settings_path = default_settings_store()
        if settings_path.exists():
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                language = raw.get("language")
                normalized = str(language or "").strip().lower()
                if normalized in {"auto", "system"}:
                    return detect_system_language_hint() or DEFAULT_SETTINGS["language"]
                return sanitize_language(language)
    except Exception:
        pass
    return DEFAULT_SETTINGS["language"]


def detect_system_language_hint() -> str | None:
    """Best-effort guess for the OS/UI language.

    Used only to *suggest* switching language; it should never override user
    settings.
    """

    candidates = [
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
        os.environ.get("LANGUAGE"),
    ]
    for raw in candidates:
        if not raw:
            continue
        base = sanitize_language(raw)
        if base:
            return base
    try:
        import locale

        # locale.getdefaultlocale() is deprecated (Py 3.11+) and can emit
        # DeprecationWarning in modern runtimes. locale.getlocale() is the
        # supported alternative.
        loc, _enc = locale.getlocale()
        if loc:
            return sanitize_language(loc)
    except Exception:
        pass
    return None


def tr(text: str) -> str:
    if CURRENT_LANGUAGE == "en":
        return TRANSLATIONS["en"].get(text, text)
    return text


def trf(text: str, **kwargs) -> str:
    return tr(text).format(**kwargs)


def is_probably_venv_dir(path: Path) -> bool:
    """Heuristic check: does *path* look like a Python virtualenv directory?"""

    try:
        if not path.exists() or not path.is_dir():
            return False

        # pyvenv.cfg is the most reliable marker.
        if (path / "pyvenv.cfg").exists():
            return True

        # Fallback: common interpreter locations.
        if (path / "bin" / "python").exists() or (path / "bin" / "python3").exists():
            return True
        if (path / "Scripts" / "python.exe").exists() or (path / "Scripts" / "python").exists():
            return True

        # Last resort: activation scripts (some tests/fake venvs only provide these).
        if (path / "bin" / "activate").exists() or (path / "Scripts" / "activate").exists():
            return True

        return False
    except Exception:
        return False


def detect_repo_venv_dir() -> Path | None:
    """Return the most likely virtualenv directory for hint generation.

    Peridot is often run from a source checkout, but not necessarily with the
    repo root as the current working directory (e.g. invoked via an absolute
    path). In that case, looking only at Path('.venv') would miss the repo
    virtualenv.

    We check (in order):
    - ./.venv relative to the current working directory (recommended)
    - ./venv relative to the current working directory (common alternative)
    - .venv next to this file (repo checkout)

    Notes:
        We only return directories that look like virtualenvs to avoid
        misleading hints when a project has a file named ".venv"/"venv".
    """

    try:
        for candidate in (Path(".venv"), Path("venv")):
            # If the CWD contains a .venv/venv entry, treat it as authoritative:
            # - when it looks like a venv, use it
            # - when it doesn't, do NOT fall back to the peridot.py-adjacent .venv
            #   (we might be running from a different repo and shouldn't emit
            #   misleading activation hints).
            if candidate.exists():
                return candidate if is_probably_venv_dir(candidate) else None

        file_venv = Path(__file__).resolve().parent / ".venv"
        if is_probably_venv_dir(file_venv):
            return file_venv
    except Exception:
        return None

    return None


def install_hint(target: str) -> str:
    """Return a copy/paste-friendly pip install command.

    We prefer the repo virtualenv (./.venv) when present.

    On Windows, virtualenvs use .venv/Scripts/python(.exe).

    Notes:
        sys.executable can contain spaces (e.g. "Program Files"). When we
        fall back to it, we quote it to make the command copy/paste-friendly.

        The install *target* can also contain spaces (e.g. a local path).
        Quote it so the suggested command remains copy/paste-friendly.

        If *target* starts with a dash, we treat it as a pip option string
        (e.g. "-U peridot-cli" or "-r requirements.txt") and **must not**
        quote it as a single argument.
    """

    raw_target = str(target)

    if raw_target.lstrip().startswith("-"):
        target_str = raw_target.strip()
    else:
        target_str = raw_target
        if any(ch.isspace() for ch in target_str):
            if normalize_os_name() == "windows":
                target_str = f'"{target_str}"'
            else:
                target_str = shlex.quote(target_str)

    venv_dir = detect_repo_venv_dir()
    if venv_dir is not None:
        candidates = [
            venv_dir / "bin" / "python",
            venv_dir / "bin" / "python3",
            venv_dir / "Scripts" / "python.exe",
            venv_dir / "Scripts" / "python",
        ]
        for venv_python in candidates:
            if venv_python.exists():
                python_str = str(venv_python)
                if any(ch.isspace() for ch in python_str):
                    if normalize_os_name() == "windows":
                        python_str = f'"{python_str}"'
                    else:
                        python_str = shlex.quote(python_str)
                return f"{python_str} -m pip install {target_str}"

    # Fall back to the current interpreter so the suggestion matches the
    # environment Peridot is running in.
    python = getattr(sys, "executable", None) or "python"
    python_str = str(python)

    if any(ch.isspace() for ch in python_str):
        if normalize_os_name() == "windows":
            python_str = f'"{python_str}"'
        else:
            python_str = shlex.quote(python_str)

    return f"{python_str} -m pip install {target_str}"


def venv_activation_hint() -> str | None:
    """Suggest activating the repo virtualenv when it exists but isn't active.

    We only emit a hint when an activation script is actually present.
    """

    try:
        venv_dir = detect_repo_venv_dir()
        is_venv_active = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        if venv_dir is None or is_venv_active:
            return None

        win_activate = venv_dir / "Scripts" / "activate"
        posix_activate = venv_dir / "bin" / "activate"

        if not win_activate.exists() and not posix_activate.exists():
            return None

        # Prefer a hint that matches the virtualenv layout for the platform.
        # Keep relative, familiar commands when the venv is in the CWD.
        if win_activate.exists():
            if venv_dir == Path(".venv"):
                cmd = ".venv\\Scripts\\activate"
            elif venv_dir == Path("venv"):
                cmd = "venv\\Scripts\\activate"
            else:
                cmd = str(win_activate)
        else:
            if venv_dir == Path(".venv"):
                cmd = ". .venv/bin/activate"
            elif venv_dir == Path("venv"):
                cmd = ". venv/bin/activate"
            else:
                cmd = f". {shlex.quote(str(posix_activate))}"

        return trf("Tip: activa el entorno virtual con '{cmd}'.", cmd=cmd)
    except Exception:
        return None


def python_runtime_hint() -> str | None:
    """Return a short, copy/paste-friendly hint about the current Python runtime."""

    try:
        exe = str(getattr(sys, "executable", "") or "").strip()
        ver_info = getattr(sys, "version_info", None)
        ver = "?"
        if ver_info is not None:
            ver = f"{ver_info.major}.{ver_info.minor}.{ver_info.micro}"
        if not exe:
            return None
        return trf("Python actual: {exe} (v{ver}).", exe=exe, ver=ver)
    except Exception:
        return None


def parse_simple_version(value: str) -> tuple[int, int, int] | None:
    """Parse a simple semantic-ish version string.

    Accepts:
      - X.Y.Z (optionally prefixed with "v")
      - X.Y (interpreted as X.Y.0)
      - X (interpreted as X.0.0)

    Ignores any suffix after the numeric prefix (e.g. "1.2.3rc1").

    We intentionally avoid external deps (packaging). If parsing fails, return None.
    """

    s = (value or "").strip()
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", s)
    if not m:
        return None

    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return (major, minor, patch)


def fetch_latest_pypi_version(package: str = "peridot-cli") -> str | None:
    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"peridot/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        version = str(payload.get("info", {}).get("version") or "").strip()
        return version or None
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def should_check_for_updates(settings: dict, *, now_ts: int | None = None) -> bool:
    env_value = os.environ.get("PERIDOT_UPDATE_CHECK", "").strip().lower()
    if env_value in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    if env_value in {"1", "true", "yes", "on", "force"}:
        return True

    if not bool(settings.get("update_check_enabled", True)):
        return False

    now = int(now_ts if now_ts is not None else time.time())
    last = int(settings.get("update_check_last_ts") or 0)

    # Power-user / CI override: allow tuning the interval without touching the
    # persisted settings store.
    env_interval = (os.environ.get("PERIDOT_UPDATE_CHECK_INTERVAL_HOURS") or "").strip()
    if env_interval:
        interval_h = sanitize_update_check_interval_hours(env_interval)
    else:
        interval_h = sanitize_update_check_interval_hours(settings.get("update_check_interval_hours"))

    return (now - last) >= (interval_h * 3600)


def maybe_suggest_self_update(args: argparse.Namespace) -> None:
    # Allow explicit opt-out for scripts.
    if bool(getattr(args, "no_update_check", False)):
        return

    # Avoid noise in machine-readable outputs / non-interactive contexts.
    if bool(getattr(args, "json", False)):
        return
    if os.environ.get("CI"):
        return

    try:
        settings = load_settings()
    except SystemExit:
        return

    if not should_check_for_updates(settings):
        return

    latest = fetch_latest_pypi_version("peridot-cli")
    if not latest:
        return

    current = str(APP_VERSION)
    parsed_latest = parse_simple_version(latest)
    parsed_current = parse_simple_version(current)
    if not parsed_latest or not parsed_current:
        return

    # Record the check time best-effort (don't fail the command).
    try:
        settings["update_check_last_ts"] = int(time.time())
        save_settings(settings)
    except Exception:
        pass

    if parsed_latest <= parsed_current:
        return

    cmd = install_hint("-U peridot-cli")
    sys.stderr.write(
        trf(
            "Actualizacion disponible: {latest} (instalada: {current}). Ejecuta: {cmd}",
            latest=latest,
            current=current,
            cmd=cmd,
        )
        + "\n"
    )


def localize_parser(parser: argparse.ArgumentParser) -> None:
    parser.description = tr(parser.description) if parser.description else parser.description
    for action in parser._actions:
        if getattr(action, "help", None):
            action.help = tr(action.help)
        if getattr(action, "description", None):
            action.description = tr(action.description)
        for pseudo_action in getattr(action, "_choices_actions", []):
            if getattr(pseudo_action, "help", None):
                pseudo_action.help = tr(pseudo_action.help)
        subparser_map = getattr(action, "choices", None)
        if isinstance(subparser_map, dict):
            for subparser in subparser_map.values():
                localize_parser(subparser)


def die(message: str) -> None:
    """Print an error message and exit.

    When Rich is available we use markup/styling. Otherwise, fall back to a
    plain stderr message so the output is still readable (instead of showing
    raw "[bold red]" tags).
    """

    if not RICH_AVAILABLE:
        print(f"{tr('Error')}: {message}", file=sys.stderr)
        raise SystemExit(1)

    # Use soft_wrap so long tokens (like file paths) aren't hard-wrapped mid-string.
    # This keeps error messages copy/paste-friendly and avoids brittle tests.
    console.print(
        f"[bold red]{tr('Error')}:[/bold red] {message}",
        style="red",
        soft_wrap=True,
    )
    raise SystemExit(1)


def normalize_os_name(value: str | None = None) -> str:
    raw = (value or platform.system()).strip().lower()

    # Some environments embed extra info in platform.system(), for example:
    # - "MSYS_NT-10.0"
    # - "MINGW64_NT-10.0"
    # Treat these as Windows so preset/config selection remains stable.
    if raw.startswith(("msys", "mingw", "cygwin")):
        return "windows"

    # Older Python versions / downstream builds may return variants like
    # "linux2" or "linux-gnu".
    if raw.startswith("linux"):
        return "linux"

    mapping = {
        "darwin": "macos",
        "mac": "macos",
        "macos": "macos",
        "linux": "linux",
        "windows": "windows",
        "win32": "windows",
        "msys": "windows",
        "cygwin": "windows",
    }
    return mapping.get(raw, raw or "unknown")


def sanitize_compression_level(value: object) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = DEFAULT_COMPRESSION_LEVEL
    return max(0, min(9, level))


def max_reasonable_jobs(cpu_count: int | None = None) -> int:
    """Return a safe upper bound for parallel jobs.

    We keep it tied to available CPU to avoid spawning an excessive amount of
    processes/threads on small machines, while still allowing high-core hosts
    to take advantage of their capacity.
    """

    cpu = cpu_count if cpu_count is not None else (os.cpu_count() or 2)
    try:
        cpu_int = int(cpu)
    except (TypeError, ValueError):
        cpu_int = 2
    cpu_int = max(1, cpu_int)
    return max(1, min(64, cpu_int * 2))


def sanitize_jobs(value: object) -> int:
    """Normalize the jobs/concurrency setting.

    Accepts integers; non-integers fall back to DEFAULT_JOBS.

    Special case: values <= 0 mean "auto" (use DEFAULT_JOBS). This makes it
    easy to disable an explicit override in config files while still keeping a
    valid, safe concurrency.
    """

    try:
        jobs = int(value)
    except (TypeError, ValueError):
        jobs = DEFAULT_JOBS

    if jobs <= 0:
        jobs = DEFAULT_JOBS

    return max(1, min(max_reasonable_jobs(), jobs))


def sanitize_language(value: object) -> str:
    """Normalize *effective* language values.

    Returns a concrete language code ("es" or "en").

    Accepts exact codes ("es", "en") and common locale variants such as
    "es-ES", "en_US" or "EN-us" by reducing them to the base language.

    Also accepts some common OS locale *names* (especially on Windows), such as
    "Spanish_Spain" / "English_United States".

    Note:
        This function intentionally does NOT return "auto"/"system". Those are
        settings-layer values that must be resolved to a concrete language
        before being used for rendering.
    """

    raw = str(value or DEFAULT_SETTINGS["language"]).strip().lower()
    # Strip common locale suffixes such as ".UTF-8" or "@euro".
    raw = raw.split(".", 1)[0].split("@", 1)[0].replace("_", "-")

    # Some platforms return language names (e.g. "Spanish-Spain"). Normalize
    # accents so "Español" can be matched as "espanol".
    raw_ascii = unicodedata.normalize("NFKD", raw)
    raw_ascii = "".join(ch for ch in raw_ascii if not unicodedata.combining(ch))

    if raw_ascii in {"es", "en"}:
        return raw_ascii

    base = raw_ascii.split("-", 1)[0] if raw_ascii else ""
    if base in {"es", "en"}:
        return base

    # Accept common language names.
    if base in {"spanish", "espanol", "castellano"}:
        return "es"
    if base == "english":
        return "en"

    return DEFAULT_SETTINGS["language"]


def sanitize_language_setting(value: object) -> str:
    """Normalize the persisted language setting.

    Accepts:
      - "es" / "en" (and locale variants) -> "es"/"en"
      - "auto" or "system" -> "auto" (stored sentinel)

    This keeps the intent (automatic language selection) when saving/loading
    settings, while callers can resolve it via detect_runtime_language() or
    detect_system_language_hint().
    """

    raw = str(value or "").strip().lower()
    if raw in {"auto", "system"}:
        return "auto"
    return sanitize_language(value)


def effective_language_from_setting(value: object) -> str:
    """Resolve a language setting to a concrete language code ("es"/"en")."""

    raw = str(value or "").strip().lower()
    if raw in {"auto", "system"}:
        return detect_system_language_hint() or DEFAULT_SETTINGS["language"]
    return sanitize_language(value)


def sanitize_update_check_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(DEFAULT_SETTINGS["update_check_enabled"])


def sanitize_update_check_interval_hours(value: object) -> int:
    try:
        # Accept both integer and float-ish values (e.g. "24.0") coming from
        # JSON or env-driven overrides.
        if isinstance(value, float):
            hours = int(value)
        else:
            raw = str(value).strip()
            hours = int(float(raw)) if (raw and any(ch in raw for ch in ".eE")) else int(raw)
    except (TypeError, ValueError):
        hours = int(DEFAULT_SETTINGS["update_check_interval_hours"])
    return max(1, min(24 * 30, hours))


def slugify(value: str | None, max_length: int = 64) -> str:
    """Turn an arbitrary string into a filesystem-friendly slug.

    Args:
        value: Source string.
        max_length: Best-effort cap for the slug length. This helps keep
            default output filenames reasonably short across platforms.
    """

    # Be defensive: callers sometimes pass None/empty values when deriving a
    # default output name.
    value = value or ""

    # Normalize unicode (e.g. "Canción" -> "Cancion") to avoid generating
    # slugs with accented characters that may be awkward in filenames/URLs.
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))

    # Treat any non-alphanumeric character as a separator. This makes common
    # inputs like "foo+bar" or "foo@bar" produce a readable slug instead of
    # silently dropping the separator.
    cleaned: list[str] = []
    last_was_sep = True
    for char in normalized.lower():
        if char.isalnum():
            cleaned.append(char)
            last_was_sep = False
            continue
        if not last_was_sep:
            cleaned.append("-")
            last_was_sep = True

    slug = "".join(cleaned).strip("-")

    if max_length and len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")

    return slug or "bundle"


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            # Avoid noisy trailing decimals for exact unit boundaries.
            rounded = round(value)
            if abs(value - rounded) < 1e-9:
                return f"{int(rounded)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def active_compression_codec() -> str:
    return PRIMARY_COMPRESSION if zstd is not None else FALLBACK_COMPRESSION


def compression_profile_name(level: int) -> str:
    if level <= 2:
        return "fast"
    if level <= 6:
        return "balanced"
    return "small"


def compression_profile_detail(level: int) -> str:
    if level <= 2:
        return "menos compresion, mas velocidad"
    if level <= 6:
        return "equilibrado entre tamano y velocidad"
    return "mas compresion, mas lentitud"


def render_level_bar(level: int, maximum: int = 9, width: int = 10) -> str:
    filled = round((level / maximum) * width) if maximum else width
    filled = max(0, min(width, filled))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def render_compression_setting(level: int) -> Panel:
    safe_level = sanitize_compression_level(level)
    profile = compression_profile_name(safe_level)
    detail = tr(compression_profile_detail(safe_level))
    codec = active_compression_codec()
    text = Table.grid(padding=(0, 1))
    text.add_row(tr("Level"), f"{safe_level}/9 {render_level_bar(safe_level)}")
    text.add_row(tr("Codec"), codec)
    text.add_row(tr("Mode"), profile)
    text.add_row(tr("Tradeoff"), detail)
    text.add_row(tr("Rule"), tr("0 = mas rapido y mas grande | 9 = mas lento y mas pequeno"))
    return Panel(text, title=tr("Compression"), border_style="cyan")


def total_memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
            return pages * page_size
    except (AttributeError, OSError, ValueError):
        pass

    if normalize_os_name() == "macos":
        try:
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
            return int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None


def available_memory_bytes() -> int | None:
    os_name = normalize_os_name()
    if os_name == "linux":
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None

    if os_name == "macos":
        try:
            result = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        page_size = 4096
        counters: dict[str, int] = {}
        for line in result.stdout.splitlines():
            if "page size of" in line and "bytes" in line:
                try:
                    page_size = int(line.split("page size of", 1)[1].split("bytes", 1)[0].strip())
                except ValueError:
                    page_size = 4096
                continue
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            digits = "".join(char for char in raw_value if char.isdigit())
            if digits:
                counters[key.strip()] = int(digits)
        available_pages = counters.get("Pages free", 0) + counters.get("Pages speculative", 0) + counters.get("Pages inactive", 0)
        if available_pages > 0:
            return available_pages * page_size
    return None


def memory_pressure_ratio() -> float | None:
    total = total_memory_bytes()
    available = available_memory_bytes()
    if not total or not available or total <= 0:
        return None
    ratio = 1.0 - (available / total)
    return max(0.0, min(1.0, ratio))


def estimate_pack_working_set(entries: list["FileEntry"]) -> int:
    if not entries:
        return 32 * 1024 * 1024
    sizes = sorted((entry.size for entry in entries), reverse=True)
    largest = sizes[0]
    head = sizes[: min(4, len(sizes))]
    average_head = sum(head) // len(head)
    return max(24 * 1024 * 1024, int(max(largest * 1.35, average_head * 1.75)))


def safe_pack_jobs(entries: list["FileEntry"], requested_jobs: int) -> tuple[int, str]:
    requested = sanitize_jobs(requested_jobs)
    if not entries:
        return requested, "no files"
    available = available_memory_bytes()
    if not available:
        return requested, "memory unknown"
    per_job_budget = estimate_pack_working_set(entries)
    usable_budget = max(256 * 1024 * 1024, int(available * 0.5))
    memory_based_jobs = max(1, usable_budget // per_job_budget)
    clamped = max(1, min(requested, memory_based_jobs))
    if requested >= 4 and clamped == 1 and available >= 1024 * 1024 * 1024:
        clamped = 2
    if clamped >= requested:
        return requested, "memory ok"
    return clamped, f"memory budget {format_bytes(usable_budget)} / job ~{format_bytes(per_job_budget)}"


def adaptive_inflight_label(pressure: float | None) -> str:
    if pressure is None:
        return "mem unknown"
    if pressure >= 0.92:
        return "mem critical"
    if pressure >= 0.84:
        return "mem high"
    if pressure >= 0.72:
        return "mem warm"
    if pressure >= 0.60:
        return "mem normal"
    return "mem cool"


def adaptive_next_inflight_limit(current_limit: int, max_jobs: int) -> tuple[int, str]:
    pressure = memory_pressure_ratio()
    label = adaptive_inflight_label(pressure)
    current = max(1, min(max_jobs, current_limit))
    if pressure is None:
        return current, label
    if pressure >= 0.90:
        return max(1, current // 2), label
    if pressure >= 0.82:
        return max(1, current - 1), label
    if pressure >= 0.72:
        return current, label
    if pressure < 0.60 and current < max_jobs:
        return min(max_jobs, current + 2), label
    if current < max_jobs:
        return min(max_jobs, current + 1), label
    return current, label


def create_pack_executor(requested_jobs: int):
    if requested_jobs <= 1:
        return ThreadPoolExecutor(max_workers=1), "threads"
    try:
        return ProcessPoolExecutor(max_workers=requested_jobs), "processes"
    except (OSError, PermissionError):
        return ThreadPoolExecutor(max_workers=requested_jobs), "threads-fallback"


def detect_shell() -> str:
    """Best-effort shell detection.

    Notes:
        On Windows, COMSPEC often points to cmd.exe even when running inside
        PowerShell/Windows Terminal. We prefer detecting PowerShell via the
        presence of the PSModulePath env var.

        When no shell can be detected, we return "unknown" (instead of an empty
        string) so downstream code can branch on an explicit sentinel.
    """

    # Windows: PowerShell sets PSModulePath.
    if os.environ.get("PSModulePath"):
        return "powershell"

    raw_shell = (os.environ.get("SHELL") or os.environ.get("COMSPEC") or "").strip()

    # Some environments store the shell command with extra arguments
    # (e.g. "/bin/bash -l" or "cmd.exe /c"). Parse it like a command line
    # so quoted paths with spaces still work.
    shell = raw_shell
    if shell:
        # shlex.split(posix=True) treats backslashes as escape characters,
        # which breaks common Windows-style values such as:
        #   "C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoLogo
        # Detect those inputs and parse them in non-posix mode.
        looks_windowsy = "\\" in shell or bool(re.match(r"^[A-Za-z]:", shell.strip().lstrip('"').lstrip("'")))
        try:
            parts = shlex.split(shell, posix=not looks_windowsy)
        except ValueError:
            parts = []
        if parts:
            shell = parts[0]
        else:
            shell = shell.strip().strip('"').strip("'")
            if shell and any(ch.isspace() for ch in shell):
                shell = shell.split()[0]

    shell = shell.strip().strip('"').strip("'")
    if not shell:
        return "unknown"

    # When running tests on POSIX, Windows paths with backslashes would be
    # treated as a single filename by pathlib.Path. Detect those cases and
    # parse them as Windows paths explicitly.
    if "\\" in shell or (":" in shell and "/" not in shell):
        name = PureWindowsPath(shell).name.lower()
    else:
        name = Path(shell).name.lower()

    # Normalize common Windows variants.
    if name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
        return "powershell"
    if name in {"cmd", "cmd.exe"}:
        return "cmd"

    return name or "unknown"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_key(key_path: Path, key: bytes) -> None:
    ensure_parent(key_path)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass


def load_profiles(profile_path: Path | None = None) -> dict:
    profile_path = profile_path or default_profile_store()
    if not profile_path.exists():
        return {}
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"El store de perfiles es invalido ({profile_path}): {exc}")
    if not isinstance(raw, dict):
        die("El store de perfiles debe ser un objeto JSON.")
    return raw


def save_profiles(data: dict, profile_path: Path | None = None) -> None:
    profile_path = profile_path or default_profile_store()
    ensure_parent(profile_path)
    profile_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_settings(settings_path: Path | None = None) -> dict:
    settings_path = settings_path or default_settings_store()
    data = dict(DEFAULT_SETTINGS)
    if not settings_path.exists():
        return data
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(
            trf(
                "El store de settings es invalido ({path}): {exc}",
                path=settings_path,
                exc=exc,
            )
        )
    if not isinstance(raw, dict):
        die(tr("El store de settings debe ser un objeto JSON."))
    data.update(raw)
    data["compression_level"] = sanitize_compression_level(data.get("compression_level"))
    data["jobs"] = sanitize_jobs(data.get("jobs"))
    data["language"] = sanitize_language_setting(data.get("language"))
    data["update_check_enabled"] = sanitize_update_check_enabled(data.get("update_check_enabled"))
    data["update_check_interval_hours"] = sanitize_update_check_interval_hours(data.get("update_check_interval_hours"))
    try:
        data["update_check_last_ts"] = int(data.get("update_check_last_ts") or 0)
    except (TypeError, ValueError):
        data["update_check_last_ts"] = 0
    return data


def save_settings(data: dict, settings_path: Path | None = None) -> None:
    settings_path = settings_path or default_settings_store()
    ensure_parent(settings_path)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    merged["compression_level"] = sanitize_compression_level(merged.get("compression_level"))
    merged["jobs"] = sanitize_jobs(merged.get("jobs"))
    merged.pop("encryption", None)
    merged["language"] = sanitize_language_setting(merged.get("language"))
    settings_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_history_snapshot(package_path: Path, history_dir: Path | None = None) -> Path | None:
    if not package_path.exists():
        return None
    bundle_name = package_path.stem
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_dir = history_dir or default_history_dir()
    target_dir = history_dir / bundle_name
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = target_dir / f"{timestamp}.peridot"
    shutil.copy2(package_path, snapshot_path)
    return snapshot_path


def fingerprint_key(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def decode_aesgcm_key_bytes(raw: bytes | str) -> bytes | None:
    """Decode a 32-byte AES-GCM key from raw bytes, text, or base64.

    Accepts:
    - Raw 32 bytes
    - Raw 32 bytes with a trailing newline (common when copy/pasting into files)
    - Hex-encoded 32 bytes (64 hex chars, with optional whitespace/newlines)
    - base64url-encoded bytes (with or without padding, with optional whitespace/newlines)
    - A string containing either of the above (UTF-8)

    Notes:
        When the input is *bytes*, we avoid aggressively stripping whitespace
        because a truly-random 32-byte key can contain whitespace bytes.
        We only strip a single trailing line ending when the length suggests
        an otherwise-valid raw key.
    """

    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw

    if len(raw_bytes) == 32:
        return raw_bytes

    if isinstance(raw, (bytes, bytearray)):
        # Accept raw keys with a trailing newline/CRLF without touching
        # interior bytes.
        if raw_bytes.endswith(b"\r\n") and len(raw_bytes) == 34:
            return raw_bytes[:-2]
        if raw_bytes.endswith(b"\n") and len(raw_bytes) == 33:
            return raw_bytes[:-1]
        if raw_bytes.endswith(b"\r") and len(raw_bytes) == 33:
            return raw_bytes[:-1]

    cleaned = b"".join(raw_bytes.split())
    if not cleaned:
        return None

    # Accept hex-encoded keys (common when copy/pasting from CLIs).
    # Also accept an optional "0x" prefix.
    if cleaned[:2].lower() == b"0x":
        cleaned = cleaned[2:]

    if len(cleaned) == 64:
        try:
            decoded_hex = bytes.fromhex(cleaned.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            decoded_hex = None
        if decoded_hex is not None and len(decoded_hex) == 32:
            return decoded_hex

    # base64 decoders expect padding; allow unpadded base64url keys.
    missing_padding = (-len(cleaned)) % 4
    if missing_padding:
        cleaned += b"=" * missing_padding

    decoded: bytes | None

    try:
        decoded = base64.urlsafe_b64decode(cleaned)
    except Exception:
        decoded = None

    if decoded is None or len(decoded) != 32:
        # Also accept standard base64 (with '+' and '/') because keys are often
        # copy/pasted from tools that do not use base64url.
        try:
            decoded = base64.b64decode(cleaned)
        except Exception:
            decoded = None

    return decoded if decoded is not None and len(decoded) == 32 else None


def load_key(key_path: Path, create: bool = False) -> bytes:
    if key_path.exists():
        key = key_path.read_bytes()
        decoded = decode_aesgcm_key_bytes(key)
        if decoded is not None:
            if decoded != key:
                try:
                    write_key(key_path, decoded)
                except OSError:
                    pass
            return decoded
        die(
            f"Clave invalida en {key_path}: se esperaban 32 bytes para AES-GCM. "
            "Formatos aceptados: 32 bytes raw, 64 hex (opcional 0x) o base64/base64url."
        )
    if not create:
        die(f"No se encontro la clave en {key_path}")
    AESGCM_impl, _InvalidTag = require_cryptography()
    key = AESGCM_impl.generate_key(bit_length=256)
    write_key(key_path, key)
    return key


def manifest_from_zip(package_path: Path) -> dict:
    try:
        with ZipFile(package_path) as zf:
            with zf.open("manifest.json") as handle:
                manifest = json.load(handle)
    except FileNotFoundError:
        die(f"No existe el paquete {package_path}")
    except KeyError:
        die(f"{package_path} no contiene manifest.json")
    except OSError as exc:
        die(f"No se pudo abrir {package_path}: {exc}")

    if manifest.get("package_version") != PACKAGE_VERSION:
        die(
            f"Version de paquete no soportada: {manifest.get('package_version')}. "
            f"Esperada: {PACKAGE_VERSION}"
        )
    return manifest


@dataclass
class FileEntry:
    source: Path
    relative_path: str
    size: int
    mode: int


@dataclass(frozen=True)
class ConfigGroup:
    key: str
    category: str
    label: str
    description: str
    paths: tuple[str, ...]
    default: bool = False


def config_groups_for_os(os_name: str) -> list[ConfigGroup]:
    shared = [
        ConfigGroup(
            "git-ssh",
            "Core",
            "Git + SSH",
            "Git identity, global config and SSH keys/config",
            ("~/.gitconfig", "~/.gitignore", "~/.gitignore_global", "~/.ssh"),
            default=True,
        ),
        ConfigGroup(
            "terminal-tools",
            "Terminal",
            "Terminal tools",
            "tmux, wget and generic terminal helpers",
            ("~/.tmux.conf", "~/.config/kitty", "~/.config/wezterm"),
        ),
        ConfigGroup(
            "editors-vscode",
            "Editors",
            "VS Code",
            "VS Code and compatible editor settings",
            ("~/.vscode",),
        ),
        ConfigGroup(
            "editors-zed",
            "Editors",
            "Zed",
            "Zed editor settings",
            ("~/.config/zed",),
        ),
        ConfigGroup(
            "dev-node",
            "Development",
            "Node tooling",
            "npm, yarn and JS tooling config",
            ("~/.npmrc", "~/.yarnrc", "~/.config/yarn"),
        ),
        ConfigGroup(
            "dev-rust",
            "Development",
            "Rust tooling",
            "Cargo config and rustup-related settings",
            ("~/.cargo/config.toml", "~/.cargo/credentials.toml"),
        ),
        ConfigGroup(
            "dev-asdf",
            "Development",
            "asdf / versions",
            "Version manager files such as .tool-versions",
            ("~/.tool-versions",),
        ),
    ]

    if os_name == "macos":
        return shared + [
            ConfigGroup(
                "shell-fish",
                "Shells",
                "Fish shell",
                "fish config and functions",
                ("~/.config/fish", "~/.local/share/fish"),
                default=detect_shell() == "fish",
            ),
            ConfigGroup(
                "shell-zsh",
                "Shells",
                "Zsh shell",
                "zsh profile, env and rc files",
                ("~/.zshrc", "~/.zprofile", "~/.zshenv"),
                default=detect_shell() == "zsh",
            ),
            ConfigGroup(
                "shell-bash",
                "Shells",
                "Bash shell",
                "bash profile and rc files",
                ("~/.bashrc", "~/.bash_profile", "~/.profile"),
            ),
            ConfigGroup(
                "apps-raycast",
                "Apps",
                "Raycast",
                "Raycast local config stored under .config",
                ("~/.config/raycast",),
            ),
            ConfigGroup(
                "apps-macos-code",
                "Apps",
                "VS Code User",
                "User settings stored in Library/Application Support",
                ("~/Library/Application Support/Code/User",),
            ),
        ]

    if os_name == "windows":
        return shared + [
            ConfigGroup(
                "shell-powershell",
                "Shells",
                "PowerShell",
                "PowerShell profiles and aliases from Documents/PowerShell",
                (
                    "~/Documents/PowerShell",
                    "~/Documents/WindowsPowerShell",
                    "~/OneDrive/Documents/PowerShell",
                    "~/OneDrive/Documents/WindowsPowerShell",
                    "~/.config/powershell",
                ),
                default=True,
            ),
            ConfigGroup(
                "shell-wsl",
                "Shells",
                "WSL",
                "WSL integration config",
                ("~/.wslconfig",),
            ),
            ConfigGroup(
                "apps-terminal",
                "Apps",
                "Windows Terminal",
                "Windows Terminal local settings",
                ("~/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState",),
            ),
            ConfigGroup(
                "apps-vscode-user",
                "Apps",
                "VS Code User",
                "User settings in AppData/Roaming",
                ("~/AppData/Roaming/Code/User",),
            ),
        ]

    return shared + [
        ConfigGroup(
            "shell-zsh",
            "Shells",
            "Zsh shell",
            "zsh profile, env and rc files",
            ("~/.zshrc", "~/.zprofile", "~/.zshenv"),
            default=detect_shell() == "zsh",
        ),
        ConfigGroup(
            "shell-bash",
            "Shells",
            "Bash shell",
            "bash profile and rc files",
            ("~/.bashrc", "~/.bash_profile", "~/.profile"),
            default=detect_shell() == "bash",
        ),
        ConfigGroup(
            "shell-fish",
            "Shells",
            "Fish shell",
            "fish config and functions",
            ("~/.config/fish", "~/.local/share/fish"),
            default=detect_shell() == "fish",
        ),
        ConfigGroup(
            "apps-vscode-user",
            "Apps",
            "VS Code User",
            "User settings in ~/.config/Code/User",
            ("~/.config/Code/User", "~/.config/VSCodium/User"),
        ),
        ConfigGroup(
            "apps-neovim",
            "Apps",
            "Neovim",
            "Neovim and Vim config",
            ("~/.config/nvim", "~/.vimrc"),
        ),
    ]


def existing_paths(path_specs: tuple[str, ...] | list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for path_spec in path_specs:
        path = Path(path_spec).expanduser()
        if path.exists() and path not in seen:
            seen.add(path)
            resolved.append(path)
    return resolved


def default_export_roots() -> list[Path]:
    groups = config_groups_for_os(normalize_os_name())
    selected: list[Path] = []
    seen: set[Path] = set()
    for group in groups:
        if not group.default:
            continue
        for path in existing_paths(group.paths):
            if path not in seen:
                seen.add(path)
                selected.append(path)
    return selected


def get_recommended_preset() -> str:
    current_os = normalize_os_name()
    shell = detect_shell()
    candidates = [
        f"{current_os}-{shell}",
        f"{current_os}-powershell" if current_os == "windows" else "",
        f"{current_os}-zsh" if current_os in {"macos", "linux"} else "",
        f"{current_os}-bash" if current_os == "linux" else "",
    ]
    for candidate in candidates:
        if candidate and candidate in PRESET_LIBRARY:
            return candidate
    return "macos-fish"


def render_presets_table() -> None:
    table = Table(title=tr("Dot Presets"), header_style="bold cyan")
    table.add_column("Preset", style="green")
    table.add_column("Target", style="white")
    table.add_column("Paths", justify="right", style="magenta")
    table.add_column("Description", style="dim")
    for name, preset in PRESET_LIBRARY.items():
        table.add_row(
            name,
            f"{preset['platform']} / {preset['shell']}",
            str(len(preset["paths"])),
            preset["description"],
        )
    console.print(table)


def apply_preset(args, preset_name: str, force_paths: bool = False) -> None:
    if preset_name == "custom":
        args.preset = "custom"
        return
    preset = PRESET_LIBRARY.get(preset_name)
    if not preset:
        candidates = sorted(PRESET_LIBRARY)
        available = ", ".join(candidates)
        suggestions = difflib.get_close_matches(preset_name, candidates, n=3, cutoff=0.6)
        extra = ""
        if suggestions:
            extra = " " + trf("Quizás quisiste decir: {suggestions}", suggestions=", ".join(suggestions))
        die(
            trf("Preset desconocido: {preset}. Disponibles: {available}", preset=preset_name, available=available)
            + extra
        )

    args.preset = preset_name
    if not args.name:
        args.name = f"{platform.node() or 'my'}-{preset_name}"
    if not args.description:
        args.description = preset["description"]
    if not args.platform:
        args.platform = preset["platform"]
    if not args.shell:
        args.shell = preset["shell"]
    if not args.tags:
        args.tags = list(preset["tags"])
    if force_paths or not args.paths:
        args.paths = list(preset["paths"])


def render_config_group_table(groups: list[ConfigGroup], selected_keys: set[str], marker_label: str = "Pick") -> None:
    table = Table(title=tr("Config Catalog"), header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column(marker_label, justify="center")
    table.add_column("Category", style="magenta")
    table.add_column("Group", style="green")
    table.add_column("Description", style="white")
    table.add_column("Found", justify="right", style="cyan")
    for index, group in enumerate(groups, start=1):
        marker = "x" if group.key in selected_keys else ""
        found = len(existing_paths(group.paths))
        table.add_row(str(index), marker, group.category, group.label, group.description, str(found))
    console.print(table)


def checkbox_prompt(message: str, choices: list, instruction: str | None = None):
    # questionary requires an interactive TTY; when stdout is not a real TTY
    # (e.g. redirected output / CI), the UI becomes unreadable.
    if not QUESTIONARY_AVAILABLE or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    return questionary.checkbox(
        tr(message),
        choices=choices,
        instruction=tr(instruction or "Espacio para marcar, Enter para confirmar"),
    ).ask()


def checkbox_unavailable_reason() -> str | None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "no_tty"
    if not QUESTIONARY_AVAILABLE:
        return "missing_questionary"
    return None


def explain_checkbox_unavailable() -> None:
    reason = checkbox_unavailable_reason()
    if reason == "no_tty":
        console.print(
            f"[yellow]{tr('Checkbox UI no disponible:')}[/yellow] {tr('esta sesion no tiene un TTY interactivo real.')}"
        )
        console.print(f"[dim]{tr('Ejecuta Peridot directamente en una terminal interactiva.')}[/dim]")
    elif reason == "missing_questionary":
        missing_questionary_text = "falta la dependencia 'questionary' en este Python."
        install_cmd = install_hint("-r requirements.txt")
        install_hint_text = trf("Usa el binario instalado con './install.sh' o ejecuta '{cmd}'.", cmd=install_cmd)
        console.print(
            f"[yellow]{tr('Checkbox UI no disponible:')}[/yellow] {tr(missing_questionary_text)}"
        )
        console.print(
            f"[dim]{install_hint_text}[/dim]"
        )


def interactive_checkbox_paths(paths: list[Path], preselected: list[Path] | None = None) -> list[Path] | None:
    if not paths:
        return []
    preselected_set = set(preselected or paths)
    choices = []
    for path in paths:
        label = str(path)
        if path.exists():
            suffix = "dir" if path.is_dir() else "file"
            label = f"{label}  [{suffix}]"
        choices.append(Choice(title=label, value=path, checked=path in preselected_set))
    return checkbox_prompt("Selecciona rutas", choices)


def build_path_catalog(os_name: str) -> list[tuple[Path, str]]:
    catalog: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for group in config_groups_for_os(os_name):
        for path in existing_paths(group.paths):
            if path in seen:
                continue
            seen.add(path)
            label = f"[{group.category}] {group.label}"
            catalog.append((path, label))
    return catalog


def interactive_checkbox_catalog_paths(
    os_name: str,
    preselected: list[Path] | None = None,
) -> list[Path] | None:
    if not QUESTIONARY_AVAILABLE or not sys.stdin.isatty():
        return None
    catalog = build_path_catalog(os_name)
    preselected_set = set(preselected or [])
    choices = []
    for path, source_label in catalog:
        kind = "dir" if path.is_dir() else "file"
        title = f"{path}  [{kind}]  {source_label}"
        choices.append(Choice(title=title, value=path, checked=path in preselected_set))
    return checkbox_prompt("Selecciona rutas para este bundle", choices)


def recommended_group_keys(groups: list[ConfigGroup], shell_name: str) -> set[str]:
    selected = {group.key for group in groups if group.default}
    shell_map = {
        "fish": "shell-fish",
        "zsh": "shell-zsh",
        "bash": "shell-bash",
        "powershell": "shell-powershell",
    }
    preferred = shell_map.get(shell_name)
    if preferred:
        selected.add(preferred)
    return {group.key for group in groups if group.key in selected}


def interactive_select_config_groups(os_name: str, shell_name: str) -> list[Path]:
    groups = config_groups_for_os(os_name)
    selected_keys = recommended_group_keys(groups, shell_name)

    # If we don't have a real interactive TTY pair, do not attempt any prompts.
    # This avoids blocking reads from stdin when stdout is redirected (e.g. CI,
    # piping output).
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        selected_paths: list[Path] = []
        seen: set[Path] = set()
        for group in groups:
            if group.key not in selected_keys:
                continue
            for path in existing_paths(group.paths):
                if path not in seen:
                    seen.add(path)
                    selected_paths.append(path)
        return selected_paths

    if QUESTIONARY_AVAILABLE:
        choices = []
        for group in groups:
            found = len(existing_paths(group.paths))
            title = f"[{group.category}] {group.label} ({found} found) - {group.description}"
            choices.append(Choice(title=title, value=group.key, checked=group.key in selected_keys))
        result = checkbox_prompt("Selecciona grupos de configuracion", choices)
        if result is not None:
            selected_keys = set(result)

    else:
        while True:
            render_config_group_table(groups, selected_keys)
            console.print(
                "[dim]Toggle with numbers like '1 4 7'. Commands: [b]a[/b]=all, [b]n[/b]=none, [b]d[/b]=defaults, [b]c[/b]=continue.[/dim]"
            )
            raw = Prompt.ask(tr("Selecciona grupos"), default="c").strip().lower()
            if raw == "c":
                break
            if raw == "a":
                selected_keys = {group.key for group in groups}
                continue
            if raw == "n":
                selected_keys = set()
                continue
            if raw == "d":
                selected_keys = recommended_group_keys(groups, shell_name)
                continue

            for token in raw.replace(",", " ").split():
                if not token.isdigit():
                    continue
                index = int(token) - 1
                if 0 <= index < len(groups):
                    group_key = groups[index].key
                    if group_key in selected_keys:
                        selected_keys.remove(group_key)
                    else:
                        selected_keys.add(group_key)

    selected_paths: list[Path] = []
    seen: set[Path] = set()
    for group in groups:
        if group.key not in selected_keys:
            continue
        for path in existing_paths(group.paths):
            if path not in seen:
                seen.add(path)
                selected_paths.append(path)
    return selected_paths


def choose_pack_base(os_name: str, preset_name: str | None) -> str:
    options = [
        ("Preset or default selection", "preset"),
        ("Categorized config groups", "catalog"),
        ("Start empty", "empty"),
    ]
    if QUESTIONARY_AVAILABLE and sys.stdin.isatty():
        answer = questionary.select(
            tr("Como quieres construir este bundle?"),
            choices=[Choice(title=title, value=value) for title, value in options],
            default="preset" if preset_name else "catalog",
        ).ask()
        if answer:
            return answer

    default_choice = "preset" if preset_name else "catalog"
    console.print(f"[dim]{tr('Bundle source: preset, catalog or empty')}[/dim]")
    return Prompt.ask(tr("Base selection"), default=default_choice)


def source_root_for_path(path: Path) -> Path:
    home = Path.home()
    try:
        path.relative_to(home)
        return home
    except ValueError:
        return path.parent


def should_exclude_entry(path: Path) -> bool:
    """Return True when a discovered path should be excluded from packing.

    The default rules are anchored to the user's home directory because Peridot
    mostly targets dotfiles.

    Additionally, we exclude well-known junk basenames (e.g. .DS_Store, .cache)
    anywhere in the tree, including when packing paths outside $HOME.
    """

    excluded_basenames = {
        Path(excluded).name for excluded in DEFAULT_EXCLUDES if "/" not in excluded
    }

    # Basename/segment-based exclusion: applies everywhere.
    # This ensures junk files like .DS_Store are filtered even when nested.
    if any(part in excluded_basenames for part in path.parts):
        return True

    home = Path.home()
    try:
        relative = path.relative_to(home).as_posix()
    except ValueError:
        return False

    # Home-anchored exclusions (exact or prefix matches).
    for excluded in DEFAULT_EXCLUDES:
        if "/" not in excluded:
            continue
        if relative == excluded or relative.startswith(f"{excluded}/"):
            return True
    return False


def collect_files(
    paths: list[Path],
    progress_callback: Callable[[int, Path], None] | None = None,
) -> list[FileEntry]:
    entries: list[FileEntry] = []
    seen: set[str] = set()
    discovered = 0

    def is_symlink_safe(path: Path) -> bool | None:
        try:
            return path.is_symlink()
        except (PermissionError, OSError):
            return None

    for source in paths:
        expanded = source.expanduser()
        if not expanded.exists():
            console.print(f"[yellow]Aviso:[/yellow] se omite {expanded}, no existe.")
            continue
        is_symlink = is_symlink_safe(expanded)
        if is_symlink is None:
            console.print(f"[yellow]Aviso:[/yellow] se omite {expanded}, no se puede comprobar symlink.")
            continue
        if is_symlink:
            console.print(f"[yellow]Aviso:[/yellow] se omite {expanded}, es un symlink.")
            continue
        if should_exclude_entry(expanded):
            continue

        export_root = source_root_for_path(expanded)
        if expanded.is_file():
            relative = expanded.relative_to(export_root).as_posix()
            if relative not in seen:
                try:
                    stat_result = expanded.stat()
                except (PermissionError, OSError) as exc:
                    console.print(
                        f"[yellow]Aviso:[/yellow] se omite {expanded}, no se puede leer metadata ({type(exc).__name__}: {exc})."
                    )
                    continue
                seen.add(relative)
                entries.append(FileEntry(expanded, relative, stat_result.st_size, stat.S_IMODE(stat_result.st_mode)))
                discovered += 1
                if progress_callback:
                    progress_callback(discovered, expanded)
            continue

        for root, dirs, files in os.walk(expanded):
            root_path = Path(root)

            # Prune excluded directories early to avoid unnecessary traversal.
            # os.walk() honors in-place mutations of "dirs".
            dirs[:] = [
                d
                for d in dirs
                if (is_symlink_safe(root_path / d) is False) and not should_exclude_entry(root_path / d)
            ]

            for name in files:
                file_path = root_path / name
                is_symlink = is_symlink_safe(file_path)
                if is_symlink is None or is_symlink:
                    continue
                if should_exclude_entry(file_path):
                    continue
                relative = file_path.relative_to(export_root).as_posix()
                if relative in seen:
                    continue
                try:
                    stat_result = file_path.stat()
                except (PermissionError, OSError) as exc:
                    console.print(
                        f"[yellow]Aviso:[/yellow] se omite {file_path}, no se puede leer metadata ({type(exc).__name__}: {exc})."
                    )
                    continue
                seen.add(relative)
                entries.append(FileEntry(file_path, relative, stat_result.st_size, stat.S_IMODE(stat_result.st_mode)))
                discovered += 1
                if progress_callback and (discovered <= 20 or discovered % 200 == 0):
                    progress_callback(discovered, root_path)

    return sorted(entries, key=lambda item: item.relative_path)


def filter_entries(entries: list[FileEntry], excludes: list[str] | None = None) -> list[FileEntry]:
    """Filter entries by glob patterns.

    Notes:
        Manifests can contain Windows-style paths ("\\") when generated on Windows.
        Normalize both entry paths and patterns to POSIX-style before matching so
        excludes behave consistently across platforms.
    """

    if not excludes:
        return entries

    normalized_patterns = [pattern.replace("\\", "/") for pattern in excludes]

    filtered: list[FileEntry] = []
    for entry in entries:
        relative_norm = entry.relative_path.replace("\\", "/")
        if any(fnmatch.fnmatch(relative_norm, pattern) for pattern in normalized_patterns):
            continue
        filtered.append(entry)
    return filtered


def normalize_excludes(excludes: list[str] | None) -> list[str]:
    """Normalize --exclude inputs.

    Users often pass multiple globs in a single flag (e.g. "a,b,c"). Support
    that by splitting on commas, trimming whitespace, and dropping empties.
    """

    if not excludes:
        return []

    normalized: list[str] = []
    for item in excludes:
        if not item:
            continue
        for part in str(item).split(","):
            part = part.strip()
            if part:
                normalized.append(part)
    return normalized


def compress_payload(raw: bytes, compression_level: int) -> bytes:
    codec = active_compression_codec()
    if codec == "zstd":
        compressor = zstd.ZstdCompressor(level=compression_level + 1)
        return compressor.compress(raw)
    return gzip.compress(raw, compresslevel=compression_level, mtime=0)


def shannon_entropy(sample: bytes) -> float:
    """Return Shannon entropy (bits/byte) for a sample."""

    if not sample:
        return 0.0

    counts = [0] * 256
    for b in sample:
        counts[b] += 1

    import math

    length = len(sample)
    entropy = 0.0
    for c in counts:
        if not c:
            continue
        p = c / length
        entropy -= p * math.log2(p)
    return entropy


def likely_incompressible(raw: bytes, relative_path: str) -> bool:
    suffix = Path(relative_path).suffix.lower()
    if suffix in INCOMPRESSIBLE_SUFFIXES:
        return True
    # Sample up to 32 KiB to estimate entropy; high entropy tends to compress poorly.
    sample = raw[: 32 * 1024]
    if len(sample) < 1024:
        return False
    return shannon_entropy(sample) > 7.6


def choose_compression(raw: bytes, relative_path: str, compression_level: int) -> tuple[str, bytes]:
    if compression_level <= 0:
        return "none", raw
    if likely_incompressible(raw, relative_path):
        return "none", raw
    compressed = compress_payload(raw, compression_level)
    if len(compressed) >= int(len(raw) * 0.98):
        return "none", raw
    return active_compression_codec(), compressed


def build_payload_record(
    *,
    raw: bytes,
    relative_path: str,
    mode: int,
    payload_name: str,
    key: bytes,
    compression_level: int,
) -> tuple[bytes, dict]:
    compression, payload = choose_compression(raw, relative_path, compression_level)
    nonce = os.urandom(12)
    AESGCM_impl, _InvalidTag = require_cryptography()
    encrypted = AESGCM_impl(key).encrypt(nonce, payload, None)
    encryption_meta = {"algorithm": ENCRYPTION_ALGORITHM, "nonce": nonce.hex()}
    record = {
        "path": relative_path,
        "payload": f"payloads/{payload_name}",
        "size": len(raw),
        "compression": compression,
        "encryption": encryption_meta,
        "compressed_size": len(payload),
        "encrypted_size": len(encrypted),
        "mode": mode,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return encrypted, record


def _is_sensitive_path(name: str, path_str: str) -> bool:
    """Heuristic detection of sensitive files.

    We intentionally avoid naive substring matching for generic tokens (e.g. "token"),
    because that creates noisy false positives (e.g. "stockton").

    Args:
        name: Basename (lowercased).
        path_str: Relative path (lowercased, posix-style).
    """

    # Exact dotfiles / well-known filenames.
    # Keep this list focused to avoid false positives.
    exact_names = {
        ".env",
        ".envrc",
        ".npmrc",
        ".netrc",
        ".pypirc",
        ".git-credentials",
        "known_hosts",
        "authorized_keys",
    }
    if name in exact_names:
        return True

    # .env.* variants are commonly used by frameworks (e.g. .env.local, .env.production)
    # and often contain secrets.
    if name.startswith(".env.") and len(name) > len(".env."):
        return True

    # SSH config can contain host aliases, usernames, ports, proxy commands, etc.
    # Treat it as sensitive but avoid flagging generic "config" files elsewhere.
    # Normalize separators so Windows-style paths are covered as well.
    path_norm = path_str.replace("\\", "/")
    if name == "config" and (
        path_norm.endswith("/.ssh/config")
        or path_norm == ".ssh/config"
        or path_norm.endswith("/.aws/config")
        or path_norm == ".aws/config"
        or path_norm.endswith("/.kube/config")
        or path_norm == ".kube/config"
    ):
        return True

    # Docker credential store.
    # https://docs.docker.com/engine/reference/commandline/login/#credentials-store
    if name == "config.json" and (
        path_norm.endswith("/.docker/config.json") or path_norm == ".docker/config.json"
    ):
        return True

    # GnuPG key material.
    if path_norm == ".gnupg" or path_norm.startswith(".gnupg/") or "/.gnupg/" in path_norm:
        return True

    # OpenSSH supports including snippets from ~/.ssh/config.d/*
    # Those files frequently contain host aliases, user names and proxy
    # configuration, so treat them as sensitive as well.
    if path_norm.startswith(".ssh/config.d/") or "/.ssh/config.d/" in path_norm:
        return True

    # SSH private keys and similar.
    # Note: public keys (e.g. id_ed25519.pub) are intentionally NOT treated as
    # sensitive. They are meant to be shared and flagging them creates noise.
    key_prefixes = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "id_ed25519_sk", "id_ecdsa_sk", "id_rsa_sk"}
    for prefix in key_prefixes:
        if name == prefix:
            return True
        if name.startswith(f"{prefix}."):
            suffix = name[len(prefix) + 1 :]
            if suffix == "pub":
                return False
            return True

    # Generic tokens: match as a path segment or separated word, not a substring.
    # Accept separators: / . _ - (and Windows \ just in case).
    import re

    for token in ("credentials", "token"):
        pattern = rf"(^|[\\/._-]){re.escape(token)}([\\/._-]|$)"
        if re.search(pattern, name) or re.search(pattern, path_str):
            return True

    return False


def detect_sensitive_entries(entries: list[FileEntry]) -> list[FileEntry]:
    sensitive: list[FileEntry] = []
    for entry in entries:
        name = entry.source.name.lower()
        path_str = entry.relative_path.lower()
        if _is_sensitive_path(name, path_str):
            sensitive.append(entry)
    return sensitive


def filter_sensitive_entries(
    entries: list[FileEntry],
    sensitive_entries: list[FileEntry],
    args,
    *,
    is_tty: bool,
) -> list[FileEntry]:
    """Drop sensitive entries by default when we cannot prompt.

    Rationale:
        In interactive shells we can ask the user whether to include sensitive
        paths (.netrc, private SSH keys, tokens, etc.).

        In non-interactive contexts (CI, cron, pipes) prompting is not possible.
        In that case we choose the safer default: exclude them unless the user
        explicitly opted-in via --yes.
    """

    if not sensitive_entries:
        return entries

    if getattr(args, "yes", False):
        return entries

    preview = "\n".join(f"- {entry.relative_path}" for entry in sensitive_entries[:10])
    console.print(Panel(preview, title=tr("Rutas sensibles detectadas"), border_style="yellow"))

    if is_tty:
        if Confirm.ask(tr("Incluir estas rutas sensibles?"), default=False):
            return entries

        sensitive_paths = {entry.relative_path for entry in sensitive_entries}
        return [entry for entry in entries if entry.relative_path not in sensitive_paths]

    console.print(
        f"[yellow]Aviso:[/yellow] {tr('No hay un TTY interactivo; se excluyen rutas sensibles por defecto. Usa --yes para incluirlas.') }"
    )
    sensitive_paths = {entry.relative_path for entry in sensitive_entries}
    return [entry for entry in entries if entry.relative_path not in sensitive_paths]


def inflate_payload(payload: bytes, compression: str | None) -> bytes:
    """Inflate a payload according to the manifest's compression metadata.

    Notes:
        Older/hand-crafted manifests might omit the compression field.
        In that case we try gzip first and fall back to raw bytes.
    """

    if compression in {None, ""}:
        try:
            return gzip.decompress(payload)
        except OSError:
            # Older/hand-crafted manifests might omit compression.
            # We try gzip first, then zstd (if available), then fall back to raw bytes.
            if zstd is not None:
                try:
                    return zstd.ZstdDecompressor().decompress(payload)
                except Exception:
                    pass
            return payload

    if compression == "gzip":
        return gzip.decompress(payload)

    if compression == "zstd":
        if zstd is None:
            pip_hint = install_hint("zstandard")
            hint = venv_activation_hint()
            runtime = python_runtime_hint()

            extra_lines: list[str] = []
            if runtime:
                extra_lines.append(runtime)
            if hint:
                extra_lines.append(hint)

            die(
                tr("Este paquete usa zstd pero falta la dependencia 'zstandard'.")
                + " "
                + trf("Instalala con '{cmd}'.", cmd=pip_hint)
                + (("\n" + "\n".join(extra_lines)) if extra_lines else "")
            )
        return zstd.ZstdDecompressor().decompress(payload)

    if compression == "none":
        return payload

    die(f"Metodo de compresion no soportado: {compression}")


def decrypt_payload(encrypted: bytes, file_entry: dict, key: bytes) -> bytes:
    encryption_meta = file_entry.get("encryption") or {}
    algorithm = encryption_meta.get("algorithm") or ENCRYPTION_ALGORITHM
    if algorithm != ENCRYPTION_ALGORITHM:
        die(f"Algoritmo de cifrado no soportado: {algorithm}")
    nonce_hex = encryption_meta.get("nonce")
    if not nonce_hex:
        die(f"Falta nonce para {file_entry.get('path')}")
    AESGCM_impl, InvalidTag_impl = require_cryptography()
    try:
        return AESGCM_impl(key).decrypt(bytes.fromhex(nonce_hex), encrypted, None)
    except Exception as exc:
        # cryptography raises InvalidTag on auth failure.
        if InvalidTag_impl is not None and isinstance(exc, InvalidTag_impl):
            raise ValueError("invalid key")
        die(f"No se pudo descifrar {file_entry.get('path')}: {exc}")


def decode_package_payload(package_path: Path, file_entry: dict, key: bytes) -> bytes:
    with ZipFile(package_path) as bundle:
        encrypted = bundle.read(file_entry["payload"])
    payload = decrypt_payload(encrypted, file_entry, key)
    return inflate_payload(payload, file_entry.get("compression"))


def read_bundle_content(package_path: Path, manifest: dict, key: bytes, selected_paths: set[str] | None = None) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    with ZipFile(package_path) as bundle:
        for file_entry in manifest["files"]:
            if selected_paths and file_entry["path"] not in selected_paths:
                continue
            encrypted = bundle.read(file_entry["payload"])
            payload = decrypt_payload(encrypted, file_entry, key)
            contents[file_entry["path"]] = inflate_payload(payload, file_entry.get("compression"))
    return contents


def build_payload_job(
    source_path: str,
    relative_path: str,
    mode: int,
    payload_name: str,
    key: bytes,
    compression_level: int,
) -> tuple[bytes | None, dict]:
    try:
        raw = Path(source_path).read_bytes()
    except (PermissionError, OSError) as exc:
        # Common on Windows for files under ~/.ssh or other protected locations.
        # Return a structured error so the caller can skip instead of crashing.
        return None, {
            "path": relative_path,
            "source": source_path,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:
        # Catch-all to prevent a single file from crashing an entire pack.
        return None, {
            "path": relative_path,
            "source": source_path,
            "error": f"{type(exc).__name__}: {exc}",
        }

    encrypted, record = build_payload_record(
        raw=raw,
        relative_path=relative_path,
        mode=mode,
        payload_name=payload_name,
        key=key,
        compression_level=compression_level,
    )
    return encrypted, record


def write_bundle_from_raw(
    output: Path,
    bundle_name: str,
    description: str,
    platform: str,
    shell: str,
    arch: str,
    tags: list[str],
    notes: str,
    after_steps: list[str],
    files: dict[str, dict],
    key: bytes,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> None:
    history_snapshot = save_history_snapshot(output)
    files_manifest: list[dict] = []
    with TemporaryDirectory() as tmp_dir_name:
        payload_root = Path(tmp_dir_name) / "payloads"
        payload_root.mkdir(parents=True, exist_ok=True)
        for index, (path, file_meta) in enumerate(sorted(files.items()), start=1):
            raw = file_meta["raw"]
            payload_name = f"{index:04d}-{hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]}.bin"
            encrypted, record = build_payload_record(
                raw=raw,
                relative_path=path,
                mode=file_meta["mode"],
                payload_name=payload_name,
                key=key,
                compression_level=compression_level,
            )
            (payload_root / payload_name).write_bytes(encrypted)
            files_manifest.append(record)
        args = SimpleNamespace(
            name=bundle_name,
            description=description,
            platform=platform,
            shell=shell,
            arch=arch,
            tags=tags,
            notes=notes,
            after_steps=after_steps,
            sensitive_count=0,
            key_fingerprint=fingerprint_key(key),
        )
        manifest = build_manifest(args, files_manifest, [])
        ensure_parent(output)
        with ZipFile(output, "w", compression=ZIP_STORED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n", compress_type=ZIP_DEFLATED)
            for file_entry in files_manifest:
                bundle.write(payload_root / Path(file_entry["payload"]).name, file_entry["payload"])
    if history_snapshot:
        console.print(f"[dim]Previous snapshot saved to {history_snapshot}[/dim]")
    render_bundle_card(manifest, output)
    console.print(f"[bold green]Created[/bold green] {output}")


def build_manifest(args, files: list[dict], source_paths: list[str]) -> dict:
    total_size = sum(item["size"] for item in files)
    return {
        "package_version": PACKAGE_VERSION,
        "peridot_version": APP_VERSION,
        "bundle": {
            "name": args.name,
            "slug": slugify(args.name),
            "description": args.description,
            "platform": {
                "os": normalize_os_name(args.platform),
                "shell": args.shell,
                "arch": args.arch or platform.machine().lower(),
            },
            "tags": sorted(set(args.tags)),
            "created_at": utc_now(),
            "notes": args.notes,
            "post_apply": args.after_steps,
            "source": {
                "host": socket.gethostname(),
                "user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
                "home": str(Path.home()),
                "paths": source_paths,
            },
            "stats": {
                "files": len(files),
                "bytes": total_size,
            },
            "security": {
                "sensitive_files": args.sensitive_count,
                "key_fingerprint": args.key_fingerprint,
            },
        },
        "files": files,
    }


def print_banner() -> None:
    title = Text("PERIDOT", style="bold bright_green")
    subtitle = Text(tr("Bundles portables de configuracion para humanos"), style="italic cyan")
    panel = Panel(
        Align.center(Text.assemble(title, "\n", subtitle)),
        border_style="bright_green",
        padding=(1, 3),
    )
    console.print(panel)


def normalize_tags(raw_tags: list[str] | str | None) -> list[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        candidates = raw_tags.split(",")
    else:
        candidates = raw_tags

    tags: list[str] = []
    for item in candidates:
        for piece in str(item).split(","):
            cleaned = piece.strip()
            if cleaned:
                tags.append(cleaned)
    return sorted(set(tags))


def load_profile_into_args(args) -> None:
    if not getattr(args, "profile", ""):
        return
    profiles = load_profiles()
    profile = profiles.get(args.profile)
    if not profile:
        die(f"No existe el perfil '{args.profile}'")
    args.name = args.name or profile.get("name")
    args.description = args.description or profile.get("description", "")
    args.platform = args.platform or profile.get("platform", "")
    args.shell = args.shell or profile.get("shell", "")
    args.arch = args.arch or profile.get("arch", "")
    args.tags = args.tags or profile.get("tags", [])
    args.preset = args.preset or profile.get("preset", "")
    args.paths = args.paths or profile.get("paths", [])
    args.exclude = args.exclude or profile.get("exclude", [])
    args.notes = args.notes or profile.get("notes", "")
    args.after_steps = args.after_steps or profile.get("after_steps", [])


def apply_settings_defaults(args) -> None:
    settings = load_settings()
    args.compression_level = sanitize_compression_level(
        getattr(args, "compression_level", None) if getattr(args, "compression_level", None) is not None else settings["compression_level"]
    )
    args.jobs = sanitize_jobs(getattr(args, "jobs", None) if getattr(args, "jobs", None) is not None else settings["jobs"])
    args.language = sanitize_language(
        getattr(args, "language", None) if getattr(args, "language", None) is not None else settings["language"]
    )


def interactive_pack_setup(args) -> tuple[list[Path], Path]:
    render_presets_table()
    recommended_preset = args.preset or get_recommended_preset()
    preset_name = Prompt.ask(tr("Preset"), default=recommended_preset)
    if preset_name:
        apply_preset(args, preset_name, force_paths=False)

    default_name = f"{platform.node() or 'my'}-{normalize_os_name()}-bundle"
    if not args.name:
        args.name = Prompt.ask(tr("Bundle name"), default=default_name)

    current_os = normalize_os_name()
    args.description = Prompt.ask(
        tr("Description"),
        default=args.description or f"Config bundle for {args.name}",
    )
    args.platform = normalize_os_name(
        Prompt.ask(tr("Target OS"), default=args.platform or current_os)
    )
    args.shell = Prompt.ask(
        tr("Primary shell/runtime"),
        default=args.shell or detect_shell() or "any",
    )
    arch_default = args.arch or platform.machine().lower() or "any"
    args.arch = Prompt.ask(tr("Target architecture"), default=arch_default)
    tag_default = ", ".join(args.tags) if args.tags else ""
    entered_tags = Prompt.ask(tr("Tags (comma separated)"), default=tag_default)
    args.tags = normalize_tags(entered_tags)

    base_mode = choose_pack_base(args.platform, args.preset if getattr(args, "preset", "") else None)
    if base_mode == "preset":
        suggested_paths = [Path(item).expanduser() for item in args.paths] if args.paths else default_export_roots()
    elif base_mode == "catalog":
        suggested_paths = interactive_select_config_groups(args.platform, args.shell or detect_shell())
    else:
        suggested_paths = []

    if suggested_paths:
        preview = "\n".join(f"- {item}" for item in suggested_paths[:8])
        if len(suggested_paths) > 8:
            preview += f"\n- ... y {len(suggested_paths) - 8} mas"
        console.print(Panel(preview, title=tr("Selected paths"), border_style="cyan"))
        edit_selection = Confirm.ask(tr("Edit this selection?"), default=False)
        if not edit_selection:
            selected_paths = suggested_paths
        else:
            chosen = interactive_checkbox_catalog_paths(args.platform, suggested_paths)
            if chosen is not None:
                selected_paths = chosen
                if Confirm.ask(tr("Add extra paths manually?"), default=False):
                    raw_paths = Prompt.ask(tr("Extra paths (comma separated)"), default="")
                    extras = [Path(item.strip()).expanduser() for item in raw_paths.split(",") if item.strip()]
                    selected_paths.extend(extras)
            else:
                explain_checkbox_unavailable()
                console.print(f"[yellow]{tr('Usando entrada manual.')}[/yellow]")
                raw_paths = Prompt.ask(tr("Paths to include (comma separated)"))
                selected_paths = [Path(item.strip()).expanduser() for item in raw_paths.split(",") if item.strip()]
    else:
        chosen = interactive_checkbox_catalog_paths(args.platform, [])
        if chosen is not None:
            selected_paths = chosen
            if Confirm.ask(tr("Add extra paths manually?"), default=False):
                raw_paths = Prompt.ask(tr("Extra paths (comma separated)"), default="")
                selected_paths.extend([Path(item.strip()).expanduser() for item in raw_paths.split(",") if item.strip()])
        else:
            explain_checkbox_unavailable()
            console.print(f"[yellow]{tr('Usando entrada manual.')}[/yellow]")
            raw_paths = Prompt.ask(tr("Paths to include (comma separated)"))
            selected_paths = [Path(item.strip()).expanduser() for item in raw_paths.split(",") if item.strip()]

    selected_paths = list(dict.fromkeys(selected_paths))
    if not selected_paths:
        if suggested_paths:
            console.print(f"[yellow]{tr('No has seleccionado ninguna ruta, se usara la seleccion sugerida.')}[/yellow]")
            selected_paths = suggested_paths
        else:
            raw_paths = Prompt.ask(tr("Paths to include (comma separated)"))
            selected_paths = [Path(item.strip()).expanduser() for item in raw_paths.split(",") if item.strip()]

    output_default = str(args.output) if args.output else f"{slugify(args.name)}.peridot"
    args.output = Path(Prompt.ask(tr("Output package"), default=output_default))
    summary = Table.grid(padding=(0, 2))
    summary.add_row("Name", args.name)
    summary.add_row("Description", args.description)
    summary.add_row("Target", f"{args.platform} / {args.shell or 'any'} / {args.arch or 'any'}")
    summary.add_row("Tags", ", ".join(args.tags) if args.tags else "none")
    summary.add_row("Output", str(args.output))
    summary.add_row("Paths", str(len(selected_paths)))
    summary.add_row(
        "Compression",
        f"{args.compression_level}/9 ({compression_profile_name(args.compression_level)}: {compression_profile_detail(args.compression_level)})",
    )
    summary.add_row("Encryption", ENCRYPTION_ALGORITHM)
    summary.add_row("Workers", str(args.jobs))
    console.print(Panel(summary, title=tr("Pack Preview"), border_style="bright_green"))
    console.print(render_compression_setting(args.compression_level))
    return selected_paths, args.output


def prepare_pack_inputs(args) -> tuple[list[Path], Path]:
    load_profile_into_args(args)
    args.tags = normalize_tags(args.tags)
    if getattr(args, "preset", ""):
        apply_preset(args, args.preset, force_paths=not args.paths)
    if not args.platform:
        args.platform = normalize_os_name()
    if not args.shell:
        args.shell = detect_shell()
    if not args.arch:
        args.arch = platform.machine().lower()

    if sys.stdin.isatty():
        missing_core = not args.name or not args.description or not args.output
        if missing_core or not args.paths:
            return interactive_pack_setup(args)

    # Non-interactive defaults: avoid hard-failing when running from scripts/CI.
    if not args.name:
        args.name = f"{platform.node() or 'my'}-{normalize_os_name(args.platform)}-bundle"
    if args.description is None:
        args.description = ""

    paths = [Path(item).expanduser() for item in args.paths] if args.paths else default_export_roots()
    output = args.output or Path(f"{slugify(args.name)}.peridot")
    return paths, output


def render_bundle_card(manifest: dict, package_path: Path | None = None) -> None:
    bundle = manifest["bundle"]
    platform_data = bundle["platform"]
    stats = bundle["stats"]
    tags = ", ".join(bundle["tags"]) if bundle["tags"] else "none"
    description = bundle["description"] or "Sin descripcion"
    algorithms = sorted({((entry.get("encryption") or {}).get("algorithm") or ENCRYPTION_ALGORITHM) for entry in manifest["files"]}) or [ENCRYPTION_ALGORITHM]

    table = Table.grid(padding=(0, 2))
    table.add_row("Bundle", f"[bold]{bundle['name']}[/bold]")
    if package_path:
        table.add_row("Package", str(package_path))
    table.add_row("Description", description)
    table.add_row("Target", f"{platform_data['os']} / {platform_data.get('shell') or 'any'} / {platform_data.get('arch') or 'any'}")
    table.add_row("Files", str(stats["files"]))

    skipped_files = bundle.get("skipped_files") or []
    if skipped_files:
        table.add_row("Skipped", str(len(skipped_files)))

    table.add_row("Payload", format_bytes(stats["bytes"]))
    table.add_row("Encryption", ", ".join(algorithms))
    table.add_row("Tags", tags)
    table.add_row("Created", bundle["created_at"])
    table.add_row("From", f"{bundle['source']['user']}@{bundle['source']['host']}")
    if bundle.get("notes"):
        table.add_row("Notes", bundle["notes"])
    if bundle.get("security", {}).get("sensitive_files"):
        table.add_row("Sensitive", str(bundle["security"]["sensitive_files"]))

    console.print(
        Panel(
            table,
            title=f"[bold bright_green]{tr('Bundle Card')}[/bold bright_green]",
            border_style="green",
        )
    )


def render_file_table(manifest: dict, limit: int | None = None) -> None:
    table = Table(title=tr("Files"), header_style="bold cyan")
    table.add_column("Path", style="white")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Mode", justify="right", style="magenta")
    shown = manifest["files"] if limit is None else manifest["files"][:limit]
    for entry in shown:
        table.add_row(entry["path"], format_bytes(entry["size"]), oct(entry["mode"]))
    console.print(table)

    hidden_count = len(manifest["files"]) - len(shown)
    if hidden_count > 0:
        console.print(f"[dim]... y {hidden_count} ficheros mas[/dim]")


def print_manifest_json(manifest: dict) -> None:
    console.print_json(data=manifest)


def render_diff_table(rows: list[tuple[str, str]]) -> None:
    table = Table(title="Diff" if CURRENT_LANGUAGE == "es" else "Diff", header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Path", style="white")
    for status, path in rows:
        style = {"new": "green", "changed": "yellow", "same": "dim", "missing": "red"}.get(status, "white")
        table.add_row(f"[{style}]{status}[/{style}]", path)
    console.print(table)


def bundle_diff(manifest: dict, target_root: Path, key: bytes | None = None, package_path: Path | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    bundle_contents = read_bundle_content(package_path, manifest, key) if key and package_path else {}
    for file_entry in manifest["files"]:
        target_path = target_root / file_entry["path"]
        if not target_path.exists():
            rows.append(("new", file_entry["path"]))
            continue
        if key and package_path:
            current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
            rows.append(("same" if current_hash == file_entry["sha256"] else "changed", file_entry["path"]))
        else:
            rows.append(("exists", file_entry["path"]))
    return rows


def discover_local_bundles(base_dir: Path | None = None) -> list[Path]:
    root = (base_dir or Path.cwd()).expanduser()
    return sorted(root.glob("*.peridot"))


def render_local_bundle_table(base_dir: Path | None = None) -> None:
    bundles = discover_local_bundles(base_dir)
    if not bundles:
        # Avoid rendering a "fake" table row which can get visually truncated in narrow terminals.
        console.print(f"[dim]{tr('No hay bundles .peridot en este directorio')}[/dim]")
        return

    table = Table(title=tr("Bundles locales"), header_style="bold cyan")
    table.add_column("#", style="dim", justify="right")
    table.add_column("File", style="white")
    table.add_column("Size", justify="right", style="green")

    for index, bundle in enumerate(bundles, start=1):
        table.add_row(str(index), bundle.name, format_bytes(bundle.stat().st_size))
    console.print(table)


def choose_bundle_path(action_label: str) -> Path:
    bundles = discover_local_bundles()
    if bundles:
        render_local_bundle_table()
        default = bundles[0].name
    else:
        default = ""

    bundle_input = Prompt.ask(f"{action_label} package", default=default)
    if bundle_input.isdigit():
        index = int(bundle_input) - 1
        if 0 <= index < len(bundles):
            bundle_path = bundles[index]
        else:
            die(f"Indice fuera de rango: {bundle_input}")
    else:
        bundle_path = Path(bundle_input).expanduser()
    if not bundle_path.exists():
        die(f"No existe el paquete {bundle_path}")
    return bundle_path


def choose_bundle_paths(action_label: str) -> list[Path]:
    bundles = discover_local_bundles()
    if not bundles:
        die("No hay paquetes locales en este directorio.")
    render_local_bundle_table()
    if QUESTIONARY_AVAILABLE and sys.stdin.isatty():
        choices = [Choice(title=bundle.name, value=bundle, checked=True) for bundle in bundles]
        selected = checkbox_prompt(f"{action_label} bundles", choices)
        if selected is not None:
            return selected
    raw = Prompt.ask(f"{action_label} bundles by index (e.g. 1 2 3)", default="1")
    selected_paths: list[Path] = []
    for token in raw.replace(",", " ").split():
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(bundles):
                selected_paths.append(bundles[index])
    return list(dict.fromkeys(selected_paths))


def render_action_hub() -> None:
    commands = Table.grid(padding=(0, 3))
    hub_rows = [
        ("pack", "Create a new bundle with a guided wizard", "Crea un nuevo bundle con asistente guiado"),
        ("catalog", "Browse categorized config groups with found counts", "Explora grupos clasificados con recuento detectado"),
        ("presets", "Browse dotfile presets for macOS, Linux and Windows", "Explora presets de dotfiles para macOS, Linux y Windows"),
        ("inspect", "Open the bundle card and file summary", "Abre la ficha del bundle y el resumen de archivos"),
        ("apply", "Preview or restore a bundle into a target directory", "Previsualiza o restaura un bundle en un directorio destino"),
        ("diff", "Compare a bundle against a target directory", "Compara un bundle contra un directorio destino"),
        ("verify", "Validate bundle structure and integrity", "Valida estructura e integridad del bundle"),
        ("doctor", "Run local environment diagnostics", "Ejecuta diagnostico del entorno local"),
        ("share", "Export a bundle card as markdown or json", "Exporta la ficha del bundle como markdown o json"),
        ("manifest", "Show the raw manifest JSON", "Muestra el manifest JSON crudo"),
        ("history", "List stored snapshots for a bundle name", "Lista snapshots guardados de un bundle"),
        ("profile", "Manage reusable pack profiles", "Gestiona perfiles reutilizables"),
        ("settings", "Tune compression, workers and language defaults", "Ajusta compresion, workers e idioma por defecto"),
        ("keygen", "Create or inspect the active key", "Genera o inspecciona la clave activa"),
        ("rekey", "Generate a new key and migrate package payloads", "Genera una nueva clave y migra los payloads"),
        ("delete", "Delete local bundle files", "Elimina bundles locales"),
        ("quit", "Exit the command center", "Sale del command center"),
    ]
    colors = {"pack": "green", "catalog": "blue", "presets": "bright_green", "inspect": "cyan", "apply": "yellow", "diff": "yellow", "verify": "white", "doctor": "white", "share": "white", "manifest": "magenta", "history": "white", "profile": "white", "settings": "white", "keygen": "white", "rekey": "white", "delete": "red", "quit": "red"}
    for command, en_desc, es_desc in hub_rows:
        desc = en_desc if CURRENT_LANGUAGE == "en" else es_desc
        commands.add_row(f"[bold {colors[command]}]{command}[/bold {colors[command]}]", desc)
    console.print(Panel(commands, title=f"[bold bright_green]{tr('Centro de acciones')}[/bold bright_green]", border_style="green"))


def prompt_action_choice() -> str:
    actions = ["pack", "catalog", "presets", "inspect", "apply", "diff", "verify", "doctor", "share", "manifest", "history", "profile", "settings", "keygen", "rekey", "delete", "quit"]
    action_map = {str(index): action for index, action in enumerate(actions, start=1)}
    console.print(f"[dim]{tr('Atajos: 1=pack 2=catalog 3=presets 4=inspect 5=apply 6=diff 7=verify 8=doctor 9=share 10=manifest 11=history 12=profile 13=settings 14=keygen 15=rekey 16=delete 17=quit')}[/dim]")
    raw = Prompt.ask(
        tr("Elegir accion"),
        default="pack",
    ).strip().lower()
    if raw in action_map:
        return action_map[raw]
    if raw in actions:
        return raw
    die(f"Accion desconocida: {raw}")


def check_platform_compatibility(manifest: dict) -> tuple[bool, str]:
    bundle_platform = manifest["bundle"]["platform"]
    target_os = bundle_platform.get("os")
    target_arch = (bundle_platform.get("arch") or "").lower()
    current_os = normalize_os_name()
    current_arch = platform.machine().lower()

    if target_os and target_os != "any" and target_os != current_os:
        return False, f"El paquete es para {target_os} y esta maquina es {current_os}"
    if target_arch and target_arch != "any" and target_arch != current_arch:
        return False, f"El paquete es para {target_arch} y esta maquina es {current_arch}"
    return True, "Compatible con esta maquina"


def cmd_keygen(args) -> None:
    key = load_key(args.key, create=True)
    fingerprint = fingerprint_key(key)
    console.print(
        Panel(
            f"{tr('Clave disponible en')} [bold]{args.key}[/bold]\nFingerprint: [cyan]{fingerprint}[/cyan]",
            title=f"[bold bright_green]{tr('Llavero')}[/bold bright_green]",
            border_style="green",
        )
    )


def cmd_pack(args) -> None:
    if not getattr(args, "json", False):
        print_banner()
    args.exclude = normalize_excludes(getattr(args, "exclude", []))
    args.notes = getattr(args, "notes", "")
    args.after_steps = getattr(args, "after_steps", [])
    args.profile = getattr(args, "profile", "")
    args.yes = getattr(args, "yes", False)
    apply_settings_defaults(args)
    key = load_key(args.key, create=True)
    paths, output = prepare_pack_inputs(args)
    if not paths:
        die(tr("No hay rutas para empaquetar. Pasa rutas explicitas o prepara tu HOME."))

    scan_progress = None
    scan_task = None
    if not getattr(args, "json", False):
        scan_progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[progress.description]{task.description}"),
            TextColumn("{task.fields[file_count]} files"),
            TextColumn("[dim]{task.fields[current_path]}[/dim]"),
            TimeElapsedColumn(),
            console=console,
        )
        scan_progress.__enter__()
        scan_task = scan_progress.add_task(
            tr("Scanning files"),
            total=None,
            file_count=0,
            current_path="starting",
        )

        def update_scan(count: int, current_path: Path) -> None:
            scan_progress.update(
                scan_task,
                file_count=count,
                current_path=str(current_path)[:80],
            )

        entries = filter_entries(collect_files(paths, progress_callback=update_scan), args.exclude)
        scan_progress.update(scan_task, description=tr("Scanning files done"), current_path="")
        scan_progress.__exit__(None, None, None)
    if getattr(args, "json", False):
        entries = filter_entries(collect_files(paths), args.exclude)

    if not entries:
        die(tr("No se encontro ningun archivo exportable."))
    sensitive_entries = detect_sensitive_entries(entries)
    entries = filter_sensitive_entries(entries, sensitive_entries, args, is_tty=sys.stdin.isatty())
    if not entries:
        die(tr("No quedan archivos tras aplicar exclusiones y filtros de seguridad."))

    files_manifest: list[dict] = []
    history_snapshot = save_history_snapshot(output)
    args.sensitive_count = len(sensitive_entries)
    args.key_fingerprint = fingerprint_key(key)
    total_bytes = sum(entry.size for entry in entries)
    requested_jobs = args.jobs
    initial_jobs, preflight_reason = safe_pack_jobs(entries, args.jobs)
    args.jobs = initial_jobs
    if initial_jobs < requested_jobs and not getattr(args, "json", False):
        console.print(
            f"[yellow]{tr('Adaptive pack:')}[/yellow] {trf('reduciendo ventana inicial de {requested} a {initial} ({reason}). Puede volver a subir si la memoria acompana.', requested=requested_jobs, initial=initial_jobs, reason=preflight_reason)}"
        )

    ensure_parent(output)
    tmp_output = output.with_suffix(output.suffix + ".tmp")

    # Write payloads directly into the ZIP as they are produced.
    # This avoids writing encrypted payloads to disk first (big speed win on slow I/O).
    skipped_files: list[dict] = []

    with ZipFile(tmp_output, "w", compression=ZIP_STORED) as bundle:
        progress_ctx = None
        progress = None
        task = None
        if not getattr(args, "json", False):
            progress_ctx = Progress(
                SpinnerColumn(style="green"),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=30),
                TextColumn("{task.fields[file_count]}/{task.fields[file_total]} files"),
                TextColumn("[dim]{task.fields[worker_status]}[/dim]"),
                TextColumn("{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
            )
            progress = progress_ctx.__enter__()
            task = progress.add_task(
                "Packing",
                total=total_bytes or len(entries),
                file_count=0,
                file_total=len(entries),
                worker_status=f"active {initial_jobs}/{requested_jobs} | {preflight_reason}",
            )

        executor, executor_mode = create_pack_executor(requested_jobs)
        if executor_mode == "threads-fallback" and not getattr(args, "json", False):
            console.print(
                f"[yellow]{tr('Adaptive pack:')}[/yellow] {tr('Process pool no disponible en este sistema; usando threads.')}"  # noqa: E501
            )
        try:
            with executor:
                pending: dict = {}
                next_index = 1
                completed_files = 0

                def submit_one(index: int, entry: FileEntry) -> None:
                    payload_name = f"{index:04d}-{hashlib.sha256(entry.relative_path.encode('utf-8')).hexdigest()[:16]}.bin"
                    future = executor.submit(
                        build_payload_job,
                        str(entry.source),
                        entry.relative_path,
                        entry.mode,
                        payload_name,
                        key,
                        args.compression_level,
                    )
                    pending[future] = (entry, payload_name)

                inflight_limit = initial_jobs
                inflight_limit, pressure_label = adaptive_next_inflight_limit(inflight_limit, requested_jobs)
                while next_index <= len(entries) and len(pending) < inflight_limit:
                    submit_one(next_index, entries[next_index - 1])
                    next_index += 1

                while pending:
                    done, _ = wait(set(pending.keys()), return_when=FIRST_COMPLETED)
                    for future in done:
                        entry, payload_name = pending.pop(future)
                        try:
                            encrypted, record = future.result()
                        except Exception as exc:
                            record = {
                                "path": entry.relative_path,
                                "source": str(entry.source),
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                            encrypted = None

                        if encrypted is None:
                            skipped_files.append(record)
                            if not getattr(args, "json", False):
                                console.print(
                                    f"[yellow]Warning:[/yellow] skipped unreadable file: {record.get('path')} ({record.get('error')})"
                                )
                            continue

                        # Write payload directly into the bundle.
                        bundle.writestr(record["payload"], encrypted)

                        files_manifest.append(record)
                        completed_files += 1
                        if progress is not None and task is not None:
                            progress.update(
                                task,
                                advance=record["size"],
                                file_count=completed_files,
                                worker_status=f"active {inflight_limit}/{requested_jobs} | {pressure_label}",
                            )

                    previous_limit = inflight_limit
                    inflight_limit, pressure_label = adaptive_next_inflight_limit(inflight_limit, requested_jobs)
                    if inflight_limit != previous_limit:
                        if inflight_limit > previous_limit:
                            detail = trf(
                                "subiendo ventana activa {previous} -> {current} ({label}).",
                                previous=previous_limit,
                                current=inflight_limit,
                                label=pressure_label,
                            )
                        else:
                            detail = trf(
                                "bajando ventana activa {previous} -> {current} ({label}).",
                                previous=previous_limit,
                                current=inflight_limit,
                                label=pressure_label,
                            )
                        if not getattr(args, "json", False):
                            console.print(f"[dim]{tr('Adaptive pack:')}[/dim] {detail}")

                    while next_index <= len(entries) and len(pending) < inflight_limit:
                        submit_one(next_index, entries[next_index - 1])
                        next_index += 1
        finally:
            if progress_ctx is not None:
                progress_ctx.__exit__(None, None, None)

        files_manifest.sort(key=lambda item: item["path"])
        skipped_files.sort(key=lambda item: (item.get("path") or ""))
        manifest = build_manifest(args, files_manifest, [str(path) for path in paths])
        if skipped_files:
            manifest.setdefault("bundle", {})
            manifest["bundle"]["skipped_files"] = [
                {"path": item.get("path"), "error": item.get("error")}
                for item in skipped_files
            ]
        bundle.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            compress_type=ZIP_DEFLATED,
        )

    # Atomic-ish replace.
    tmp_output.replace(output)

    if getattr(args, "json", False):
        payload = {
            "output": str(output),
            "tmp_output": str(tmp_output),
            "files": len(entries),
            "skipped": len(skipped_files),
            "payload_bytes": int(total_bytes),
            "sensitive_files": int(len(sensitive_entries)),
            "key_fingerprint": str(args.key_fingerprint),
            "history_snapshot": str(history_snapshot) if history_snapshot else None,
            "manifest": manifest,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    render_bundle_card(manifest, output)
    if history_snapshot:
            console.print(f"[dim]{trf('Previous snapshot saved to {path}', path=history_snapshot)}[/dim]")
    console.print(f"[bold green]{trf('Created {output}', output=output)}[/bold green]")


def cmd_bench(args) -> None:
    """Micro-benchmark Peridot pack performance.

    This creates a synthetic dataset of N files and runs `pack` multiple times
    with different compression levels/jobs, reporting wall time and output size.
    """

    if not (args.json and not getattr(args, "out", None)):
        print_banner()

    runs = max(1, int(args.runs))
    file_count = max(1, int(args.files))
    size_kb = max(1, int(args.size_kb))

    # Parse compression levels like: "0,1,3,6".
    # Be strict but user-friendly: reject invalid tokens with a clear error
    # instead of an unhandled ValueError traceback.
    levels: list[int] = []
    seen_levels: set[int] = set()
    for raw in str(args.levels).split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            parsed = int(token)
        except ValueError:
            die(trf("Nivel de compresion invalido en --levels: '{value}'.", value=token))
        level = sanitize_compression_level(parsed)
        if level in seen_levels:
            continue
        seen_levels.add(level)
        levels.append(level)
    if not levels:
        levels = [DEFAULT_COMPRESSION_LEVEL]

    key = load_key(args.key, create=True)

    results: list[dict] = []

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Deterministic-ish payload to make runs comparable.
        block = (b"peridot" * 128)  # 768 bytes
        target_size = size_kb * 1024

        for i in range(file_count):
            content = (block * ((target_size // len(block)) + 1))[:target_size]
            (data_dir / f"file-{i:04d}.txt").write_bytes(content)

        # One run per config.
        for level in levels:
            for jobs in [int(args.jobs)]:
                for run_idx in range(runs):
                    out = root / f"bench-l{level}-j{jobs}-r{run_idx}.peridot"
                    t0 = datetime.now(timezone.utc)
                    start = datetime.now(timezone.utc).timestamp()

                    pack_args = SimpleNamespace(
                        key=args.key,
                        name=f"bench-l{level}-j{jobs}",
                        paths=[str(data_dir)],
                        output=out,
                        description="",
                        platform=normalize_os_name("linux"),
                        shell="bash",
                        arch=platform.machine().lower(),
                        tags=[],
                        preset="",
                        profile="",
                        exclude=[],
                        notes="",
                        after_steps=[],
                        compression_level=level,
                        jobs=jobs,
                        yes=True,
                        language=getattr(args, "language", None),
                    )

                    cmd_pack(pack_args)

                    end = datetime.now(timezone.utc).timestamp()
                    dt = end - start
                    results.append(
                        {
                            "level": level,
                            "jobs": jobs,
                            "run": run_idx,
                            "seconds": round(dt, 4),
                            "output_bytes": out.stat().st_size,
                            "started_at": t0.isoformat(),
                        }
                    )

    input_bytes = file_count * size_kb * 1024

    # Print a compact summary (unless in JSON-only mode).
    json_only = bool(args.json and not getattr(args, "out", None))
    if not json_only:
        console.print("\n[bold]" + tr("Bench results") + "[/bold]")
        for row in results:
            mb_s = (input_bytes / 1_000_000) / max(0.0001, float(row["seconds"]))
            ratio = float(row["output_bytes"]) / max(1.0, float(input_bytes))
            console.print(
                f"- level={row['level']} jobs={row['jobs']} run={row['run']} -> {row['seconds']}s | in={format_bytes(int(input_bytes))} | out={format_bytes(int(row['output_bytes']))} | {mb_s:.1f} MB/s | ratio={ratio:.2f}"
            )

    if args.json or getattr(args, "out", None):
        payload = {
            "input_bytes": input_bytes,
            "files": file_count,
            "size_kb": size_kb,
            "results": results,
        }
        rendered = json.dumps(payload, indent=2)
        if getattr(args, "out", None):
            out_path = Path(args.out).expanduser()
            ensure_parent(out_path)
            out_path.write_text(rendered + "\n", encoding="utf-8")
            console.print(f"[dim]Saved bench JSON to {out_path}[/dim]")
        if args.json:
            print(rendered)


def cmd_inspect(args) -> None:
    manifest = manifest_from_zip(args.package)

    if args.json:
        # Machine-friendly mode: emit JSON only.
        print_manifest_json(manifest)
        return

    print_banner()
    render_bundle_card(manifest, args.package)
    compatible, message = check_platform_compatibility(manifest)
    style = "green" if compatible else "yellow"
    console.print(Panel(message if CURRENT_LANGUAGE == "es" else tr(message), title=tr("Compatibility"), border_style=style))

    if args.files:
        render_file_table(manifest, limit=None if args.all else 20)


def backup_existing_file(source: Path, backup_dir: Path, home_target: Path) -> Path:
    """Back up an existing path inside the apply target.

    Notes:
    - We intentionally preserve symlinks (store them as symlinks in the backup dir)
      to avoid silently dereferencing them.
    """

    relative = source.relative_to(home_target)
    backup_path = backup_dir / relative
    ensure_parent(backup_path)

    if source.is_symlink():
        # Preserve the symlink itself, not the content of its target.
        link_target = os.readlink(source)
        if backup_path.exists() or backup_path.is_symlink():
            backup_path.unlink()
        os.symlink(link_target, backup_path)
        return backup_path

    shutil.copy2(source, backup_path)
    return backup_path


def restore_backup(backup_path: Path, target_path: Path) -> None:
    """Restore a backup created by backup_existing_file back to target_path."""
    ensure_parent(target_path)

    if backup_path.is_symlink():
        link_target = os.readlink(backup_path)
        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()
        os.symlink(link_target, target_path)
        return

    shutil.copy2(backup_path, target_path)


@dataclass
class ApplyChange:
    target_path: Path
    existed: bool
    backup_path: Path | None


def _apply_plan_for_manifest(manifest: dict, target_root: Path) -> list[dict]:
    plan: list[dict] = []
    for entry in manifest["files"]:
        path = entry["path"]
        target_path = target_root / path
        existed = target_path.exists()
        plan.append(
            {
                "path": path,
                "target": str(target_path),
                "action": "overwrite" if existed else "create",
                "existed": existed,
                "size": int(entry.get("size") or 0),
            }
        )
    return plan


def _apply_token_for_plan(
    *,
    package_path: Path,
    target_root: Path,
    plan: list[dict],
    ignore_platform: bool,
    verify_write: bool,
    transactional: bool,
    selected_paths: list[str],
) -> str:
    payload = {
        "package": str(package_path),
        "target": str(target_root),
        "ignore_platform": bool(ignore_platform),
        "verify": bool(verify_write),
        "transactional": bool(transactional),
        "select": list(selected_paths),
        "plan": plan,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cmd_apply(args) -> None:
    json_mode = bool(getattr(args, "json", False))

    if not json_mode:
        print_banner()

    manifest = manifest_from_zip(args.package)
    if not json_mode:
        render_bundle_card(manifest, args.package)

    compatible, message = check_platform_compatibility(manifest)
    if not compatible and not args.ignore_platform and not args.dry_run:
        die(message)

    if not json_mode:
        if not compatible:
            console.print(
                f"[yellow]{'Warning' if CURRENT_LANGUAGE == 'en' else 'Aviso'}:[/yellow] {message if CURRENT_LANGUAGE == 'es' else tr(message)}"
            )
        else:
            console.print(f"[green]{message if CURRENT_LANGUAGE == 'es' else tr(message)}[/green]")

    selected_paths = set(args.select or [])
    if not json_mode and (not selected_paths and sys.stdin.isatty() and not args.yes and QUESTIONARY_AVAILABLE):
        if Confirm.ask(
            "Select only some bundle paths?" if CURRENT_LANGUAGE == "es" else "Select only some bundle paths?",
            default=False,
        ):
            choices = [Choice(title=entry["path"], value=entry["path"], checked=True) for entry in manifest["files"]]
            chosen = checkbox_prompt("Bundle paths to apply", choices)
            if chosen is not None:
                selected_paths = set(chosen)

    filtered_manifest = {
        **manifest,
        "files": [entry for entry in manifest["files"] if not selected_paths or entry["path"] in selected_paths],
    }

    target_root = args.target.expanduser()
    transactional = getattr(args, "transactional", True)
    verify_write = getattr(args, "verify", True)

    plan = _apply_plan_for_manifest(filtered_manifest, target_root)
    apply_token = _apply_token_for_plan(
        package_path=args.package,
        target_root=target_root,
        plan=plan,
        ignore_platform=bool(args.ignore_platform),
        verify_write=bool(verify_write),
        transactional=bool(transactional),
        selected_paths=sorted(selected_paths),
    )

    if args.dry_run:
        if json_mode:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dry_run": True,
                        "compatible": bool(compatible),
                        "compatibility_message": message,
                        "plan": plan,
                        "apply_token": apply_token,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        render_file_table(filtered_manifest, limit=None)
        diff_rows = bundle_diff(
            filtered_manifest,
            target_root,
            key=load_key(args.key, create=False),
            package_path=args.package,
        )
        render_diff_table(diff_rows)
        console.print(f"[bold cyan]{tr('Dry run: no se ha escrito nada.')}[/bold cyan]")
        hint = tr("Tip: para automatizar (MCP), ejecuta 'apply --dry-run --json' para obtener un apply_token.")
        console.print(f"[dim]{hint}[/dim]")
        return

    # In JSON mode (used by MCP), require the safety token.
    if json_mode and not str(getattr(args, "apply_token", "") or ""):
        die("Missing --apply-token. Run apply --dry-run --json first to obtain it.")
    if json_mode and str(args.apply_token) != apply_token:
        die("apply token mismatch. Re-run --dry-run --json to obtain a fresh token.")

    if not json_mode and not args.yes and sys.stdin.isatty():
        if not Confirm.ask(tr("Apply this bundle?"), default=False):
            console.print(f"[yellow]{tr('Operacion cancelada.')}[/yellow]")
            return

    key = load_key(args.key, create=False)
    backup_dir = args.backup_dir.expanduser() if args.backup_dir else None

    overwritten = 0
    restored = 0
    rollback_performed = False
    rollback_reason = ""
    changes: list[ApplyChange] = []

    def rollback(reason: str) -> None:
        nonlocal rollback_performed, rollback_reason
        rollback_performed = True
        rollback_reason = reason
        if not changes:
            return
        if not json_mode:
            console.print(f"[yellow]{'Aviso' if CURRENT_LANGUAGE == 'es' else 'Warning'}:[/yellow] rollback: {reason}")
        # Reverse order: last write first.
        for change in reversed(changes):
            try:
                if change.existed and change.backup_path and change.backup_path.exists():
                    restore_backup(change.backup_path, change.target_path)
                elif not change.existed:
                    if change.target_path.exists():
                        change.target_path.unlink()
            except Exception:
                # Best effort rollback.
                pass

    total_bytes = sum(entry["size"] for entry in filtered_manifest["files"])

    # If transactional and user didn't request backups, use a temporary backup dir.
    temp_backup_ctx = TemporaryDirectory() if transactional and not backup_dir else None
    try:
        if temp_backup_ctx is not None:
            backup_dir = Path(temp_backup_ctx.name)

        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)

        with ZipFile(args.package) as bundle:
            progress_ctx = None
            progress = None
            task = None
            if not json_mode:
                progress_ctx = Progress(
                    SpinnerColumn(style="green"),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(bar_width=30),
                    TextColumn("{task.fields[file_count]}/{task.fields[file_total]} files"),
                    TextColumn("{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    TimeRemainingColumn(),
                    console=console,
                )
                progress = progress_ctx.__enter__()
                task = progress.add_task(
                    "Applying",
                    total=total_bytes or len(filtered_manifest["files"]),
                    file_count=0,
                    file_total=len(filtered_manifest["files"]),
                )

            for file_entry in filtered_manifest["files"]:
                    target_path = target_root / file_entry["path"]
                    ensure_parent(target_path)

                    existed = target_path.exists()
                    backup_path = None
                    if existed and backup_dir:
                        backup_path = backup_existing_file(target_path, backup_dir, target_root)
                        overwritten += 1

                    # Track this change so we can rollback on failure.
                    changes.append(ApplyChange(target_path=target_path, existed=existed, backup_path=backup_path))

                    # Safety: never write through a pre-existing symlink (would clobber its target).
                    if existed and target_path.is_symlink():
                        target_path.unlink()

                    try:
                        encrypted = bundle.read(file_entry["payload"])
                        payload = decrypt_payload(encrypted, file_entry, key)
                        raw = inflate_payload(payload, file_entry.get("compression"))
                    except ValueError:
                        if transactional:
                            rollback(tr("La clave no coincide con el paquete."))
                        die(tr("La clave no coincide con el paquete."))

                    try:
                        target_path.write_bytes(raw)
                    except Exception as exc:
                        if transactional:
                            rollback(f"write failed: {exc}")
                        raise

                    if verify_write:
                        try:
                            written = target_path.read_bytes()
                        except Exception as exc:
                            if transactional:
                                rollback(f"verify read failed: {exc}")
                            raise
                        if hashlib.sha256(written).hexdigest() != file_entry["sha256"]:
                            msg = f"Hash mismatch after write: {file_entry['path']}"
                            if transactional:
                                rollback(msg)
                            die(msg)

                    try:
                        target_path.chmod(file_entry["mode"])
                    except OSError:
                        pass
                    restored += 1
                    if progress is not None and task is not None:
                        progress.update(task, advance=file_entry["size"], file_count=restored)

    except Exception as exc:
        if transactional:
            rollback(f"exception: {exc}")
        raise
    finally:
        if progress_ctx is not None:
            progress_ctx.__exit__(None, None, None)
        if temp_backup_ctx is not None:
            temp_backup_ctx.cleanup()

    post_apply = manifest["bundle"].get("post_apply") or []

    if json_mode:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": False,
                    "target": str(target_root),
                    "restored": int(restored),
                    "overwritten": int(overwritten),
                    "backup_dir": str(backup_dir) if backup_dir else None,
                    "transactional": bool(transactional),
                    "verify": bool(verify_write),
                    "rollback_performed": bool(rollback_performed),
                    "rollback_reason": rollback_reason or None,
                    "post_apply": list(post_apply),
                    "apply_token": apply_token,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    footer = Table.grid(padding=(0, 2))
    footer.add_row("Target", str(target_root))
    footer.add_row("Restored", str(restored))
    footer.add_row("Backups", str(overwritten if backup_dir else 0))
    if backup_dir:
        footer.add_row("Backup dir", str(backup_dir))
    if post_apply:
        footer.add_row("Post apply", str(len(post_apply)))
    console.print(Panel(footer, title=f"[bold bright_green]{tr('Apply Summary')}[/bold bright_green]", border_style="green"))
    if post_apply:
        console.print(f"[bold cyan]{tr('Post-apply checklist')}[/bold cyan]")
        for step in post_apply:
            console.print(f"- {step}")


def cmd_diff(args) -> None:
    if not getattr(args, "json", False):
        print_banner()
    manifest = manifest_from_zip(args.package)
    key = None
    if not args.no_hash:
        key = load_key(args.key, create=False)
    rows = bundle_diff(manifest, args.target.expanduser(), key=key, package_path=args.package if key else None)
    if getattr(args, "json", False):
        print(json.dumps([{"status": status, "path": path} for status, path in rows], indent=2))
        return
    render_diff_table(rows)


def cmd_verify(args) -> None:
    manifest = manifest_from_zip(args.package)
    issues: list[str] = []
    try:
        with ZipFile(args.package) as bundle:
            for file_entry in manifest["files"]:
                if file_entry["payload"] not in bundle.namelist():
                    issues.append(f"Missing payload: {file_entry['payload']}")
    except OSError as exc:
        issues.append(str(exc))

    if args.deep:
        key = load_key(args.key, create=False)
        try:
            contents = read_bundle_content(args.package, manifest, key)
            for file_entry in manifest["files"]:
                payload = contents[file_entry["path"]]
                if hashlib.sha256(payload).hexdigest() != file_entry["sha256"]:
                    issues.append(f"Hash mismatch: {file_entry['path']}")
        except ValueError:
            issues.append("La clave no coincide con el paquete.")

    result = {"ok": not issues, "issues": issues}
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        if issues:
            raise SystemExit(1)
        return
    if issues:
        console.print(f"[bold red]{tr('Verificacion fallida')}[/bold red]")
        for issue in issues:
            console.print(f"- {issue}")
        raise SystemExit(1)
    console.print(f"[bold green]{tr('Verificacion OK')}[/bold green]")


def render_settings_table(settings: dict) -> None:
    table = Table(title=tr("Settings"), header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Value")
    table.add_column("Detail")
    compression_level = sanitize_compression_level(settings.get("compression_level"))
    jobs = sanitize_jobs(settings.get("jobs"))
    language = sanitize_language(settings.get("language"))
    table.add_row(
        "compression_level",
        f"{compression_level}/9",
        f"{render_level_bar(compression_level)} {active_compression_codec()} | {tr(compression_profile_detail(compression_level))}",
    )
    table.add_row("jobs", str(jobs), tr("workers para pack; mas puede ir mas rapido si hay CPU libre"))
    table.add_row("encryption", ENCRYPTION_ALGORITHM, tr("cifrado fijo: rapido, moderno y estandar"))
    table.add_row("language", language, tr("preparado para internacionalizacion CLI"))
    console.print(table)
    console.print(render_compression_setting(compression_level))


def interactive_settings_editor(settings_path: Path | None = None) -> dict:
    settings_path = settings_path or default_settings_store()
    settings = load_settings(settings_path)
    print_banner()
    render_settings_table(settings)
    console.print(f"[dim]{tr('Compression: 0 = mas rapido y mas grande, 9 = mas lento y mas pequeno.')}[/dim]")
    raw_level = Prompt.ask(tr("Compression level"), default=str(settings["compression_level"]))
    settings["compression_level"] = sanitize_compression_level(raw_level)
    console.print(render_compression_setting(settings["compression_level"]))
    cpu_total = os.cpu_count() or DEFAULT_JOBS
    raw_jobs = Prompt.ask(tr("Pack workers"), default=str(settings["jobs"]))
    settings["jobs"] = sanitize_jobs(raw_jobs)
    console.print(f"[dim]{trf('CPU detectada: {cpu} | workers activos: {jobs}', cpu=cpu_total, jobs=settings['jobs'])}[/dim]")
    settings["language"] = sanitize_language(
        Prompt.ask(
            tr("Language"),
            choices=["es", "en"],
            default=effective_language_from_setting(settings["language"]),
        )
    )
    if not Confirm.ask(tr("Save settings?"), default=True):
        console.print(f"[yellow]{tr('Operacion cancelada.')}[/yellow]")
        return load_settings(settings_path)
    save_settings(settings, settings_path)
    set_current_language(settings["language"])
    console.print(f"[bold green]{trf('Settings saved {path}', path=settings_path)}[/bold green]")
    return settings


def cmd_settings(args) -> None:
    settings_path = getattr(args, "settings_path", None) or default_settings_store()
    json_mode = bool(getattr(args, "json", False))

    if getattr(args, "set", []):
        settings = load_settings(settings_path)
        for item in args.set:
            if "=" not in item:
                die(f"Formato invalido en setting '{item}'. Usa clave=valor.")
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "compression_level":
                settings[key] = sanitize_compression_level(value)
            elif key == "jobs":
                settings[key] = sanitize_jobs(value)
            elif key == "language":
                settings[key] = sanitize_language_setting(value)
            else:
                die(f"Setting no soportado: {key}")
        save_settings(settings, settings_path)
        set_current_language(effective_language_from_setting(settings["language"]))

        if json_mode:
            print(json.dumps({"settings_path": str(settings_path), "settings": settings}, indent=2, sort_keys=True))
            return

        render_settings_table(settings)
        console.print(f"[bold green]{trf('Settings updated {path}', path=settings_path)}[/bold green]")
        return

    # In JSON mode, default to showing the effective settings.
    if json_mode:
        settings = load_settings(settings_path)
        print(json.dumps({"settings_path": str(settings_path), "settings": settings}, indent=2, sort_keys=True))
        return

    if getattr(args, "show", False):
        render_settings_table(load_settings(settings_path))
        return

    interactive_settings_editor(settings_path)


def cmd_init(args) -> None:
    """Initialize Peridot local state (key + settings) with sane defaults."""

    json_mode = bool(getattr(args, "json", False))

    if not json_mode:
        print_banner()

    key_path: Path = getattr(args, "key", default_key_path())
    settings_path: Path = default_settings_store()

    # Ensure key exists.
    key = load_key(key_path, create=True)

    # Ensure settings exist (or overwrite with --force).
    created_settings = False
    if settings_path.exists() and not getattr(args, "force", False):
        settings = load_settings(settings_path)
        if not json_mode:
            console.print(f"[dim]Settings already exist at {settings_path}[/dim]")
    else:
        ensure_parent(settings_path)
        save_settings({**DEFAULT_SETTINGS}, settings_path)
        settings = load_settings(settings_path)
        created_settings = True
        if not json_mode:
            console.print(f"[green]Created settings at {settings_path}[/green]")

    payload = {
        "key_path": str(key_path),
        "fingerprint": fingerprint_key(key),
        "settings_path": str(settings_path),
        "created_settings": created_settings,
        "language": settings.get("language"),
        "compression_level": settings.get("compression_level"),
        "compression_codec": active_compression_codec(),
        "jobs": settings.get("jobs"),
    }

    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    footer = Table.grid(padding=(0, 2))
    footer.add_row("Key", payload["key_path"])
    footer.add_row("Fingerprint", payload["fingerprint"])
    footer.add_row("Settings", payload["settings_path"])
    footer.add_row("Language", str(payload["language"]))
    footer.add_row("Compression", f"{payload['compression_level']}/9 ({payload['compression_codec']})")
    footer.add_row("Jobs", str(payload["jobs"]))

    console.print(Panel(footer, title=tr("Peridot initialized"), border_style="green"))

    console.print("\n" + tr("Next steps") + ":")
    console.print("- peridot pack --help")
    console.print("- peridot ui")
    console.print("- peridot bench --files 200 --size-kb 4 --levels 0,1,3 --runs 1")


def cmd_doctor(args) -> None:
    rows = []
    rows.append(("key", "ok" if args.key.exists() else "missing", str(args.key)))
    bundles = discover_local_bundles()
    rows.append(("bundles", "ok" if bundles else "empty", str(len(bundles))))
    profiles_store = default_profile_store()
    rows.append(("profiles", "ok" if profiles_store.exists() else "empty", str(profiles_store)))
    settings = load_settings()
    settings_store = default_settings_store()
    rows.append(("settings", "ok" if settings_store.exists() else "default", str(settings_store)))
    rows.append(("compression_level", "ok", f"{settings['compression_level']}/9"))
    rows.append(("compression_codec", "ok" if zstd is not None else "warn", active_compression_codec()))
    if zstd is None:
        rows.append(("zstd", "warn", "zstandard not installed; using gzip fallback"))
    else:
        zstd_version = getattr(zstd, "__version__", "unknown")
        rows.append(("zstd", "ok", f"zstandard {zstd_version}"))
    rows.append(("jobs", "ok", str(settings["jobs"])))
    rows.append(("encryption", "ok", ENCRYPTION_ALGORITHM))
    rows.append(("language", "ok", settings["language"]))
    total_mem = total_memory_bytes()
    avail_mem = available_memory_bytes()
    pressure = memory_pressure_ratio()
    if total_mem:
        rows.append(("memory_total", "ok", format_bytes(total_mem)))
    if avail_mem:
        rows.append(("memory_available", "ok" if avail_mem > 512 * 1024 * 1024 else "warn", format_bytes(avail_mem)))
    if pressure is None:
        rows.append(("memory_pressure", "warn", "no se pudo calcular"))
    else:
        if pressure < 0.60:
            status = "ok"
            detail = f"{pressure * 100:.0f}% (cool)"
        elif pressure < 0.72:
            status = "ok"
            detail = f"{pressure * 100:.0f}% (normal)"
        elif pressure < 0.84:
            status = "warn"
            detail = f"{pressure * 100:.0f}% (warm)"
        elif pressure < 0.92:
            status = "high"
            detail = f"{pressure * 100:.0f}% (high)"
        else:
            status = "high"
            detail = f"{pressure * 100:.0f}% (critical)"
        rows.append(("memory_pressure", status, detail))
    path_ok = any(str(Path.home() / ".local" / "bin") == part for part in os.environ.get("PATH", "").split(os.pathsep))
    rows.append(("path", "ok" if path_ok else "warn", "~/.local/bin in PATH" if path_ok else "~/.local/bin not in PATH"))
    checkbox_reason = checkbox_unavailable_reason()
    if checkbox_reason is None:
        rows.append(("checkbox_ui", "ok", "questionary + tty available"))
    elif checkbox_reason == "missing_questionary":
        rows.append(("checkbox_ui", "warn", "missing questionary in current Python"))
    else:
        rows.append(("checkbox_ui", "warn", "no interactive tty"))
    if getattr(args, "json", False):
        print(json.dumps([{"check": name, "status": status, "detail": detail} for name, status, detail in rows], indent=2))
        return
    table = Table(title=tr("Doctor"), header_style="bold cyan")
    table.add_column(tr("Check"))
    table.add_column(tr("Status"))
    table.add_column(tr("Detail"))
    for name, status, detail in rows:
        style = {"ok": "green", "missing": "red", "warn": "yellow", "high": "red", "empty": "yellow"}.get(status, "white")
        table.add_row(name, f"[{style}]{status}[/{style}]", detail)
    console.print(table)


def cmd_version(args) -> None:
    payload = {
        "app": "peridot",
        "version": APP_VERSION,
        "python_executable": str(getattr(sys, "executable", "") or ""),
        "python_version": platform.python_version(),
        "rich_available": bool(RICH_AVAILABLE),
        "cryptography_available": AESGCM is not None,
        "zstd_available": zstd is not None,
        "os": normalize_os_name(),
        "platform": platform.platform(),
    }

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(f"peridot {APP_VERSION}")
    if payload["python_executable"]:
        print(f"Python: {payload['python_executable']} ({payload['python_version']})")
    else:
        print(f"Python: {payload['python_version']}")
    print(f"Rich: {'yes' if payload['rich_available'] else 'no'}")
    print(f"Cryptography: {'yes' if payload['cryptography_available'] else 'no'}")
    print(f"zstandard: {'yes' if payload['zstd_available'] else 'no'}")
    print(f"OS: {payload['os']}")


def cmd_share(args) -> None:
    manifest = manifest_from_zip(args.package)
    bundle = manifest["bundle"]
    if args.format == "json":
        output = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    elif args.format == "md":
        lines = [
            f"# {bundle['name']}",
            "",
            bundle.get("description") or "",
            "",
            f"- Target: {bundle['platform']['os']} / {bundle['platform'].get('shell') or 'any'} / {bundle['platform'].get('arch') or 'any'}",
            f"- Files: {bundle['stats']['files']}",
            f"- Payload: {format_bytes(bundle['stats']['bytes'])}",
            "",
            "## Files",
        ]
        lines.extend(f"- `{entry['path']}`" for entry in manifest["files"])
        output = "\n".join(lines) + "\n"
    else:
        die("Formato no soportado en modo 100% CLI. Usa json o md.")

    if args.output:
        args.output.write_text(output)
        console.print(f"[bold green]Exported[/bold green] {args.output}")
    else:
        print(output, end="")


def cmd_history(args) -> None:
    history_root = default_history_dir() / args.bundle

    snapshots: list[dict[str, object]] = []
    if history_root.exists():
        for snapshot in sorted(history_root.glob("*.peridot")):
            stat = snapshot.stat()
            snapshots.append(
                {
                    "name": snapshot.name,
                    "path": str(snapshot),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "bundle": args.bundle,
                    "history_root": str(history_root),
                    "snapshots": snapshots,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    table = Table(title=tr("History"), header_style="bold cyan")
    table.add_column("Snapshot")
    table.add_column("Size", justify="right")
    if snapshots:
        for entry in snapshots:
            table.add_row(str(entry["name"]), format_bytes(int(entry["size_bytes"])))
    else:
        table.add_row("No snapshots", "-")
    console.print(table)


def cmd_merge(args) -> None:
    key = load_key(args.key, create=False)
    merged_files: dict[str, dict] = {}
    bundle_name = args.name or "merged-bundle"
    notes = []
    for package in args.packages:
        manifest = manifest_from_zip(package)
        notes.append(f"merged from {package.name}")
        for file_entry in manifest["files"]:
            raw = decode_package_payload(package, file_entry, key)
            merged_files[file_entry["path"]] = {
                "raw": raw,
                "mode": file_entry["mode"],
            }
    if not merged_files:
        die("No hay archivos para fusionar.")
    write_bundle_from_raw(
        output=args.output,
        bundle_name=bundle_name,
        description=args.description or "Merged bundle",
        platform=args.platform or normalize_os_name(),
        shell=args.shell or detect_shell(),
        arch=args.arch or platform.machine().lower(),
        tags=normalize_tags(args.tags),
        notes="\n".join(notes),
        after_steps=[],
        files=merged_files,
        key=key,
    )


def cmd_split(args) -> None:
    key = load_key(args.key, create=False)
    manifest = manifest_from_zip(args.package)
    selected = [entry for entry in manifest["files"] if any(entry["path"].startswith(prefix) for prefix in args.prefix)]
    if not selected:
        die("No se ha seleccionado ningun archivo para extraer.")
    files: dict[str, dict] = {}
    for file_entry in selected:
        files[file_entry["path"]] = {
            "raw": decode_package_payload(args.package, file_entry, key),
            "mode": file_entry["mode"],
        }
    write_bundle_from_raw(
        output=args.output,
        bundle_name=args.name or f"{manifest['bundle']['name']} split",
        description=args.description or "Split bundle",
        platform=manifest["bundle"]["platform"]["os"],
        shell=manifest["bundle"]["platform"].get("shell") or "",
        arch=manifest["bundle"]["platform"].get("arch") or "",
        tags=manifest["bundle"].get("tags") or [],
        notes=manifest["bundle"].get("notes") or "",
        after_steps=manifest["bundle"].get("post_apply") or [],
        files=files,
        key=key,
    )


def cmd_profile_save(args) -> None:
    profiles = load_profiles()
    profiles[args.name] = {
        "name": args.bundle_name,
        "description": args.description,
        "platform": args.platform,
        "shell": args.shell,
        "arch": args.arch,
        "tags": normalize_tags(args.tags),
        "preset": args.preset,
        "paths": args.paths,
        "exclude": args.exclude,
        "notes": args.notes,
        "after_steps": args.after_steps,
    }
    save_profiles(profiles)
    console.print(f"[bold green]{trf('Profile saved {name}', name=args.name)}[/bold green]")


def cmd_profile_list(args) -> None:
    profiles = load_profiles()
    table = Table(title=tr("Profiles"), header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Target")
    table.add_column("Preset")
    for name, profile in sorted(profiles.items()):
        table.add_row(name, f"{profile.get('platform') or 'any'} / {profile.get('shell') or 'any'}", profile.get("preset") or "-")
    if not profiles:
        table.add_row("No profiles", "-", "-")
    console.print(table)


def cmd_profile_show(args) -> None:
    profiles = load_profiles()
    profile = profiles.get(args.name)
    if not profile:
        die(f"No existe el perfil '{args.name}'")
    console.print_json(data=profile)


def cmd_profile_delete(args) -> None:
    profiles = load_profiles()
    if args.name not in profiles:
        die(f"No existe el perfil '{args.name}'")
    del profiles[args.name]
    save_profiles(profiles)
    console.print(f"[bold green]{trf('Profile deleted {name}', name=args.name)}[/bold green]")


def resolve_package_list(package_inputs: list[str] | None, use_local: bool = False) -> list[Path]:
    packages: list[Path] = []
    seen: set[Path] = set()
    if use_local:
        for bundle in discover_local_bundles():
            if bundle not in seen:
                seen.add(bundle)
                packages.append(bundle)
    for package_input in package_inputs or []:
        candidate = Path(package_input).expanduser()
        if package_input.isdigit():
            bundles = discover_local_bundles()
            index = int(package_input) - 1
            if 0 <= index < len(bundles):
                candidate = bundles[index]
        if candidate not in seen:
            seen.add(candidate)
            packages.append(candidate)
    return packages


def reencrypt_package(package_path: Path, old_key: bytes, new_key: bytes) -> None:
    temp_path = package_path.with_suffix(package_path.suffix + ".tmp")
    with ZipFile(package_path) as source_zip:
        manifest = json.loads(source_zip.read("manifest.json"))
        with ZipFile(temp_path, "w", compression=ZIP_STORED) as target_zip:
            for file_entry in manifest["files"]:
                encrypted = source_zip.read(file_entry["payload"])
                payload = decrypt_payload(encrypted, file_entry, old_key)
                nonce = os.urandom(12)
                AESGCM_impl, _InvalidTag = require_cryptography()
                reencrypted = AESGCM_impl(new_key).encrypt(nonce, payload, None)
                file_entry["encryption"] = {"algorithm": ENCRYPTION_ALGORITHM, "nonce": nonce.hex()}
                target_zip.writestr(file_entry["payload"], reencrypted)
            target_zip.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n", compress_type=ZIP_DEFLATED)
    temp_path.replace(package_path)


def cmd_delete(args) -> None:
    packages = resolve_package_list(args.packages, use_local=args.all_local)
    if not packages:
        die("No hay paquetes para eliminar.")
    if not args.yes and sys.stdin.isatty():
        render_local_bundle_table()
        if not Confirm.ask(f"Delete {len(packages)} package(s)?", default=False):
            console.print(f"[yellow]{tr('Operacion cancelada.')}[/yellow]")
            return
    deleted = 0
    for package in packages:
        if package.exists():
            package.unlink()
            deleted += 1
    console.print(f"[bold green]{trf('Deleted {count} package(s)', count=deleted)}[/bold green]")


def cmd_rekey(args) -> None:
    packages = resolve_package_list(args.packages, use_local=args.all_local)
    if not packages:
        die("No hay paquetes para migrar. Pasa paquetes o usa --all-local.")

    old_key = load_key(args.key, create=False)
    AESGCM_impl, _InvalidTag = require_cryptography()
    new_key = AESGCM_impl.generate_key(bit_length=256)
    backup_key_path = args.key.with_suffix(args.key.suffix + ".bak")

    if not args.yes and sys.stdin.isatty():
        render_local_bundle_table()
        if not Confirm.ask(f"Re-encrypt {len(packages)} package(s) with a new key?", default=False):
            console.print(f"[yellow]{tr('Operacion cancelada.')}[/yellow]")
            return

    migrated = 0
    with Progress(
        SpinnerColumn(style="green"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Rekeying", total=len(packages))
        for package in packages:
            reencrypt_package(package, old_key, new_key)
            migrated += 1
            progress.advance(task)

    if not args.no_backup:
        write_key(backup_key_path, old_key)
    write_key(args.key, new_key)

    table = Table.grid(padding=(0, 2))
    table.add_row("Packages", str(migrated))
    table.add_row("New key", str(args.key))
    table.add_row("Backup key", str(backup_key_path if not args.no_backup else "disabled"))
    console.print(Panel(table, title=f"[bold bright_green]{tr('Rekey Summary')}[/bold bright_green]", border_style="green"))


def cmd_manifest(args) -> None:
    manifest = manifest_from_zip(args.package)
    print_manifest_json(manifest)


def cmd_catalog(args) -> None:
    print_banner()
    os_name = normalize_os_name(args.platform or normalize_os_name())
    shell_name = args.shell or detect_shell()
    groups = config_groups_for_os(os_name)
    render_config_group_table(groups, recommended_group_keys(groups, shell_name), marker_label="Default")
    catalog_hint = "'x' marca los grupos recomendados por defecto para esta plataforma/shell. No significa que ya vayan dentro de ningun bundle."
    console.print(f"[dim]{tr(catalog_hint)}[/dim]")


def cmd_ui(args) -> None:
    while True:
        console.clear()
        print_banner()
        render_local_bundle_table()
        render_action_hub()
        action = prompt_action_choice()
        skip_return_prompt = False

        try:
            if action == "quit":
                console.print(f"[dim]{tr('Leaving Peridot UI.')}[/dim]")
                return
            if action == "catalog":
                cmd_catalog(SimpleNamespace(platform="", shell=""))
            if action == "presets":
                render_presets_table()
            elif action == "pack":
                cmd_pack(
                    SimpleNamespace(
                        key=args.key,
                        name=None,
                        paths=[],
                        output=None,
                        description="",
                        platform="",
                        shell="",
                        arch="",
                        tags=[],
                        preset="",
                        profile="",
                        exclude=[],
                        notes="",
                        after_steps=[],
                        compression_level=None,
                        jobs=None,
                        language=None,
                        yes=False,
                    )
                )
            elif action == "inspect":
                package = choose_bundle_path(tr("Inspeccionar"))
                show_files = Confirm.ask(tr("Mostrar lista de ficheros?"), default=True)
                show_json = Confirm.ask(tr("Mostrar manifest JSON?"), default=False)
                cmd_inspect(SimpleNamespace(package=package, files=show_files, all=True, json=show_json))
            elif action == "apply":
                package = choose_bundle_path(tr("Aplicar"))
                dry_run = Confirm.ask(tr("Hacer dry-run primero?"), default=True)
                target = Path(Prompt.ask(tr("Directorio destino"), default=str(Path.home()))).expanduser()
                backup_enabled = Confirm.ask(tr("Guardar backups antes de sobrescribir?"), default=True)
                backup_dir = None
                if backup_enabled:
                    backup_dir = Path(
                        Prompt.ask(
                            tr("Directorio de backups"),
                            default=str(Path.home() / ".peridot-backups"),
                        )
                    ).expanduser()
                ignore_platform = Confirm.ask(tr("Ignorar mismatch de plataforma?"), default=False)
                cmd_apply(
                    SimpleNamespace(
                        package=package,
                        target=target,
                        backup_dir=backup_dir,
                        dry_run=dry_run,
                        ignore_platform=ignore_platform,
                        yes=True,
                        key=args.key,
                    )
                )
            elif action == "diff":
                package = choose_bundle_path(tr("Diff"))
                target = Path(Prompt.ask(tr("Directorio destino"), default=str(Path.home()))).expanduser()
                cmd_diff(SimpleNamespace(package=package, target=target, no_hash=False, json=False, key=args.key))
            elif action == "verify":
                package = choose_bundle_path(tr("Verificar"))
                deep = Confirm.ask(tr("Verificacion profunda (descifrar)?"), default=True)
                cmd_verify(SimpleNamespace(package=package, deep=deep, json=False, key=args.key))
            elif action == "doctor":
                cmd_doctor(SimpleNamespace(key=args.key, json=False))
            elif action == "share":
                package = choose_bundle_path(tr("Compartir"))
                fmt = Prompt.ask(tr("Formato"), choices=["md", "json"], default="md")
                output_raw = Prompt.ask(tr("Fichero de salida (vacio = imprimir)"), default="")
                output = Path(output_raw).expanduser() if output_raw else None
                cmd_share(SimpleNamespace(package=package, format=fmt, output=output))
            elif action == "manifest":
                package = choose_bundle_path("Manifest")
                cmd_manifest(SimpleNamespace(package=package))
            elif action == "history":
                bundle_name = Prompt.ask(tr("Nombre del bundle"), default=(discover_local_bundles()[0].stem if discover_local_bundles() else "bundle"))
                cmd_history(SimpleNamespace(bundle=bundle_name))
            elif action == "profile":
                profile_action = Prompt.ask(tr("Accion de perfil"), choices=["list", "show", "delete"], default="list")
                if profile_action == "list":
                    cmd_profile_list(SimpleNamespace())
                elif profile_action == "show":
                    name = Prompt.ask(tr("Nombre del perfil"))
                    cmd_profile_show(SimpleNamespace(name=name))
                else:
                    name = Prompt.ask(tr("Nombre del perfil"))
                    cmd_profile_delete(SimpleNamespace(name=name))
            elif action == "settings":
                cmd_settings(SimpleNamespace(settings_path=DEFAULT_SETTINGS_STORE, show=False, set=[]))
                skip_return_prompt = True
            elif action == "keygen":
                cmd_keygen(SimpleNamespace(key=args.key))
            elif action == "rekey":
                all_local = Confirm.ask(tr("Rekey todos los bundles locales?"), default=True)
                packages = [] if all_local else [str(path) for path in choose_bundle_paths(tr("Rekey"))]
                cmd_rekey(SimpleNamespace(key=args.key, packages=packages, all_local=all_local, no_backup=False, yes=True))
            elif action == "delete":
                all_local = Confirm.ask(tr("Borrar todos los bundles locales?"), default=False)
                packages = [] if all_local else [str(path) for path in choose_bundle_paths(tr("Borrar"))]
                cmd_delete(SimpleNamespace(packages=packages, all_local=all_local, yes=True))
        except SystemExit:
            pass

        if skip_return_prompt:
            continue
        Prompt.ask(tr("Press enter to return to the command center"), default="")


def cmd_self_update(args) -> None:
    """Update peridot-cli via pip using the current interpreter.

    This command is opt-in and requires confirmation unless --yes is passed.
    """

    if not getattr(args, "yes", False) and sys.stdin.isatty():
        prompt = tr("Actualizar peridot-cli a la ultima version? [y/N] ")
        ans = input(prompt).strip().lower()
        if ans not in {"y", "yes", "s", "si", "sí"}:
            return

    cmd = [sys.executable, "-m", "pip", "install", "-U", "peridot-cli"]
    try:
        subprocess.check_call(cmd)
    except FileNotFoundError:
        die(tr("No se encontro pip en este Python. Instala pip o usa tu gestor de paquetes."))
    except subprocess.CalledProcessError as exc:
        die(trf("Fallo al actualizar peridot-cli (exit={code}).", code=exc.returncode))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peridot",
        description=tr("Empaqueta, inspecciona y aplica bundles de configuracion .peridot"),
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=default_key_path(),
        help=trf(
            "Ruta de la clave AES-GCM (por defecto: {path}; override: PERIDOT_KEY_PATH)",
            path=DEFAULT_KEY,
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
        help=tr("Muestra la version y sale"),
    )
    parser.add_argument(
        "--no-update-check",
        dest="no_update_check",
        action="store_true",
        help=tr("No comprueba actualizaciones (desactiva el aviso)."),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    pack_parser = subparsers.add_parser("pack", help="Crea un paquete .peridot")
    pack_parser.add_argument("name", nargs="?", help="Nombre del bundle")
    pack_parser.add_argument("paths", nargs="*", help="Rutas a incluir. Si no se indican, usa las rutas por defecto del sistema.")
    pack_parser.add_argument("--output", type=Path, help="Ruta del paquete de salida")
    pack_parser.add_argument("--description", default="", help="Descripcion corta del bundle")
    pack_parser.add_argument("--platform", default="", help="SO objetivo: macos, linux, windows o any")
    pack_parser.add_argument("--shell", default="", help="Shell o runtime principal: fish, zsh, powershell, bash...")
    pack_parser.add_argument("--arch", default="", help="Arquitectura objetivo: arm64, x86_64 o any")
    pack_parser.add_argument("--tag", dest="tags", action="append", default=[], help="Tag del bundle. Repetible.")
    pack_parser.add_argument("--preset", default="", help="Preset de dotfiles: macos-fish, macos-zsh, linux-fish, linux-zsh, linux-bash, windows-powershell")
    pack_parser.add_argument("--profile", default="", help="Perfil guardado para reutilizar configuracion")
    pack_parser.add_argument("--exclude", action="append", default=[], help="Glob a excluir. Repetible.")
    pack_parser.add_argument("--notes", default="", help="Notas del bundle")
    pack_parser.add_argument("--after-step", dest="after_steps", action="append", default=[], help="Paso post-apply. Repetible.")
    pack_parser.add_argument("--compression-level", type=int, default=None, choices=range(0, 10), help="Nivel de compresion Peridot: zstd si esta disponible, gzip como fallback. 0 rapido, 9 pequeno. Si no se pasa, usa settings.")
    pack_parser.add_argument("--jobs", type=int, default=None, help="Numero de workers para pack. Si no se pasa, usa settings.")
    pack_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    pack_parser.add_argument("-y", "--yes", action="store_true", help="Aceptar avisos sensibles sin confirmacion")
    pack_parser.set_defaults(func=cmd_pack)

    bench_parser = subparsers.add_parser("bench", help="Quick pack benchmark (time + size)")
    bench_parser.add_argument("--files", type=int, default=200, help="Numero de ficheros sinteticos")
    bench_parser.add_argument("--size-kb", type=int, default=4, help="Tamano por fichero (KB)")
    bench_parser.add_argument("--runs", type=int, default=1, help="Repeticiones por configuracion")
    bench_parser.add_argument("--levels", default="0,1,3", help="Niveles de compresion separados por coma")
    bench_parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="Workers para pack")
    bench_parser.add_argument("--json", action="store_true", help="Imprime tambien JSON con resultados")
    bench_parser.add_argument("--out", type=Path, help="Guarda el JSON en un fichero")
    bench_parser.set_defaults(func=cmd_bench)

    inspect_parser = subparsers.add_parser("inspect", help="Muestra la ficha de un paquete")
    inspect_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    inspect_parser.add_argument("--files", action="store_true", help="Muestra la lista de ficheros")
    inspect_parser.add_argument("--all", action="store_true", help="Muestra todos los ficheros")
    inspect_parser.add_argument("--json", action="store_true", help="Imprime tambien el manifest en JSON")
    inspect_parser.set_defaults(func=cmd_inspect)

    apply_parser = subparsers.add_parser("apply", help="Aplica un paquete .peridot")
    apply_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    apply_parser.add_argument("--target", type=Path, default=Path.home(), help="Directorio destino para la restauracion")
    apply_parser.add_argument("--backup-dir", type=Path, help="Si existe el fichero, guarda una copia antes de sobrescribir")
    apply_parser.add_argument("--transactional", dest="transactional", action="store_true", default=True, help="Rollback best-effort si falla a mitad (por defecto activado)")
    apply_parser.add_argument("--no-transactional", dest="transactional", action="store_false", help="Desactiva rollback transaccional")
    apply_parser.add_argument("--verify", dest="verify", action="store_true", default=True, help="Verifica hash tras escribir (por defecto activado)")
    apply_parser.add_argument("--no-verify", dest="verify", action="store_false", help="Desactiva verificacion post-escritura")
    apply_parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se haria sin escribir")
    apply_parser.add_argument("--ignore-platform", action="store_true", help="Aplica incluso si el target del bundle no coincide con la maquina actual")
    apply_parser.add_argument("--select", action="append", default=[], help="Path exacto dentro del bundle a restaurar. Repetible.")
    apply_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    apply_parser.add_argument("--apply-token", default="", help="Safety token produced by --dry-run --json; required by MCP")
    apply_parser.add_argument("-y", "--yes", action="store_true", help="No pedir confirmacion interactiva")
    apply_parser.set_defaults(func=cmd_apply)

    diff_parser = subparsers.add_parser("diff", help="Compara un bundle con un directorio destino")
    diff_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    diff_parser.add_argument("--target", type=Path, default=Path.home(), help="Directorio destino")
    diff_parser.add_argument("--no-hash", action="store_true", help="No descifrar payloads; solo comprobar presencia")
    diff_parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON")
    diff_parser.set_defaults(func=cmd_diff)

    verify_parser = subparsers.add_parser("verify", help="Verifica integridad del bundle")
    verify_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    verify_parser.add_argument("--deep", action="store_true", help="Verifica hashes descifrando payloads con la clave")
    verify_parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON")
    verify_parser.set_defaults(func=cmd_verify)

    doctor_parser = subparsers.add_parser("doctor", help="Diagnostico del entorno local")
    doctor_parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON")
    doctor_parser.set_defaults(func=cmd_doctor)

    version_parser = subparsers.add_parser("version", help="Muestra informacion de version y runtime")
    version_parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON")
    version_parser.set_defaults(func=cmd_version)

    update_parser = subparsers.add_parser("self-update", help="Actualiza peridot-cli usando pip")
    update_parser.add_argument("-y", "--yes", action="store_true", help="No pedir confirmacion")
    update_parser.set_defaults(func=cmd_self_update)

    share_parser = subparsers.add_parser("share", help="Exporta una ficha CLI-friendly del bundle")
    share_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    share_parser.add_argument("--format", choices=["json", "md"], default="md", help="Formato de salida")
    share_parser.add_argument("--output", type=Path, help="Ruta de salida opcional")
    share_parser.set_defaults(func=cmd_share)

    merge_parser = subparsers.add_parser("merge", help="Fusiona varios bundles en uno")
    merge_parser.add_argument("packages", nargs="+", type=Path, help="Bundles a fusionar")
    merge_parser.add_argument("--output", type=Path, required=True, help="Bundle de salida")
    merge_parser.add_argument("--name", default="", help="Nombre del bundle resultante")
    merge_parser.add_argument("--description", default="", help="Descripcion del bundle resultante")
    merge_parser.add_argument("--platform", default="", help="Plataforma del bundle resultante")
    merge_parser.add_argument("--shell", default="", help="Shell del bundle resultante")
    merge_parser.add_argument("--arch", default="", help="Arquitectura del bundle resultante")
    merge_parser.add_argument("--tag", dest="tags", action="append", default=[], help="Tag repetible")
    merge_parser.set_defaults(func=cmd_merge)

    split_parser = subparsers.add_parser("split", help="Extrae un subset de un bundle en otro bundle")
    split_parser.add_argument("package", type=Path, help="Bundle origen")
    split_parser.add_argument("--prefix", action="append", required=True, help="Prefijo/path a extraer. Repetible.")
    split_parser.add_argument("--output", type=Path, required=True, help="Bundle de salida")
    split_parser.add_argument("--name", default="", help="Nombre del bundle resultante")
    split_parser.add_argument("--description", default="", help="Descripcion del bundle resultante")
    split_parser.set_defaults(func=cmd_split)

    history_parser = subparsers.add_parser("history", help="Lista snapshots historicos de un bundle")
    history_parser.add_argument("bundle", help="Nombre base del bundle sin extension")
    history_parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON")
    history_parser.set_defaults(func=cmd_history)

    manifest_parser = subparsers.add_parser("manifest", help="Imprime el manifest de un paquete")
    manifest_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    manifest_parser.set_defaults(func=cmd_manifest)

    delete_parser = subparsers.add_parser("delete", help="Elimina paquetes .peridot")
    delete_parser.add_argument("packages", nargs="*", help="Paquetes a eliminar o indices locales")
    delete_parser.add_argument("--all-local", action="store_true", help="Elimina todos los .peridot del directorio actual")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="No pedir confirmacion")
    delete_parser.set_defaults(func=cmd_delete)

    rekey_parser = subparsers.add_parser("rekey", help="Genera una nueva clave y migra paquetes existentes")
    rekey_parser.add_argument("packages", nargs="*", help="Paquetes a migrar o indices locales")
    rekey_parser.add_argument("--all-local", action="store_true", help="Migra todos los .peridot del directorio actual")
    rekey_parser.add_argument("--no-backup", action="store_true", help="No guardar copia de la clave antigua")
    rekey_parser.add_argument("-y", "--yes", action="store_true", help="No pedir confirmacion")
    rekey_parser.set_defaults(func=cmd_rekey)

    catalog_parser = subparsers.add_parser("catalog", help="Lista grupos clasificados de configuracion detectables")
    catalog_parser.add_argument("--platform", default="", help="Plataforma a inspeccionar: macos, linux o windows")
    catalog_parser.add_argument("--shell", default="", help="Shell para recomendaciones por defecto")
    catalog_parser.set_defaults(func=cmd_catalog)

    profile_parser = subparsers.add_parser("profile", help="Gestiona perfiles reutilizables")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)

    profile_save_parser = profile_subparsers.add_parser("save", help="Guarda un perfil")
    profile_save_parser.add_argument("name", help="Nombre del perfil")
    profile_save_parser.add_argument("--bundle-name", default="", help="Nombre de bundle por defecto")
    profile_save_parser.add_argument("--description", default="", help="Descripcion")
    profile_save_parser.add_argument("--platform", default="", help="Plataforma")
    profile_save_parser.add_argument("--shell", default="", help="Shell")
    profile_save_parser.add_argument("--arch", default="", help="Arquitectura")
    profile_save_parser.add_argument("--tag", dest="tags", action="append", default=[], help="Tag repetible")
    profile_save_parser.add_argument("--preset", default="", help="Preset base")
    profile_save_parser.add_argument("--path", dest="paths", action="append", default=[], help="Path repetible")
    profile_save_parser.add_argument("--exclude", action="append", default=[], help="Glob a excluir")
    profile_save_parser.add_argument("--notes", default="", help="Notas")
    profile_save_parser.add_argument("--after-step", dest="after_steps", action="append", default=[], help="Paso post-apply")
    profile_save_parser.set_defaults(func=cmd_profile_save)

    profile_list_parser = profile_subparsers.add_parser("list", help="Lista perfiles")
    profile_list_parser.set_defaults(func=cmd_profile_list)

    profile_show_parser = profile_subparsers.add_parser("show", help="Muestra un perfil")
    profile_show_parser.add_argument("name", help="Nombre del perfil")
    profile_show_parser.set_defaults(func=cmd_profile_show)

    profile_delete_parser = profile_subparsers.add_parser("delete", help="Elimina un perfil")
    profile_delete_parser.add_argument("name", help="Nombre del perfil")
    profile_delete_parser.set_defaults(func=cmd_profile_delete)

    settings_parser = subparsers.add_parser("settings", help="Gestiona defaults persistentes de Peridot")
    settings_parser.add_argument("--show", action="store_true", help="Muestra los settings efectivos")
    settings_parser.add_argument("--set", action="append", default=[], help="Actualiza un setting con clave=valor. Repetible.")
    settings_parser.add_argument("--settings-path", type=Path, default=None, help="Ruta del store de settings (o PERIDOT_SETTINGS_PATH)")
    settings_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    settings_parser.set_defaults(func=cmd_settings)

    keygen_parser = subparsers.add_parser("keygen", help="Genera o muestra la clave activa")
    keygen_parser.set_defaults(func=cmd_keygen)

    init_parser = subparsers.add_parser("init", help="Initialize Peridot (key + settings)")
    init_parser.add_argument("--force", action="store_true", help="Sobrescribe settings existentes")
    init_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    init_parser.set_defaults(func=cmd_init)

    ui_parser = subparsers.add_parser("ui", help="Lanza el command center visual")
    ui_parser.set_defaults(func=cmd_ui)

    export_parser = subparsers.add_parser("export", help="Alias de pack")
    export_parser.add_argument("name", nargs="?", help="Nombre del bundle")
    export_parser.add_argument("paths", nargs="*", help="Rutas a incluir")
    export_parser.add_argument("--output", type=Path, help="Ruta del paquete de salida")
    export_parser.add_argument("--description", default="", help="Descripcion corta del bundle")
    export_parser.add_argument("--platform", default="", help="SO objetivo")
    export_parser.add_argument("--shell", default="", help="Shell o runtime principal")
    export_parser.add_argument("--arch", default="", help="Arquitectura objetivo")
    export_parser.add_argument("--tag", dest="tags", action="append", default=[], help="Tag del bundle. Repetible.")
    export_parser.add_argument("--preset", default="", help="Preset de dotfiles")
    export_parser.add_argument("--profile", default="", help="Perfil guardado")
    export_parser.add_argument("--exclude", action="append", default=[], help="Glob a excluir")
    export_parser.add_argument("--notes", default="", help="Notas del bundle")
    export_parser.add_argument("--after-step", dest="after_steps", action="append", default=[], help="Paso post-apply")
    export_parser.add_argument("--compression-level", type=int, default=None, choices=range(0, 10), help="Nivel de compresion Peridot: zstd si esta disponible, gzip como fallback. Si no se pasa, usa settings.")
    export_parser.add_argument("--jobs", type=int, default=None, help="Numero de workers para pack. Si no se pasa, usa settings.")
    export_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    export_parser.add_argument("-y", "--yes", action="store_true", help="Aceptar avisos sensibles")
    export_parser.set_defaults(func=cmd_pack)

    import_parser = subparsers.add_parser("import", help="Alias de apply")
    import_parser.add_argument("package", type=Path, help="Ruta del paquete .peridot")
    import_parser.add_argument("--target", type=Path, default=Path.home(), help="Directorio destino para la restauracion")
    import_parser.add_argument("--backup-dir", type=Path, help="Si existe el fichero, guarda una copia antes de sobrescribir")
    import_parser.add_argument("--transactional", dest="transactional", action="store_true", default=True, help="Rollback best-effort si falla a mitad (por defecto activado)")
    import_parser.add_argument("--no-transactional", dest="transactional", action="store_false", help="Desactiva rollback transaccional")
    import_parser.add_argument("--verify", dest="verify", action="store_true", default=True, help="Verifica hash tras escribir (por defecto activado)")
    import_parser.add_argument("--no-verify", dest="verify", action="store_false", help="Desactiva verificacion post-escritura")
    import_parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se haria sin escribir")
    import_parser.add_argument("--ignore-platform", action="store_true", help="Aplica incluso si el target del bundle no coincide con la maquina actual")
    import_parser.add_argument("--select", action="append", default=[], help="Path exacto dentro del bundle a restaurar. Repetible.")
    import_parser.add_argument("--json", action="store_true", help="Structured JSON output (no banner/tables)")
    import_parser.add_argument("--apply-token", default="", help="Safety token produced by --dry-run --json; required by MCP")
    import_parser.add_argument("-y", "--yes", action="store_true", help="No pedir confirmacion interactiva")
    import_parser.set_defaults(func=cmd_apply)

    localize_parser(parser)
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    # Default to English, but allow overriding via settings or PERIDOT_LANG.
    runtime_lang = detect_runtime_language()
    set_current_language(runtime_lang)

    # If the system language looks Spanish but Peridot is running in English by
    # default (no explicit settings), suggest switching.
    try:
        settings_path = default_settings_store()
        has_settings = settings_path.exists()
    except Exception:
        has_settings = False

    should_suggest_spanish = (
        runtime_lang == "en"
        and not os.environ.get("PERIDOT_LANG")
        and not has_settings
        and (detect_system_language_hint() or "").startswith("es")
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    # Avoid polluting machine-readable output modes.
    if should_suggest_spanish and not getattr(args, "json", False):
        sys.stderr.write(
            tr(
                "Tip: tu idioma del sistema parece espanol. Puedes cambiar la UI/CLI de Peridot con PERIDOT_LANG=es o desde la UI de Settings."
            )
            + "\n"
        )

    # Best-effort update check (non-fatal, cached).
    maybe_suggest_self_update(args)

    # Rich is required for the full TUI/pretty output, but JSON modes should
    # still work in constrained environments.
    json_mode = bool(getattr(args, "json", False))

    if not RICH_AVAILABLE and not json_mode:
        hint = venv_activation_hint()
        runtime = python_runtime_hint()
        pip_hint = install_hint(".")

        extra_lines: list[str] = []
        if runtime:
            extra_lines.append(runtime)
        if hint:
            extra_lines.append(hint)

        print(
            tr("Error: falta la dependencia 'rich'.")
            + " "
            + trf("Instalala con '{cmd}'.", cmd=pip_hint)
            + (("\n" + "\n".join(extra_lines)) if extra_lines else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)

    args.func(args)


if __name__ == "__main__":
    main()
