"""
Tell whether a folder is a real KOTOR installation.

Mods are patched straight into the game folder, so pointing the installer at the
wrong folder (an empty "New folder", a Documents folder, the Steam library root)
wastes a long download and then fails deep inside the patcher with a cryptic
message. We check up front instead, the same way the patcher engine does: by
looking for the game's resource index (chitin.key).
"""
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]

# Canonical files that only exist inside a KOTOR game folder.
_CHITIN = "chitin.key"
_DIALOG = "dialog.tlk"
_MODULES = "modules"


def _has_file(folder: Path, name: str) -> bool:
    """Case-insensitive file check (Windows is already case-insensitive; this
    also covers case-sensitive filesystems where chitin.key may be capitalised)."""
    target = name.lower()
    if (folder / name).exists():
        return True
    try:
        return any(child.name.lower() == target for child in folder.iterdir())
    except OSError:
        return False


def _has_dir(folder: Path, name: str) -> bool:
    target = name.lower()
    try:
        return any(child.is_dir() and child.name.lower() == target
                   for child in folder.iterdir())
    except OSError:
        return False


def is_kotor_install(path: Optional[PathLike]) -> bool:
    """Return True if `path` looks like a KOTOR 1 or 2 installation folder."""
    if not path:
        return False
    p = Path(path)
    if not p.is_dir():
        return False
    # chitin.key is present in every PC install of either game - the strongest
    # single signal, and exactly what the patcher engine requires.
    if _has_file(p, _CHITIN):
        return True
    # Fall back to other tell-tale contents for unusual layouts.
    return _has_dir(p, _MODULES) and _has_file(p, _DIALOG)
