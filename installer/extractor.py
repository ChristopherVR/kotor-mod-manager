"""Archive extraction: zip, 7z, rar, self-extracting exe."""

import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

try:
    import rarfile
    HAS_RAR = True
except ImportError:
    HAS_RAR = False


class ExtractionError(Exception):
    pass


def _extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive, "r") as z:
        z.extractall(dest)


def _extract_7z(archive: Path, dest: Path) -> None:
    if not HAS_7Z:
        raise ExtractionError("py7zr is not installed - cannot extract .7z files.")
    with py7zr.SevenZipFile(archive, mode="r") as z:
        z.extractall(path=dest)


_7Z_CANDIDATES = [
    "7z",
    "7za",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]

_WINRAR_UNRAR = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    "unrar",
]


def _find_7z() -> str | None:
    for cmd in _7Z_CANDIDATES:
        if shutil.which(cmd) or Path(cmd).exists():
            return cmd
    return None


def _find_unrar() -> str | None:
    for cmd in _WINRAR_UNRAR:
        if shutil.which(cmd) or Path(cmd).exists():
            return cmd
    return None


def _extract_rar(archive: Path, dest: Path) -> None:
    # Try 7-Zip first (handles most RAR files)
    cmd_7z = _find_7z()
    if cmd_7z:
        result = subprocess.run(
            [cmd_7z, "x", str(archive), f"-o{dest}", "-y"],
            capture_output=True
        )
        if result.returncode == 0:
            return

    # Try WinRAR/unrar
    unrar = _find_unrar()
    if unrar:
        result = subprocess.run(
            [unrar, "x", "-y", str(archive), str(dest) + "\\"],
            capture_output=True
        )
        if result.returncode == 0:
            return

    # Try rarfile library
    if HAS_RAR:
        unrar_tool = _find_unrar()
        if unrar_tool:
            rarfile.UNRAR_TOOL = unrar_tool
        try:
            with rarfile.RarFile(archive) as r:
                r.extractall(dest)
            return
        except Exception:
            pass

    # Try py7zr as last resort (sometimes handles RAR3)
    if HAS_7Z:
        try:
            with py7zr.SevenZipFile(archive, mode="r") as z:
                z.extractall(path=dest)
            return
        except Exception:
            pass

    raise ExtractionError(
        f"Cannot extract RAR archive '{archive.name}'. "
        "Install 7-Zip (https://www.7-zip.org/) and ensure 7z.exe is on your PATH, "
        "or install WinRAR."
    )


def _extract_self_extracting_exe(archive: Path, dest: Path) -> None:
    """Try to unpack a self-extracting .exe with 7z."""
    for cmd in ["7z", "7za"]:
        if shutil.which(cmd):
            result = subprocess.run(
                [cmd, "x", str(archive), f"-o{dest}", "-y"],
                capture_output=True
            )
            if result.returncode == 0:
                return
    if HAS_7Z:
        try:
            with py7zr.SevenZipFile(archive, mode="r") as z:
                z.extractall(path=dest)
            return
        except Exception:
            pass
    raise ExtractionError(
        f"Cannot extract self-extracting EXE '{archive.name}'. "
        "Install 7-Zip and ensure 7z.exe is on your PATH."
    )


def extract(archive: Path, dest: Optional[Path] = None) -> Path:
    """
    Extract an archive to dest (defaults to archive_name/ next to the archive).
    Returns the extraction directory.
    """
    if dest is None:
        # Strip extension(s) - handle .tar.gz etc
        stem = archive.stem
        if stem.endswith(".tar"):
            stem = stem[:-4]
        dest = archive.parent / stem

    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()

    if suffix == ".zip":
        _extract_zip(archive, dest)
    elif suffix == ".7z":
        _extract_7z(archive, dest)
    elif suffix == ".rar":
        _extract_rar(archive, dest)
    elif suffix == ".exe":
        _extract_self_extracting_exe(archive, dest)
    else:
        # Try zip first (many mods use .zip regardless of extension)
        try:
            _extract_zip(archive, dest)
        except zipfile.BadZipFile:
            if HAS_7Z:
                _extract_7z(archive, dest)
            else:
                raise ExtractionError(f"Unsupported archive format: {suffix}")

    return dest


def detect_archive_format(path: Path) -> str:
    """Return the likely archive format by reading magic bytes."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        return "unknown"

    if header[:2] == b"PK":
        return "zip"
    if header[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if header[:7] == b"Rar!\x1a\x07":
        return "rar"
    if header[:2] == b"MZ":
        return "exe"
    return "unknown"
