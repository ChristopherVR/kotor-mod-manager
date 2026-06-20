"""
Fetch HoloPatcher and place it where the installer's universal shim looks
(<project>/tools/HoloPatcher/HoloPatcher.exe). The build then bundles it INTO
the distributed .exe, so end users never touch the tools/ folder.

HoloPatcher (part of the PyKotor project) is a headless, open-source
reimplementation of TSLPatcher. Because it reads the exact same tslpatchdata /
changes.ini / namespaces.ini format, one HoloPatcher.exe can install ANY
TSLPatcher mod — old or new — with no GUI and no clicking. This is the
"dynamic patcher" the installer relies on.

The PyKotor release assets are zips (e.g. HoloPatcher_Windows_x64.zip) that
contain the HoloPatcher executable; this script downloads the right one and
extracts the exe.

Usage:
    python tools/setup_holopatcher.py                # latest STABLE patcher release
    python tools/setup_holopatcher.py --prerelease   # allow beta releases
    python tools/setup_holopatcher.py <local.zip|.exe>  # use a local file
"""

import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

DEST_DIR = Path(__file__).parent / "HoloPatcher"
DEST_EXE = DEST_DIR / "HoloPatcher.exe"

RELEASES_API = "https://api.github.com/repos/NickHugi/PyKotor/releases"
_UA = {"User-Agent": "kotor-mod-installer"}


def _is_windows_patcher_asset(name: str) -> bool:
    n = name.lower()
    if "holopatcher" not in n:
        return False
    if "windows" not in n and "win" not in n:
        return False
    return n.endswith(".zip") or n.endswith(".exe") or n.endswith(".exe.zip")


def _rank_asset(name: str) -> int:
    """Prefer 64-bit over 32-bit; prefer .exe-bearing zips."""
    n = name.lower()
    score = 0
    if "x64" in n or "amd64" in n or "win64" in n:
        score += 10
    if "x86" in n or "win32" in n:
        score -= 5
    return score


def _select_asset(prerelease: bool) -> "tuple[str, str] | None":
    """Return (tag, download_url) for the best Windows HoloPatcher asset."""
    req = urllib.request.Request(RELEASES_API, headers=_UA)
    releases = json.loads(urllib.request.urlopen(req, timeout=30).read())

    best = None  # (release_index, asset_score, tag, url)
    for idx, rel in enumerate(releases):
        if rel.get("prerelease") and not prerelease:
            continue
        # Only consider the patcher line, not the toolset releases.
        if "patcher" not in (rel.get("tag_name", "").lower()):
            continue
        for asset in rel.get("assets", []):
            name = asset.get("name", "")
            if not _is_windows_patcher_asset(name):
                continue
            score = _rank_asset(name)
            # Earlier release index == newer release (API returns newest first).
            if best is None or (idx, -score) < (best[0], -best[1]):
                best = (idx, score, rel["tag_name"], asset["browser_download_url"])
    if best:
        return best[2], best[3]
    return None


def _extract_exe_from_zip(data: bytes) -> bool:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Find HoloPatcher executable inside the archive.
        exe_member = None
        for info in zf.infolist():
            low = info.filename.lower()
            if low.endswith("holopatcher.exe") or (low.endswith(".exe") and "holopatcher" in low):
                exe_member = info
                break
        if not exe_member:
            # Some archives ship a folder of files; copy the whole thing.
            zf.extractall(DEST_DIR)
            # Try to locate an exe afterwards.
            for p in DEST_DIR.rglob("*.exe"):
                if "holopatcher" in p.name.lower():
                    if p != DEST_EXE:
                        shutil.copy2(p, DEST_EXE)
                    return True
            return False
        with zf.open(exe_member) as src, open(DEST_EXE, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return DEST_EXE.exists()


def _use_local(path: str) -> int:
    src = Path(path)
    if not src.exists():
        print(f"Source not found: {src}")
        return 1
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".zip":
        ok = _extract_exe_from_zip(src.read_bytes())
    else:
        shutil.copy2(src, DEST_EXE)
        ok = True
    print(f"HoloPatcher ready at {DEST_EXE}" if ok else "Could not find HoloPatcher.exe in source")
    return 0 if ok else 1


def _download(prerelease: bool) -> int:
    print("Querying GitHub for the latest HoloPatcher release...")
    try:
        selected = _select_asset(prerelease)
    except Exception as e:
        print(f"Could not query releases: {e}")
        return 1
    if not selected:
        print("No Windows HoloPatcher asset found.")
        print("Grab it manually from https://github.com/NickHugi/PyKotor/releases")
        return 1

    tag, url = selected
    print(f"Selected {tag}: {url}")
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=180).read()
    except Exception as e:
        print(f"Download failed: {e}")
        return 1

    if url.lower().endswith(".zip"):
        ok = _extract_exe_from_zip(data)
    else:
        DEST_DIR.mkdir(parents=True, exist_ok=True)
        DEST_EXE.write_bytes(data)
        ok = True

    if ok:
        size = DEST_EXE.stat().st_size / 1e6
        print(f"HoloPatcher ready at {DEST_EXE} ({size:.1f} MB)")
        return 0
    print("Downloaded archive but could not extract HoloPatcher.exe")
    return 1


def main(argv: "list[str]") -> int:
    args = [a for a in argv if a]
    prerelease = "--prerelease" in args
    args = [a for a in args if a != "--prerelease"]
    if args:
        return _use_local(args[0])
    return _download(prerelease)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
