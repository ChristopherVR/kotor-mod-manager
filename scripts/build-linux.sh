#!/usr/bin/env bash
# Build the Linux version: one self-contained executable with the backend and
# HoloPatcher embedded, like the Windows .exe.
#
# Usage:  scripts/build-linux.sh [--skip-holopatcher] [--fast]
#   --fast  skip LTO and use parallel codegen for the Tauri shell: much quicker
#           to build, slightly larger binary. Use for testing, not releases.
# Output: dist/KOTOR-Mod-Installer-linux-x86_64
#
# Needs (Debian/Ubuntu package names):
#   python3.12 python3.12-venv python3.12-tk git nodejs npm curl build-essential pkg-config
#   libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
#   libssl-dev patchelf  (and Rust from https://rustup.rs)
# Fedora/Arch equivalents: webkit2gtk4.1-devel / webkit2gtk-4.1, gtk3, etc.
set -euo pipefail

SKIP_HOLO=0
FAST=0
for arg in "$@"; do
  case "$arg" in
    --skip-holopatcher) SKIP_HOLO=1 ;;
    --fast) FAST=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

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
[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || command -v xvfb-run >/dev/null || { echo "No display and no xvfb-run: HoloPatcher needs one of them to be checked after building (sudo apt install xvfb)." >&2; exit 1; }
pkg-config --exists webkit2gtk-4.1 || { echo "Missing libwebkit2gtk-4.1-dev (and libgtk-3-dev)" >&2; exit 1; }

step "Python environment ($PY)"
# Drop a venv left over from a too-new Python.
if [ -d "$VENV" ] && ! "$VENV/bin/python" -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3, 12) else 1)" 2>/dev/null; then
  rm -rf "$VENV"
fi
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# Only reinstall when requirements.txt changed (saves the network round trips).
REQ_STAMP="$VENV/.requirements.sha256"
REQ_HASH="$(cat requirements.txt constraints.txt | sha256sum | cut -d' ' -f1)"
if [ "$(cat "$REQ_STAMP" 2>/dev/null)" != "$REQ_HASH" ] || ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r requirements.txt -c constraints.txt pyinstaller
  echo "$REQ_HASH" > "$REQ_STAMP"
fi

step "Backend sanity check"
"$VENV/bin/python" -c "import backend.server, installer.pipeline, installer.patcher_strategy; print('backend imports OK')"

if [ "$SKIP_HOLO" != 1 ]; then
  step "Build HoloPatcher (pinned PyKotor source)"
  "$VENV/bin/python" tools/setup_holopatcher.py
fi
[ -x tools/HoloPatcher/HoloPatcher ] || { echo "tools/HoloPatcher/HoloPatcher missing; the app would not be able to install mods." >&2; exit 1; }
# HoloPatcher's window is created even for --help, so it needs a display.
# Players always have one; on a headless build machine borrow a virtual one.
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  tools/HoloPatcher/HoloPatcher --help >/dev/null || { echo "HoloPatcher failed to start." >&2; exit 1; }
else
  xvfb-run -a tools/HoloPatcher/HoloPatcher --help >/dev/null || { echo "HoloPatcher failed to start." >&2; exit 1; }
fi

step "Build backend (PyInstaller)"
# Reuse the previous backend if nothing it is built from has changed.
if [ -f dist/kotor-backend ] && [ -z "$(find backend installer config.py backend.spec requirements.txt CHANGELOG.md tools/HoloPatcher/HoloPatcher \
     -type f -not -path '*/__pycache__/*' -newer dist/kotor-backend -print -quit 2>/dev/null)" ]; then
  echo "Backend unchanged, reusing dist/kotor-backend"
else
  "$VENV/bin/python" -m PyInstaller backend.spec --noconfirm
fi
mkdir -p frontend/src-tauri/binaries
cp dist/kotor-backend frontend/src-tauri/binaries/kotor-backend
chmod +x frontend/src-tauri/binaries/kotor-backend

step "Build frontend + Tauri shell"
# Only reinstall node modules when the lockfile changed.
if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
  ( cd frontend && npm ci )
fi
if [ "$FAST" = 1 ]; then
  export CARGO_PROFILE_RELEASE_LTO=false CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 CARGO_PROFILE_RELEASE_INCREMENTAL=true
fi
( cd frontend && npx tauri build --no-bundle )

step "Collect result"
mkdir -p dist
# Rename over the old file so this works while a previous build is running.
cp frontend/src-tauri/target/release/kotor-mod-installer "$OUT.new"
chmod +x "$OUT.new"
mv -f "$OUT.new" "$OUT"
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
