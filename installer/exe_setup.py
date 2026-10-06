"""
Widescreen setup for swkotor.exe: ask first, keep the original, patch a copy.

The player's own program file is renamed to swkotor.exe.bak and never edited.
The patched swkotor.exe is built fresh from a clean base every time, so running
this again redoes the patches and restore_original() undoes them completely.
The Steam release is copy-protected and cannot be patched, so for it the base
is the unprotected v1.03 "KOTOR Editable Executable" (downloaded on request).
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Optional

import config as cfg
from installer.exe_patch import PatchError, engine
from installer.pathcase import resolve_ci

EDITABLE_EXE_ID = "1320"
EDITABLE_EXE_SLUG = "kotor-editable-executable"

STEP_LABELS = {
    "uniws": "Widescreen patch (makes the game accept your screen shape)",
    "hrmenus": "High resolution menus patch (makes the menus fit your screen)",
    "laa": "4GB patch (lets the game use more memory, so big mod lists do not crash it)",
}

Log = Callable[[str, str], None]


def _state_file(game: str) -> Path:
    return cfg.CONFIG_DIR / "exe_patch" / f"{game}.json"


def _base_cache(game: str) -> Path:
    return cfg.CONFIG_DIR / "exe_patch" / f"{game}-base" / "swkotor.exe"


def load_uniws_ini(zip_path: Path) -> str:
    """patches.ini from the UniWS download."""
    with zipfile.ZipFile(zip_path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("patches.ini")), None)
        if not name:
            raise PatchError("The widescreen patch download has no patch data in it.")
        return z.read(name).decode("latin-1")


def fetch_editable_exe(client, work_dir: Path, log: Log) -> Optional[Path]:
    """Download and unpack the unprotected v1.03 program file from DeadlyStream.
    Returns the swkotor.exe inside, or None if it could not be fetched or is wrong."""
    from installer.extractor import extract
    from installer.pathcase import rglob_ci
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        archive = client.download_file(EDITABLE_EXE_ID, work_dir, slug=EDITABLE_EXE_SLUG)
        folder = extract(archive, work_dir / "editable-exe")
    except Exception as e:
        log(f"  Could not download the unprotected game program: {e}", "warning")
        return None
    for exe in rglob_ci(folder, "swkotor.exe"):
        if engine.exe_kind(exe) == "plain":
            return exe
    log("  The download did not contain a usable swkotor.exe.", "warning")
    return None


def _find_exe(game_path: Path) -> Optional[Path]:
    exe = resolve_ci(game_path, "swkotor.exe")
    return exe if exe.is_file() else None


def _confirm_text(steps: list[str], steam: bool, width: int, height: int) -> str:
    lines = [f"To enable widescreen ({width}x{height}), the game's program file "
             f"(swkotor.exe) will be modified in this order:", ""]
    lines += [f"  {i}. {STEP_LABELS[s]}" for i, s in enumerate(steps, 1)]
    lines += ["", "Before anything is changed, your current swkotor.exe will be backed up "
              "as swkotor.exe.bak, so you can restore it at any time."]
    if steam:
        lines += ["", "Because you have the Steam version, whose program file has copy "
                  "protection that these changes can't work with, the unprotected 1.03 "
                  "program file from the KOTOR Editable Executable mod (DeadlyStream) "
                  "will be downloaded and used instead. This only affects your own copy "
                  "of the game."]
    return "\n".join(lines)


def run(game_path: Path, steps: list[str], resolution: str, uniws_ini: str, *,
        confirm: Callable[[str, str], bool],
        fetch_base: Callable[[], Optional[Path]],
        log: Log, game: str = "KOTOR1") -> bool:
    """Patch the game's program file. Returns True when it is patched and in place;
    False (with the reason logged) when skipped or when nothing was changed."""
    steps = [s for s in engine.STEP_ORDER if s in steps]
    try:
        width, height = (int(x) for x in resolution.lower().split("x"))
    except ValueError:
        log(f"  Could not read the screen size '{resolution}', so the program file was not patched.", "warning")
        return False

    exe = _find_exe(game_path)
    if exe is None:
        log("  Could not find swkotor.exe in the game folder.", "warning")
        return False
    bak = exe.with_name(exe.name + ".bak")

    # The original is the .bak when we made one on an earlier run, else the exe itself.
    original = bak if bak.is_file() else exe
    kind = engine.exe_kind(original)
    if kind == "unknown":
        log("  swkotor.exe is not a version these patches support, so it was left alone.", "warning")
        return False

    needs_base = kind == "steam"
    base = original
    if needs_base:
        base = _base_cache(game)
        if not base.is_file():
            base = None  # fetched after the player agrees

    if not confirm("Prepare the game's program file for widescreen",
                   _confirm_text(steps, needs_base, width, height)):
        log("  Skipped the program file patches. Widescreen will not work until they are done.", "warning")
        return False

    if needs_base and base is None:
        fetched = fetch_base()
        if fetched is None:
            log("  Without the unprotected program file the patches cannot be applied.", "warning")
            return False
        cache = _base_cache(game)
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fetched, cache)
        base = cache

    # Prove it fits before touching anything in the game folder.
    try:
        engine.patch_bytes(base.read_bytes(), steps, width, height, uniws_ini)
    except PatchError as e:
        log(f"  {e} Nothing was changed.", "warning")
        return False

    if not bak.is_file():
        exe.rename(bak)                # keep the player's original, never overwrite it
        if base == exe:
            base = bak
        log(f"  Kept your original program file as {bak.name}.", "muted")
    try:
        result = engine.build_patched_exe(base, exe, steps, width, height, uniws_ini)
    except Exception as e:
        if not exe.exists():
            shutil.copy2(bak, exe)     # never leave the game without a program file
        log(f"  Could not write the patched program file: {e}", "error")
        return False

    sf = _state_file(game)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({
        "game_path": str(game_path), "original_sha256": engine.sha256(bak),
        "patched_sha256": result.sha256, "steps": result.applied,
        "resolution": f"{width}x{height}",
    }), encoding="utf-8")
    log("  Patched the program file: " + ", ".join(result.applied) + ".", "success")
    return True


def restore_original(game_path: Path, game: str = "KOTOR1") -> bool:
    """Put the player's original swkotor.exe back. False if there is nothing to restore."""
    exe = _find_exe(game_path)
    if exe is None:
        return False
    bak = exe.with_name(exe.name + ".bak")
    if not bak.is_file():
        return False
    shutil.copy2(bak, exe)
    bak.unlink()
    _state_file(game).unlink(missing_ok=True)
    return True


