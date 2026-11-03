"""Archive extraction: zip, 7z, rar, self-extracting exe."""

import os
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from pathlib import Path
from typing import Optional

import config as cfg
from installer.fs_retry import with_lock_retry

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


def _unc(p: Path) -> Path:
    """Return a UNC-prefixed path on Windows to bypass MAX_PATH (260 char) limits."""
    if sys.platform != "win32":
        return p
    resolved = str(p.resolve())
    if resolved.startswith("\\\\"):
        return p
    return Path("\\\\?\\" + resolved)


def _extract_zip(archive: Path, dest: Path) -> None:
    # Opening the archive can briefly fail with WinError 32 if antivirus is still
    # scanning the freshly downloaded file; retry through the transient lock.
    def _open_and_extract() -> None:
        with zipfile.ZipFile(archive, "r") as z:
            z.extractall(dest)
    try:
        with_lock_retry(_open_and_extract)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError):
        # The OS tools may support a ZIP compression method Python does not.
        if not _extract_system_archive(archive, dest, is_zip=True):
            raise


def _run_extractor(args: list[str]) -> bool:
    """A missing, inaccessible or incompatible tool must not block fallbacks."""
    try:
        return subprocess.run(args, capture_output=True).returncode == 0
    except OSError:
        return False


def _extract_system_archive(archive: Path, dest: Path, *, is_zip: bool = False) -> bool:
    """Try available OS tools, without ever launching a downloaded installer.

    Windows ships libarchive-based tar. On Linux use bsdtar if installed, since
    GNU tar cannot read ZIP/7z/RAR. Support depends on the local libarchive build.
    """
    tar = shutil.which("bsdtar")
    if not tar and sys.platform == "win32":
        tar = shutil.which("tar")
        if not tar:
            system_tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
            if system_tar.is_file():
                tar = str(system_tar)
    if tar and _run_extractor([tar, "-xf", str(archive.resolve()), "-C", str(dest.resolve())]):
        return True
    if is_zip:
        unzip = shutil.which("unzip")
        if unzip and _run_extractor([unzip, "-o", str(archive.resolve()), "-d", str(dest.resolve())]):
            return True
    return False


def _extract_7z(archive: Path, dest: Path) -> None:
    # Try system 7z first - it supports more compression methods (BCJ2, etc.)
    # and handles long Windows paths better than py7zr.
    cmd_7z = _find_7z()
    if cmd_7z:
        if _run_extractor([cmd_7z, "x", str(archive), f"-o{dest}", "-y"]):
            return

    if _extract_system_archive(archive, dest):
        return

    if not HAS_7Z:
        raise ExtractionError(
            "Cannot extract .7z files with the available tools. Install 7-Zip "
            "and select its executable in Settings > General > Archive extraction."
        )

    def _open_and_extract() -> None:
        with py7zr.SevenZipFile(archive, mode="r") as z:
            z.extractall(path=_unc(dest))
    try:
        with_lock_retry(_open_and_extract)
    except Exception as e:
        raise ExtractionError(
            f"Cannot extract '{archive.name}': {e}. "
            "Install 7-Zip (https://www.7-zip.org/) and select its executable "
            "in Settings > General > Archive extraction."
        ) from e


_7Z_CANDIDATES = [
    "7z",
    "7za",
    "7zz",
    "7zr",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]

_WINRAR_UNRAR = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    "unrar",
]


def _find_7z() -> str | None:
    custom = cfg.load().get("seven_zip_path", "").strip().strip('"')
    candidates = [custom] if custom else []
    candidates.extend(_7Z_CANDIDATES)
    if sys.platform == "win32":
        # Windows may live on a drive other than C:, or use a per-user install.
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.append(str(Path(base) / "7-Zip" / "7z.exe"))
                if variable == "LOCALAPPDATA":
                    candidates.append(str(Path(base) / "Programs" / "7-Zip" / "7z.exe"))
        # The installer records custom installation directories in the registry.
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\7-Zip", 0, winreg.KEY_READ | view) as key:
                        for name in ("Path", "Path64", "Path32"):
                            try:
                                base, _ = winreg.QueryValueEx(key, name)
                                candidates.append(str(Path(base) / "7z.exe"))
                            except OSError:
                                pass
                except OSError:
                    pass
    for cmd in candidates:
        resolved = shutil.which(cmd)
        if resolved:
            return resolved
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
        if _run_extractor([cmd_7z, "x", str(archive), f"-o{dest}", "-y"]):
            return

    # Try WinRAR/unrar
    unrar = _find_unrar()
    if unrar:
        if _run_extractor([unrar, "x", "-y", str(archive), str(dest) + os.sep]):
            return

    # Linux: unar and bsdtar (libarchive) read RAR, including RAR5. Distro builds
    # of 7-Zip leave the RAR decoder out for licence reasons, so 7z alone is
    # not enough there.
    unar = shutil.which("unar")
    if unar:
        if _run_extractor(
            [unar, "-quiet", "-force-overwrite", "-no-directory", "-output-directory",
             str(dest), str(archive)]
        ):
            return
    if _extract_system_archive(archive, dest):
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

    if sys.platform == "win32":
        tools = "7-Zip (https://www.7-zip.org/), WinRAR, or unrar"
    else:
        tools = ("unar, unrar, bsdtar (package libarchive-tools), or 7-Zip from "
                 "https://www.7-zip.org/ (the 7z in Debian and Ubuntu cannot read RAR)")
    raise ExtractionError(
        f"Cannot extract RAR archive '{archive.name}'. "
        f"Please install one of the following tools: {tools}. "
        "You can select 7-Zip in Settings > General > Archive extraction."
    )


