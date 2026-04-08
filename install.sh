#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PERIDOT_VENV:-$ROOT_DIR/.venv}"
BIN_DIR="${PERIDOT_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: no se encontro $PYTHON_BIN en PATH" >&2
  exit 1
fi

# Debian/Ubuntu tip: python -m venv requires the distro's venv/ensurepip bits.
if ! "$PYTHON_BIN" -c "import venv, ensurepip" >/dev/null 2>&1; then
  echo "Error: este Python no puede crear venv (falta ensurepip)." >&2
  echo "En Debian/Ubuntu suele arreglarse con:" >&2
  echo "  sudo apt-get install -y python3-venv" >&2
  exit 1
fi

echo "Installing Peridot into $VENV_DIR"
if [ -d "$VENV_DIR" ]; then
  echo "- Reusing existing venv"
else
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip

# Optional dev extras (pytest, etc.)
# Usage:
#   PERIDOT_INSTALL_DEV=1 ./install.sh
INSTALL_DEV="${PERIDOT_INSTALL_DEV:-0}"
if [ "$INSTALL_DEV" = "1" ] || [ "$INSTALL_DEV" = "true" ]; then
  echo "- Installing with dev extras"
  "$VENV_DIR/bin/pip" install -e "$ROOT_DIR[dev]"
else
  "$VENV_DIR/bin/pip" install -e "$ROOT_DIR"
fi

mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/peridot" "$BIN_DIR/peridot"

echo
echo "Peridot installed."
echo "CLI: $BIN_DIR/peridot"
echo
echo "If '$BIN_DIR' is not in your PATH, add this line to your shell profile:"
echo "export PATH=\"$BIN_DIR:\$PATH\""
