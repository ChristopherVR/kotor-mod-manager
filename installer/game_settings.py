"""Game settings in swkotor.ini."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from installer.pathcase import resolve_ci

_SECTION = "Graphics Options"


def set_resolution(game_path: Path, width: int, height: int) -> Optional[Path]:
    """Set Width and Height in swkotor.ini's [Graphics Options], leaving every other
    line as it was. The first change keeps the player's file as swkotor.ini.orig.
    Returns the ini path, or None when the game has no ini yet (it is made on first launch)."""
    ini = resolve_ci(game_path, "swkotor.ini")
    if not ini.is_file():
        return None
    raw = ini.read_bytes()
    text = raw.decode("latin-1")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)

    start = next((i for i, l in enumerate(lines)
                  if l.strip().lower() == f"[{_SECTION.lower()}]"), None)
    if start is None:
        lines += [f"[{_SECTION}]", f"Width={width}", f"Height={height}", ""]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
                   len(lines))
        seen = set()
        for i in range(start + 1, end):
            m = re.match(r"^\s*(width|height)\s*=", lines[i], re.I)
            if m:
                key = m.group(1).lower()
                seen.add(key)
                lines[i] = f"{'Width' if key == 'width' else 'Height'}={width if key == 'width' else height}"
        at = start + 1
        for key, val in (("height", height), ("width", width)):
            if key not in seen:
                lines.insert(at, f"{key.title()}={val}")

    new = eol.join(lines).encode("latin-1")
    if new != raw:
        orig = ini.with_name(ini.name + ".orig")
        if not orig.exists():
            shutil.copy2(ini, orig)
        ini.write_bytes(new)
    return ini