def _extract_self_extracting_exe(archive: Path, dest: Path) -> None:
    """Unpack a self-extracting .exe without executing it."""
    # Use the same lookup as .7z/.rar extraction: a standard 7-Zip install
    # lives in Program Files and is NOT on PATH, so a which()-only check
    # would fail on most player machines.
    cmd_7z = _find_7z()
    if cmd_7z:
        if _run_extractor([cmd_7z, "x", str(archive), f"-o{dest}", "-y"]):
            return
    # ZIP-based SFX files are readable by Python on both Windows and Linux.
    if zipfile.is_zipfile(archive):
        _extract_zip(archive, _unc(dest))
        return
    if _extract_system_archive(archive, dest):
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
        "Install 7-Zip (https://www.7-zip.org/), then select 7z.exe (Windows) "
        "or 7zz/7z (Linux) in Settings > General > Archive extraction. "
        "You do not need to change PATH. Built-in extraction cannot read every installer format."
    )


# File types that mean "this folder actually contains mod content".
_PAYLOAD_SUFFIXES = {
    ".tga", ".tpc", ".dds", ".txi", ".mdl", ".mdx", ".2da", ".tlk", ".gui",
    ".utc", ".uti", ".utp", ".uts", ".utt", ".utm", ".utd", ".ute", ".utw",
    ".dlg", ".ncs", ".nss", ".mod", ".rim", ".erf", ".wav", ".mp3", ".bik",
    ".lip", ".ssf", ".ini", ".exe",
}
_NESTED_ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}


def has_mod_payload(root: Path) -> bool:
    """
    Whether an extracted folder holds anything installable.

    Used to decide if a nested archive still needs unpacking: a folder with only
    a readme and a screenshot is not a mod, it is a wrapper around one.
    """
    try:
        for p in root.rglob("*"):
            if p.is_dir() and p.name.lower() == "tslpatchdata":
                return True
            if p.is_file() and p.suffix.lower() in _PAYLOAD_SUFFIXES:
                return True
    except OSError:
        pass
    return False


def _extract_nested(dest: Path, depth: int = 0) -> None:
    """
    Unpack archives found inside an extraction that produced no mod content.

    Some submissions wrap the real mod in a second archive (Effixian's Qel-Droma
    Robes ships a .zip inside the .zip). Without this the detector sees only a
    readme and reports the mod as needing a manual install.

    Deliberately conservative: this only runs when nothing installable was found,
    so a mod that legitimately ships an optional extra archive alongside its real
    payload is left untouched. Depth-limited so a nest of archives cannot loop.
    """
    if depth >= 3 or has_mod_payload(dest):
        return
    try:
        nested = [p for p in dest.rglob("*")
                  if p.is_file() and p.suffix.lower() in _NESTED_ARCHIVE_SUFFIXES]
    except OSError:
        return
    if not nested:
        return
    for inner in nested:
        try:
            extract(inner, inner.parent / urllib.parse.unquote(inner.stem))
        except Exception:
            continue  # a nested archive we cannot read is not fatal
    _extract_nested(dest, depth + 1)


def extract(archive: Path, dest: Optional[Path] = None) -> Path:
    """
    Extract an archive to dest (defaults to archive_name/ next to the archive).
    Returns the extraction directory.
    """
    if dest is None:
        stem = archive.stem
        if stem.endswith(".tar"):
            stem = stem[:-4]
        # URL-decode the stem so %5BK1%5D becomes [K1], reducing nested path length.
        stem = urllib.parse.unquote(stem)
        dest = archive.parent / stem

    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()

    if suffix == ".zip":
        _extract_zip(archive, _unc(dest))
    elif suffix == ".7z":
        _extract_7z(archive, dest)
    elif suffix == ".rar":
        _extract_rar(archive, dest)
    elif suffix == ".exe":
        _extract_self_extracting_exe(archive, dest)
    else:
        # Try zip first (many mods use .zip regardless of extension)
        try:
            _extract_zip(archive, _unc(dest))
        except zipfile.BadZipFile:
            try:
                _extract_7z(archive, dest)
            except Exception as e:
                raise ExtractionError(
                    f"Cannot extract '{archive.name}': {e}"
                ) from e

    # A wrapper archive yields no installable files; unpack what is inside it.
    _extract_nested(dest)

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
