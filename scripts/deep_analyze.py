"""Deep-inspect already-extracted sample mods and also fix RAR extraction."""
import sys
import subprocess
import shutil
import rarfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SAMPLES_DIR = Path("D:/Development/kotor-mod-installer/mod_samples")


def tree(directory: Path, indent: int = 0, max_depth: int = 5) -> None:
    if indent > max_depth:
        return
    prefix = "  " * indent
    try:
        for item in sorted(directory.iterdir()):
            if item.is_dir():
                print(f"{prefix}[DIR] {item.name}/")
                tree(item, indent + 1, max_depth)
            else:
                size = item.stat().st_size
                print(f"{prefix}{item.name}  ({size:,} bytes)")
    except PermissionError:
        print(f"{prefix}[permission denied]")


def read_file_snippet(path: Path, max_bytes: int = 500) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except Exception:
        return "[unreadable]"


# ---- Inspect extracted mods ----
for mod_dir in sorted(SAMPLES_DIR.iterdir()):
    if not mod_dir.is_dir():
        continue

    # Find extracted subdir (non-archive files)
    extracted_dirs = [d for d in mod_dir.iterdir() if d.is_dir()]
    archives = [f for f in mod_dir.iterdir() if f.suffix.lower() in (".zip", ".7z", ".rar", ".exe")]

    print(f"\n{'='*70}")
    print(f"MOD: {mod_dir.name}")

    if extracted_dirs:
        for ed in extracted_dirs:
            print(f"\n  Extracted dir: {ed.name}/")
            tree(ed, indent=2, max_depth=4)

            # Show changes.ini if present
            for ini in ed.rglob("changes.ini"):
                print(f"\n  --- {ini.relative_to(ed)} ---")
                print(read_file_snippet(ini, 800))

            # Show namespaces.ini if present
            for ini in ed.rglob("namespaces.ini"):
                print(f"\n  --- {ini.relative_to(ed)} (namespaces) ---")
                print(read_file_snippet(ini, 800))

            # Show readme
            for readme in ed.rglob("readme*"):
                print(f"\n  --- README: {readme.relative_to(ed)} ---")
                print(read_file_snippet(readme, 600))
                break
    else:
        print("  (not yet extracted)")

    # Try to unpack RAR archives that failed earlier
    for arch in archives:
        if arch.suffix.lower() == ".rar":
            out = arch.parent / arch.stem
            if out.exists():
                continue
            print(f"\n  Attempting RAR extraction: {arch.name}")
            # Try 7-Zip first
            for cmd in ["7z", "7za", r"C:\Program Files\7-Zip\7z.exe"]:
                if shutil.which(cmd) or Path(cmd).exists():
                    result = subprocess.run(
                        [cmd, "x", str(arch), f"-o{out}", "-y"],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        print(f"  Extracted with {cmd}")
                        tree(out, indent=2, max_depth=4)
                        break
                    else:
                        print(f"  {cmd} failed: {result.stderr[:200]}")
            else:
                # Try rarfile with unrar
                try:
                    rarfile.UNRAR_TOOL = r"C:\Program Files\WinRAR\UnRAR.exe"
                    with rarfile.RarFile(arch) as rf:
                        rf.extractall(out)
                    print(f"  Extracted with rarfile/WinRAR")
                    tree(out, indent=2, max_depth=4)
                except Exception as e:
                    print(f"  All RAR methods failed: {e}")
