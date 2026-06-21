"""
Low-level patcher runners.
- HoloPatcher: fully headless via CLI flags
- TSLPatcher: GUI launch with game path pre-filled (user clicks Install once)
"""
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Callable[[str], None]


class PatcherError(Exception):
    pass


def _log(msg: str, cb: Optional[ProgressCallback]) -> None:
    if cb:
        cb(msg)


# ------------------------------------------------------------------
# HoloPatcher - fully headless
# ------------------------------------------------------------------

def run_holopatcher(
    exe: Path,
    game_dir: Path,
    tslpatchdata_dir: Path,
    namespace_index: int = 0,
    cb: Optional[ProgressCallback] = None,
    timeout: int = 600,
) -> None:
    """
    Run HoloPatcher headlessly.
    namespace_index: 0-based index into namespaces.ini options.
    Note: index 0 is falsy in HoloPatcher's argparse check, so we omit the
    flag for index 0 and pass it only for index > 0.
    """
    if not exe.exists():
        raise PatcherError(f"HoloPatcher not found: {exe}")

    cmd = [
        str(exe),
        "--game-dir", str(game_dir),
        "--tslpatchdata", str(tslpatchdata_dir),
        "--install",
    ]
    if namespace_index > 0:
        cmd += ["--namespace-option-index", str(namespace_index)]

    _log(f"[HoloPatcher] {exe.name} --game-dir \"{game_dir}\" --install", cb)
    if namespace_index > 0:
        _log(f"  namespace index: {namespace_index}", cb)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(exe.parent),
            timeout=timeout,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise PatcherError(f"HoloPatcher timed out after {timeout}s")
    except FileNotFoundError:
        raise PatcherError(f"Could not launch HoloPatcher: {exe}")

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        for line in stdout.splitlines()[-20:]:
            _log(f"  {line}", cb)
    if result.returncode not in (0, 1):
        # Exit code 1 = completed with warnings (acceptable)
        _log(f"  [stderr] {stderr[:300]}", cb)
        raise PatcherError(
            f"HoloPatcher exited with code {result.returncode}.\n"
            f"{stderr[:400]}"
        )
    _log("[HoloPatcher] Complete.", cb)


# ------------------------------------------------------------------
# TSLPatcher - GUI (unavoidable), game path pre-filled + clipboard
# ------------------------------------------------------------------

def run_tslpatcher(
    exe: Path,
    game_dir: Path,
    cb: Optional[ProgressCallback] = None,
    on_waiting: Optional[Callable[[], None]] = None,
) -> None:
    """
    Launch TSLPatcher.exe and wait for it to close.
    Copies game_dir to clipboard so user can paste into the path field.
    on_waiting: called once the process is running (use to show a UI banner).
    """
    if not exe.exists():
        raise PatcherError(f"TSLPatcher.exe not found: {exe}")

    # Copy game path to clipboard so user can paste
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard '{game_dir}'"],
                capture_output=True, timeout=5
            )
    except Exception:
        pass

    # TSLPatcher.exe accepts the game path as first positional argument
    # (pre-fills the path field in the GUI, but still requires user to click Install)
    cmd = [str(exe), str(game_dir)]

    _log(f"[TSLPatcher] Launching {exe.name}...", cb)
    _log(f"  Game path copied to clipboard: {game_dir}", cb)
    _log(f"  Click 'Install Mod' in the patcher window, then close it.", cb)

    try:
        proc = subprocess.Popen(cmd, cwd=str(exe.parent))
    except FileNotFoundError:
        raise PatcherError(f"Could not launch TSLPatcher: {exe}")

    if on_waiting:
        on_waiting()

    proc.wait()
    _log(f"[TSLPatcher] Closed (exit {proc.returncode}).", cb)
