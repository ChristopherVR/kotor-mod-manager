"""
Build HoloPatcher and place it where the installer's universal shim looks
(<project>/tools/HoloPatcher/HoloPatcher.exe). The build then bundles it INTO
the distributed .exe, so end users never touch the tools/ folder.

HoloPatcher (part of the PyKotor project) is a headless, open-source
reimplementation of TSLPatcher. Because it reads the exact same tslpatchdata /
changes.ini / namespaces.ini format, one HoloPatcher.exe can install ANY
TSLPatcher mod - old or new - with no GUI and no clicking. This is the
"dynamic patcher" the installer relies on.

We compile it ourselves from a pinned PyKotor commit rather than downloading a
prebuilt release asset. PyKotor removed all of its GitHub Releases, so there is
no asset left to fetch, and building from a pinned source means the patcher we
ship can never change underneath us without a deliberate edit here.

Usage:
    python tools/setup_holopatcher.py                   # clone the pinned source and build
    python tools/setup_holopatcher.py --source <dir>    # build from an existing checkout
    python tools/setup_holopatcher.py --print-ref       # print the pinned PyKotor ref
    python tools/setup_holopatcher.py <local.zip|.exe>  # use a prebuilt patcher instead
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DEST_DIR = Path(__file__).parent / "HoloPatcher"
DEST_EXE = DEST_DIR / "HoloPatcher.exe"

# Where the pinned source is cloned when no --source is given (gitignored).
SOURCE_DIR = Path(__file__).parent / ".pykotor-src"
BUILD_DIR = Path(__file__).parent / ".holopatcher-build"

PYKOTOR_REPO = "https://github.com/NickHugi/PyKotor.git"

# Pinned so the bundled patcher is reproducible. v1.52-patcher is the newest
# stable (non-beta) patcher tag and supports every CLI flag installer/runner.py
# passes: --game-dir, --tslpatchdata, --install, --namespace-option-index.
# Later betas moved to a toga-based UI, which drags in far heavier build deps
# for no gain to us, since we only ever drive it headlessly.
PYKOTOR_REF = "v1.52-patcher"
# The commit that tag pointed at when it was pinned. Tags can be moved, so this
# is checked after cloning; a mismatch stops the build rather than silently
# shipping different code inside our installer.
PYKOTOR_COMMIT = "70749dea9e5c0cb6fca1e5599b95de94a0b107a4"

# Import roots HoloPatcher needs on sys.path, relative to the PyKotor checkout.
SRC_ROOTS = (
    "Libraries/PyKotor/src",
    "Libraries/Utility/src",
    "Tools/HoloPatcher/src",
)
TOOL_SRC = "Tools/HoloPatcher/src"
ENTRY_POINT = "__main__.py"

# PyKotor's only runtime dependency for the patcher path is ply (the nss
# compiler lexer); the rest of what HoloPatcher imports is stdlib + tkinter.
BUILD_REQUIREMENTS = ("pyinstaller>=6", "ply>=3.11,<4")


def _run(cmd: "list[str]", cwd: "Path | None" = None) -> None:
    printable = " ".join(str(c) for c in cmd)
    print(f"$ {printable}" + (f"   (in {cwd})" if cwd else ""))
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


# ---------------------------------------------------------------------------
# Getting the pinned source
# ---------------------------------------------------------------------------

def _clone_pinned_source(dest: Path) -> Path:
    if dest.exists():
        print(f"Removing previous checkout at {dest}")
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Cloning PyKotor at {PYKOTOR_REF}...")
    _run(["git", "clone", "--depth", "1", "--branch", PYKOTOR_REF,
          PYKOTOR_REPO, str(dest)])
    return dest


def _verify_pinned_commit(src: Path) -> bool:
    """Confirm the checkout really is the commit we pinned. Skipped when the
    caller supplied a source tree that is not a git checkout."""
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(src),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        print("Note: could not read the checkout's commit, skipping the pin check.")
        return True
    if head == PYKOTOR_COMMIT:
        print(f"Source pinned at {PYKOTOR_REF} ({head[:12]})")
        return True
    print(f"Refusing to build: expected PyKotor commit {PYKOTOR_COMMIT[:12]} "
          f"({PYKOTOR_REF}) but the checkout is at {head[:12]}.")
    print("If the upstream tag legitimately moved, update PYKOTOR_COMMIT in "
          "this script after reviewing the change.")
    return False


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _install_build_requirements() -> None:
    print("Installing build requirements...")
    _run([sys.executable, "-m", "pip", "install", "--quiet", *BUILD_REQUIREMENTS])


def _build_from_source(src: Path) -> bool:
    missing = [r for r in SRC_ROOTS if not (src / r).is_dir()]
    if missing:
        print(f"Not a usable PyKotor checkout ({src}); missing: {', '.join(missing)}")
        return False

    _install_build_requirements()

    tool_src = src / TOOL_SRC
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    dist_dir = BUILD_DIR / "dist"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",        # one self-contained exe, which is what we embed
        "--console",        # headless CLI, never a windowed app
        "--noconfirm", "--clean",
        "--log-level=WARN",
        "--name", "HoloPatcher",
        "--distpath", str(dist_dir),
        "--workpath", str(BUILD_DIR / "build"),
        "--specpath", str(BUILD_DIR),
    ]
    for root in SRC_ROOTS:
        cmd += ["--paths", str(src / root)]
    cmd.append(ENTRY_POINT)

    print("Compiling HoloPatcher (this takes a minute)...")
    try:
        _run(cmd, cwd=tool_src)
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller failed with exit code {e.returncode}")
        return False

    built = next((p for p in dist_dir.glob("HoloPatcher*") if p.is_file()), None)
    if not built:
        print(f"Build reported success but no executable landed in {dist_dir}")
        return False

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, DEST_EXE)
    if os.name != "nt":
        os.chmod(DEST_EXE, 0o755)
    return True


def _build(source: "str | None") -> int:
    if source:
        src = Path(source).expanduser().resolve()
        if not src.is_dir():
            print(f"Source checkout not found: {src}")
            return 1
        print(f"Building from existing checkout: {src}")
    else:
        try:
            src = _clone_pinned_source(SOURCE_DIR)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"Could not clone PyKotor: {e}")
            return 1

    if not _verify_pinned_commit(src):
        return 1
    if not _build_from_source(src):
        return 1

    size = DEST_EXE.stat().st_size / 1e6
    print(f"HoloPatcher ready at {DEST_EXE} ({size:.1f} MB)")
    return 0


# ---------------------------------------------------------------------------
# Using a prebuilt patcher
# ---------------------------------------------------------------------------

def _extract_exe_from_zip(data: bytes) -> bool:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Find HoloPatcher executable inside the archive.
        exe_member = None
        for info in zf.infolist():
            low = info.filename.lower()
            if low.endswith("holopatcher.exe") or (low.endswith(".exe") and "holopatcher" in low):
                exe_member = info
                break
        if not exe_member:
            # Some archives ship a folder of files; copy the whole thing.
            zf.extractall(DEST_DIR)
            # Try to locate an exe afterwards.
            for p in DEST_DIR.rglob("*.exe"):
                if "holopatcher" in p.name.lower():
                    if p != DEST_EXE:
                        shutil.copy2(p, DEST_EXE)
                    return True
            return False
        with zf.open(exe_member) as src, open(DEST_EXE, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return DEST_EXE.exists()


def _use_local(path: str) -> int:
    src = Path(path)
    if not src.exists():
        print(f"Source not found: {src}")
        return 1
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".zip":
        ok = _extract_exe_from_zip(src.read_bytes())
    else:
        shutil.copy2(src, DEST_EXE)
        ok = True
    print(f"HoloPatcher ready at {DEST_EXE}" if ok else "Could not find HoloPatcher.exe in source")
    return 0 if ok else 1


def main(argv: "list[str]") -> int:
    parser = argparse.ArgumentParser(
        description="Build (or supply) the headless HoloPatcher the installer bundles.")
    parser.add_argument("prebuilt", nargs="?",
                        help="Use this already-built HoloPatcher (.exe or .zip) "
                             "instead of compiling one.")
    parser.add_argument("--source", metavar="DIR",
                        help="Build from an existing PyKotor checkout instead of "
                             "cloning the pinned one.")
    parser.add_argument("--print-ref", action="store_true",
                        help="Print the pinned PyKotor ref and exit.")
    args = parser.parse_args([a for a in argv if a])

    if args.print_ref:
        print(PYKOTOR_REF)
        return 0
    if args.prebuilt:
        return _use_local(args.prebuilt)
    return _build(args.source)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
