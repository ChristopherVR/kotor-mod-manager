"""Helpers for opening paths in the OS file manager.

Used by the "Open folder" / "Reveal download" actions. Works reliably from a
windowless (PyInstaller --windowed) build where a plain subprocess to a shell
may not, by preferring os.startfile on Windows.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]


def reveal_path(path: PathLike, select: bool = False) -> bool:
    """
    Open ``path`` in the OS file manager.

    - If ``path`` is a directory, open it.
    - If ``path`` is a file and ``select`` is True, open its parent folder with
      the file highlighted; otherwise open the parent folder.

    Returns True on success, False if the path does not exist or the open fails.
    """
    p = Path(path)
    if not p.exists():
        return False

    try:
        if sys.platform == "win32":
            if select and p.is_file():
                # explorer returns a non-zero exit code even on success, so we
                # fire and forget. The comma after /select is required.
                subprocess.Popen(f'explorer /select,"{p}"')
            else:
                target = p if p.is_dir() else p.parent
                os.startfile(str(target))  # noqa: S606
            return True
        if sys.platform == "darwin":
            if select and p.is_file():
                subprocess.Popen(["open", "-R", str(p)])
            else:
                target = p if p.is_dir() else p.parent
                subprocess.Popen(["open", str(target)])
            return True
        # Linux / other: no reliable "select", just open the containing folder.
        target = p if p.is_dir() else p.parent
        subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception:
        return False