_GUI_DIR = re.compile(r"^gui\.(\d+)x(\d+)$", re.I)


def pick_gui_set(mod_root: Path, width: int, height: int) -> Optional[Path]:
    """The mod's gui.WxH folder that best fits the screen: an exact match, else the
    closest size with the same shape, else the closest size overall."""
    sets = []
    for d in mod_root.rglob("*"):
        m = _GUI_DIR.match(d.name)
        if m and d.is_dir():
            sets.append((int(m.group(1)), int(m.group(2)), d))
    if not sets:
        return None

    def key(s):
        w, h, _ = s
        same_shape = w * height == h * width
        return (0 if (w, h) == (width, height) else 1, 0 if same_shape else 1,
                abs(w - width) + abs(h - height))

    return min(sets, key=key)[2]


def copy_gui_set(mod_root: Path, game_path: Path, resolution: str, game: str, log: Log) -> bool:
    """Copy the menu layout files for this screen into Override, saving any file
    they replace so it can be put back."""
    width, height = (int(x) for x in resolution.lower().split("x"))
    src = pick_gui_set(mod_root, width, height)
    if src is None:
        log("  The high resolution menus mod has no menu files to copy.", "warning")
        return False
    override = resolve_ci(game_path, "Override")
    override.mkdir(exist_ok=True)
    backup = cfg.CONFIG_DIR / "exe_patch" / f"{game}-gui-backup"
    saved = 0
    for f in sorted(p for p in src.iterdir() if p.is_file()):
        dest = override / f.name
        if dest.exists() and not (backup / f.name).exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, backup / f.name)
            saved += 1
        shutil.copy2(f, dest)
    log(f"  Copied the menu layout for {src.name[4:]} into Override"
        + (f" (kept {saved} replaced file(s) in {backup})." if saved else "."), "success")
    return True
