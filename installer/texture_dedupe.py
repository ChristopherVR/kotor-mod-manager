"""
Remove duplicate texture files from Override.

When a build installs many texture packs, the same texture can end up present as
both a .tga and a .tpc. KOTOR's resource loader does not pick between them
consistently: in some situations the .tpc wins, and where the two files disagree
the game can crash. The KOTOR 1 build guides therefore make removing these pairs
a mandatory final step (entry 175 of the K1 Spoiler-Free build, which ships a
DelDuplicateTGA-TPC .bat for Windows and a shell script for Linux).

Their tool deletes the .tpc side and keeps the .tga, so this does the same.

.dds is handled separately by the pipeline's own post-install sweep, which drops
a stale .tpc/.tga when a mod installs a .dds of the same name.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Extension kept, versus the extensions removed when a same-stem clash exists.
KEEP_EXT = ".tga"
DROP_EXTS = (".tpc",)


@dataclass
class DedupeResult:
    removed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    scanned: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed


def find_duplicates(override_dir: Path) -> dict[str, dict[str, Path]]:
    """
    Map stem -> {extension: path} for every stem that exists under more than one
    of the texture extensions we care about. Matching is case-insensitive, since
    KOTOR mods are wildly inconsistent about casing.
    """
    seen: dict[str, dict[str, Path]] = {}
    if not override_dir.is_dir():
        return {}
    for f in override_dir.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext != KEEP_EXT and ext not in DROP_EXTS:
            continue
        seen.setdefault(f.stem.lower(), {})[ext] = f
    return {
        stem: exts for stem, exts in seen.items()
        if KEEP_EXT in exts and any(e in exts for e in DROP_EXTS)
    }


def dedupe(override_dir: Path, dry_run: bool = False,
           on_log: Optional[Callable[[str], None]] = None) -> DedupeResult:
    """
    Delete the .tpc side of every .tga/.tpc pair in Override.

    dry_run reports what would go without touching anything, so the count can be
    shown to the player before they commit to it.
    """
    result = DedupeResult()
    dupes = find_duplicates(override_dir)
    result.scanned = len(dupes)
    for stem in sorted(dupes):
        for ext in DROP_EXTS:
            target = dupes[stem].get(ext)
            if target is None:
                continue
            if dry_run:
                result.removed.append(target.name)
                continue
            try:
                target.unlink()
                result.removed.append(target.name)
            except OSError as e:
                result.failed.append((target.name, str(e)))
    if on_log:
        verb = "Would remove" if dry_run else "Removed"
        on_log(f"{verb} {len(result.removed)} duplicate .tpc file(s) "
               f"across {result.scanned} clashing texture name(s).")
        for name, err in result.failed:
            on_log(f"  Could not remove {name}: {err}")
    return result
