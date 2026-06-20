# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for KOTOR Mod Installer.

Produces a single self-contained windowed .exe (no Python / pip required on
the target machine). Bundles installer_config.json and customtkinter's theme
assets, and declares hidden imports that PyInstaller's static analysis can miss.

Build:  pyinstaller kotor_mod_installer.spec --noconfirm
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("installer/installer_config.json", "installer"),
]
binaries = []
hiddenimports = []

# Bundle the headless HoloPatcher engine INTO the app so the distributed exe is
# fully self-contained — users never touch the tools/ folder. Fetched at build
# time by tools/setup_holopatcher.py (locally and in CI).
_holo = os.path.join("tools", "HoloPatcher", "HoloPatcher.exe")
if os.path.exists(_holo):
    datas += [(_holo, os.path.join("tools", "HoloPatcher"))]
    print(f"[spec] Bundling HoloPatcher shim: {_holo}")
else:
    print("[spec] WARNING: HoloPatcher.exe not found — building without the "
          "bundled headless shim. Run tools/setup_holopatcher.py first.")

# customtkinter ships JSON themes + assets that must travel with the app.
for pkg in ("customtkinter",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Backends / submodules that static analysis frequently misses.
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "win32ctypes.core",
    "win32timezone",
    "py7zr",
    "rarfile",
    "lxml._elementpath",
    "PIL._tkinter_finder",
]

block_cipher = None


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="KOTOR-Mod-Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # windowed GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if __import__("os").path.exists("assets/icon.ico") else None,
)
