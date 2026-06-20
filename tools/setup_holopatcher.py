"""
Download the latest HoloPatcher and place it where the installer's universal
shim will find it (<project>/tools/HoloPatcher/HoloPatcher.exe).

HoloPatcher (part of the PyKotor / KOTORModSync project) is a headless,
open-source reimplementation of TSLPatcher. Because it reads the exact same
tslpatchdata / changes.ini / namespaces.ini format, a single HoloPatcher.exe
can install ANY TSLPatcher mod — old or new — with no GUI and no clicking.

This is the "dynamic patcher" the installer relies on: rather than binary-
patching dozens of bespoke (and legacy) TSLPatcher.exe builds, we substitute
one proven headless engine that consumes the identical data format.

Usage:
    python tools/setup_holopatcher.py            # auto-download latest release
    python tools/setup_holopatcher.py <path.exe> # copy a local HoloPatcher.exe

If automatic download fails (no network / API change), grab HoloPatcher from
https://github.com/NickHugi/PyKotor/releases and drop the .exe into
tools/HoloPatcher/.
"""

import json
import shutil
import sys
import urllib.request
from pathlib import Path

DEST_DIR = Path(__file__).parent / "HoloPatcher"
DEST_EXE = DEST_DIR / "HoloPatcher.exe"

RELEASES_API = "https://api.github.com/repos/NickHugi/PyKotor/releases"


def _copy_local(src: str) -> int:
    src_path = Path(src)
    if not src_path.exists():
        print(f"Source not found: {src_path}")
        return 1
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, DEST_EXE)
    print(f"Copied {src_path} → {DEST_EXE}")
    return 0


def _download_latest() -> int:
    print("Querying GitHub for the latest HoloPatcher release...")
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "kotor-mod-installer"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            releases = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"Could not query releases: {e}")
        print("Download HoloPatcher manually from "
              "https://github.com/NickHugi/PyKotor/releases and place the .exe in "
              f"{DEST_DIR}")
        return 1

    asset_url = None
    for rel in releases:
        for asset in rel.get("assets", []):
            name = asset.get("name", "").lower()
            if "holopatcher" in name and name.endswith(".exe") and "windows" in name or \
               ("holopatcher" in name and name.endswith(".exe")):
                asset_url = asset["browser_download_url"]
                break
        if asset_url:
            break

    if not asset_url:
        print("No HoloPatcher .exe asset found in recent releases.")
        print("Download manually from https://github.com/NickHugi/PyKotor/releases")
        return 1

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {asset_url}")
    req = urllib.request.Request(asset_url, headers={"User-Agent": "kotor-mod-installer"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(DEST_EXE, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        print(f"Download failed: {e}")
        return 1

    print(f"HoloPatcher ready at {DEST_EXE}")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return _copy_local(sys.argv[1])
    return _download_latest()


if __name__ == "__main__":
    raise SystemExit(main())
