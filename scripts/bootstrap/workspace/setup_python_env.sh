#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[STEP] Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "[SKIP] Virtual environment already exists at $VENV_DIR"
fi

echo "[STEP] Upgrading pip/setuptools/wheel"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

echo "[STEP] Installing project in editable mode with dev dependencies"
"$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR[dev]"

echo "[DONE] Python environment is ready: $VENV_DIR/bin/python"
