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

echo "Installing Peridot into $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$ROOT_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/peridot" "$BIN_DIR/peridot"

echo
echo "Peridot installed."
echo "CLI: $BIN_DIR/peridot"
echo
echo "If '$BIN_DIR' is not in your PATH, add this line to your shell profile:"
echo "export PATH=\"$BIN_DIR:\$PATH\""
