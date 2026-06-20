# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the KOTOR Mod Installer BACKEND sidecar.

Freezes the FastAPI/uvicorn server (with the bundled HoloPatcher shim and
installer_config.json) into a single self-contained exe that the Tauri shell
spawns on launch. The build step renames the output to Tauri's sidecar naming
convention: kotor-backend-<target-triple>.exe.

Build:  pyinstaller backend.spec --noconfirm
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("installer/installer_config.json", "installer"),
]
binaries = []
hiddenimports = []

# Bundle the headless HoloPatcher engine so the sidecar is fully self-contained.
_holo = os.path.join("tools", "HoloPatcher", "HoloPatcher.exe")
if os.path.exists(_holo):
    datas += [(_holo, os.path.join("tools", "HoloPatcher"))]
    print(f"[backend.spec] Bundling HoloPatcher shim: {_holo}")
else:
    print("[backend.spec] WARNING: HoloPatcher.exe not found — run tools/setup_holopatcher.py first.")

# uvicorn/fastapi pull a lot of implementations dynamically.
for pkg in ("uvicorn", "fastapi", "starlette", "anyio"):
    hiddenimports += collect_submodules(pkg)

# websockets + http tooling used by uvicorn[standard]
hiddenimports += [
    "websockets.legacy", "websockets.legacy.server",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.loops.asyncio",
    "uvicorn.lifespan.on",
    "h11",
]
# keyring backend + project runtime deps that static analysis can miss.
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "win32ctypes.core", "win32timezone",
    "py7zr", "rarfile", "lxml._elementpath", "bs4",
]

block_cipher = None


a = Analysis(
    ["backend/server.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "customtkinter", "PIL", "test", "unittest"],
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
    name="kotor-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,            # Tauri spawns sidecars with no window; keep stdio for uvicorn logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
