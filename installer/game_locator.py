"""
Find Steam installs of KOTOR so the player does not have to browse for them.
Covers extra Steam libraries and the Flatpak/Snap copies of Steam on Linux.
"""
import os
import re
import sys
from pathlib import Path
from typing import Iterable

from installer.game_validate import is_kotor_install

# Folder name under steamapps/common -> game key. Compared case-insensitively.
_STEAM_FOLDERS = {
    "swkotor": "KOTOR1",
    "star wars - knights of the old republic": "KOTOR1",
    "knights of the old republic ii": "KOTOR2",
    "star wars knights of the old republic ii": "KOTOR2",
}


def _steam_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        cands = []
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(var)
            if base:
                cands.append(Path(base) / "Steam")
        return cands
    if sys.platform == "darwin":
        return [home / "Library/Application Support/Steam"]
    return [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]


def _library_folders(steam_root: Path) -> list[Path]:
    """The Steam root plus the extra libraries in libraryfolders.vdf."""
    libs = [steam_root]
    for rel in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
        vdf = steam_root / rel
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def _child_dirs(folder: Path) -> Iterable[Path]:
    try:
        return [c for c in folder.iterdir() if c.is_dir()]
    except OSError:
        return []


def find_game_installs() -> list[dict]:
    """[{game, path, source}] for each KOTOR install found."""
    found: list[dict] = []
    seen: set[str] = set()
    for root in _steam_roots():
        if not root.is_dir():
            continue
        for lib in _library_folders(root):
            # Match "steamapps"/"common" case-insensitively (Linux).
            for apps in _child_dirs(lib):
                if apps.name.lower() != "steamapps":
                    continue
                for common in _child_dirs(apps):
                    if common.name.lower() != "common":
                        continue
                    for game_dir in _child_dirs(common):
                        game = _STEAM_FOLDERS.get(game_dir.name.lower())
                        if not game or not is_kotor_install(game_dir):
                            continue
                        try:
                            key = str(game_dir.resolve())
                        except OSError:
                            key = str(game_dir)
                        if key in seen:
                            continue
                        seen.add(key)
                        found.append({"game": game, "path": str(game_dir), "source": "steam"})
    return found
