"""
Case-insensitive paths for the game folder.

Windows treats "Override" and "override" as the same folder; Linux (Steam
Proton) does not, so a mod's "Override/Foo.tga" would sit beside an existing
"override/foo.tga" instead of replacing it. Game-folder paths go through here so
the name already on disk wins. On Windows and macOS this is a plain join.
"""
import sys
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]

_CASE_SENSITIVE_FS = sys.platform not in ("win32", "darwin")


class CaseResolver:
    """Resolves paths under ``base`` against what is on disk.

    Folder listings are cached, so use one instance per operation.
    """

    def __init__(self, base: PathLike) -> None:
        self.base = Path(base)
        self._listings: "dict[Path, dict[str, str]]" = {}

    def _names(self, folder: Path) -> "dict[str, str]":
        names = self._listings.get(folder)
        if names is None:
            try:
                names = {c.name.lower(): c.name for c in folder.iterdir()}
            except OSError:
                names = {}
            self._listings[folder] = names
        return names

    def resolve(self, rel: PathLike) -> Path:
        """``base / rel`` with the casing already on disk. New names keep the
        caller's casing and are remembered for later lookups."""
        parts = [p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
        if not _CASE_SENSITIVE_FS:
            return self.base.joinpath(*parts)
        cur = self.base
        for part in parts:
            names = self._names(cur)
            real = names.get(part.lower())
            if real is None:
                names[part.lower()] = part
                real = part
            cur = cur / real
        return cur


def resolve_ci(base: PathLike, rel: PathLike) -> Path:
    """One-off form of :meth:`CaseResolver.resolve`."""
    return CaseResolver(base).resolve(rel)


def rglob_ci(root: PathLike, pattern: str):
    """Case-insensitive ``Path.rglob``: "*.exe" also finds "Setup.EXE"."""
    import fnmatch
    pat = pattern.lower()
    for p in walk_sorted(root):
        if fnmatch.fnmatchcase(p.name.lower(), pat):
            yield p


def walk_sorted(root: PathLike):
    """Every path under ``root``, sorted by name. NTFS lists alphabetically but
    Linux does not, and "first match" lookups must agree on both."""
    key = lambda q: q.name.lower()
    try:
        entries = sorted(Path(root).iterdir(), key=key)
    except OSError:
        return
    for e in entries:
        yield e
        try:
            is_dir = e.is_dir() and not e.is_symlink()
        except OSError:
            is_dir = False
        if is_dir:
            yield from walk_sorted(e)
