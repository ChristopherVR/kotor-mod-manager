"""
Universal Widescreen patch (UniWS) for swkotor.exe, done directly on the bytes.

The recipe (byte signature plus where width and height live) comes from the
tool's own patches.ini, so nothing here is hard-coded to one game version.
"""
from __future__ import annotations

import struct

from installer.exe_patch import PatchError

KOTOR1_SECTION = "Star Wars: KOTOR (800x600 interface)"


def _read_section(ini_text: str, section: str) -> dict[str, str]:
    """One section of patches.ini as {key: value}. The file starts with free text
    and has odd spacing, so a plain INI parser is not used."""
    wanted, found, values = section.strip().lower(), False, {}
    for raw in ini_text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            found = line[1:-1].strip().lower() == wanted
        elif found and "=" in line and not line.startswith(";"):
            key, _, val = line.partition("=")
            values.setdefault(key.strip().lower(), val.strip())
    return values


def parse_recipe(ini_text: str, section: str = KOTOR1_SECTION) -> dict:
    sec = _read_section(ini_text, section)
    if not sec:
        raise PatchError("The widescreen patch data has no entry for KOTOR.")
    try:
        sig = bytes.fromhex(sec["sig"])
        wild = sec["sigwild"]
        recipe = {"sig": sig, "wild": wild,
                  "xoffset": int(sec["xoffset"]), "yoffset": int(sec["yoffset"])}
    except (KeyError, ValueError) as e:
        raise PatchError("The widescreen patch data is damaged.") from e
    if len(wild) != len(sig) or "0" not in wild:
        raise PatchError("The widescreen patch data is damaged.")
    return recipe


def _find(data: bytes | bytearray, sig: bytes, wild: str) -> list[int]:
    fixed = [(i, b) for i, (b, w) in enumerate(zip(sig, wild)) if w != "1"]
    first_i, first_b = fixed[0]
    hits, pos = [], data.find(bytes([first_b]))
    n = len(sig)
    while pos != -1:
        start = pos - first_i
        if start >= 0 and start + n <= len(data) and all(data[start + i] == b for i, b in fixed):
            hits.append(start)
        pos = data.find(bytes([first_b]), pos + 1)
    return hits


def apply(data: bytearray, recipe: dict, width: int, height: int) -> None:
    hits = _find(data, recipe["sig"], recipe["wild"])
    if len(hits) != 1:
        raise PatchError(
            "The widescreen patch does not fit this copy of the game "
            "(it needs the unprotected version 1.03 program file).")
    at = hits[0]
    struct.pack_into("<I", data, at + recipe["xoffset"], width)
    struct.pack_into("<I", data, at + recipe["yoffset"], height)
