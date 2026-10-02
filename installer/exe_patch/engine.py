"""
Build a patched swkotor.exe from a clean base, always in the same order.

The base file is never modified. Redoing the patches means building again from
the same base, and undoing them means putting the base back.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from installer.exe_patch import PatchError, hrmenus, pe, uniws

# The one order that works: UniWS, then HR Menus, then the 4GB flag last.
STEP_ORDER = ("uniws", "hrmenus", "laa")

EXE_STEPS = frozenset(STEP_ORDER)


def exe_kind(path: Path) -> str:
    """'steam' (copy-protected release), 'plain' (a normal v1.03 program) or 'unknown'."""
    try:
        data = path.read_bytes()
        if pe.has_steam_drm(data):
            return "steam"
        pe.is_large_address_aware(data)       # raises unless it is a 32-bit exe
    except (OSError, PatchError):
        return "unknown"
    return "plain"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class BuildResult:
    applied: list[str]
    sha256: str


def patch_bytes(data: bytes, steps: Iterable[str], width: int, height: int,
                uniws_ini: str = "", letterbox: bool = True) -> tuple[bytearray, list[str]]:
    """Apply the wanted steps to a copy of data. Raises PatchError before anything is kept."""
    wanted = set(steps)
    unknown = wanted - EXE_STEPS
    if unknown:
        raise PatchError(f"Unknown patch step: {', '.join(sorted(unknown))}")
    if pe.has_steam_drm(data):
        raise PatchError("This is the copy-protected Steam program file, which these patches cannot edit.")
    out, applied = bytearray(data), []
    for step in STEP_ORDER:
        if step not in wanted:
            continue
        if step == "uniws":
            uniws.apply(out, uniws.parse_recipe(uniws_ini), width, height)
        elif step == "hrmenus":
            hrmenus.apply(out, width, height, letterbox)
        else:
            pe.set_large_address_aware(out)
        applied.append(step)
    return out, applied


def build_patched_exe(base: Path, dest: Path, steps: Iterable[str], width: int, height: int,
                      uniws_ini: str = "", letterbox: bool = True) -> BuildResult:
    """Patch a copy of base and put it at dest. dest is only replaced when every step fits."""
    out, applied = patch_bytes(base.read_bytes(), steps, width, height, uniws_ini, letterbox)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(out)
    os.replace(tmp, dest)
    return BuildResult(applied, hashlib.sha256(out).hexdigest())
