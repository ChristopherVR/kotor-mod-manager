#!/usr/bin/env bash
# Build the Linux version: one self-contained executable with the backend and
# HoloPatcher embedded, like the Windows .exe.
#
# Usage:  scripts/build-linux.sh [--skip-holopatcher]
# Output: dist/KOTOR-Mod-Installer-linux-x86_64
#
# Needs (Debian/Ubuntu package names):
#   python3.12 python3.12-venv python3.12-tk git nodejs npm curl build-essential pkg-config
#   libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
#   libssl-dev patchelf  (and Rust from https://rustup.rs)
# Fedora/Arch equivalents: webkit2gtk4.1-devel / webkit2gtk-4.1, gtk3, etc.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="$ROOT/.venv-linux-build"
ARCH="$(uname -m)"
OUT="$ROOT/dist/KOTOR-Mod-Installer-linux-$ARCH"

step() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1 ($2)" >&2; exit 1; }; }

# The pinned HoloPatcher (PyKotor v1.52) breaks on Python 3.13+, so build with
# 3.12 (as CI does). Set BUILD_PYTHON=/path/to/python to override.
PY="${BUILD_PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi
[ -n "$PY" ] || { echo "Need Python 3.12 (or 3.11): newer versions cannot build the bundled HoloPatcher. Install python3.12 python3.12-venv python3.12-tk, or set BUILD_PYTHON." >&2; exit 1; }
"$PY" -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3, 12) else 1)" || { echo "$PY is too new to build HoloPatcher; use Python 3.12 or older." >&2; exit 1; }
need node "nodejs"
need npm "npm"
need cargo "Rust, see https://rustup.rs"
need git "git"
"$PY" -c "import ensurepip, venv" 2>/dev/null || { echo "Missing the venv module for $PY (sudo apt install ${PY}-venv)" >&2; exit 1; }
"$PY" -c "import tkinter" 2>/dev/null || { echo "Missing tkinter for $PY (sudo apt install ${PY}-tk; HoloPatcher imports it)" >&2; exit 1; }
pkg-config --exists webkit2gtk-4.1 || { echo "Missing libwebkit2gtk-4.1-dev (and libgtk-3-dev)" >&2; exit 1; }

step "Python environment ($PY)"
# Drop a venv left over from a too-new Python.
if [ -d "$VENV" ] && ! "$VENV/bin/python" -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3, 12) else 1)" 2>/dev/null; then
  rm -rf "$VENV"
fi
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r requirements.txt pyinstaller

step "Backend sanity check"
"$VENV/bin/python" -c "import backend.server, installer.pipeline, installer.patcher_strategy; print('backend imports OK')"

if [ "${1:-}" != "--skip-holopatcher" ]; then
  step "Build HoloPatcher (pinned PyKotor source)"
  "$VENV/bin/python" tools/setup_holopatcher.py
fi
[ -x tools/HoloPatcher/HoloPatcher ] || { echo "tools/HoloPatcher/HoloPatcher missing; the app would not be able to install mods." >&2; exit 1; }
tools/HoloPatcher/HoloPatcher --help >/dev/null || { echo "HoloPatcher does not run headlessly." >&2; exit 1; }

step "Build backend (PyInstaller)"
"$VENV/bin/python" -m PyInstaller backend.spec --noconfirm
mkdir -p frontend/src-tauri/binaries
cp dist/kotor-backend frontend/src-tauri/binaries/kotor-backend
chmod +x frontend/src-tauri/binaries/kotor-backend

step "Build frontend + Tauri shell"
( cd frontend && npm ci && npx tauri build --no-bundle )

step "Collect result"
mkdir -p dist
# Rename over the old file so this works while a previous build is running.
cp frontend/src-tauri/target/release/kotor-mod-installer "$OUT.new"
chmod +x "$OUT.new"
mv -f "$OUT.new" "$OUT"
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
