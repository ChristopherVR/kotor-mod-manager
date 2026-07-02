"""
Low-level patcher runners.
- HoloPatcher: fully headless via CLI flags
- TSLPatcher: GUI launch with game path pre-filled (user clicks Install once)
"""
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Callable[[str], None]


class PatcherError(Exception):
    pass


def _log(msg: str, cb: Optional[ProgressCallback]) -> None:
    if cb:
        cb(msg)


# HoloPatcher (and the pykotor engine it wraps) reports fatal problems in its
# output but can still exit 0/1, so a clean exit code is NOT proof of success.
# Treat any of these signatures in stdout/stderr as a hard failure.
_HOLO_ERROR_MARKERS = (
    "is not a valid installation",
    "[error]",
    "traceback (most recent call last)",
    "runtimeerror:",
    "filenotfounderror:",
    "permissionerror:",
    "cannot initialize modinstaller",
    "failed to install",
    "installation failed",
)

# Lines matching these are noise even though they contain a marker substring
# (e.g. a summary line reporting "0 errors").
_HOLO_ERROR_IGNORE = (
    "0 errors",
    "no errors",
    "errors: 0",
)


def _scan_patcher_output(text: str) -> Optional[str]:
    """Return the first meaningful error line in patcher output, else None."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if any(ok in low for ok in _HOLO_ERROR_IGNORE):
            continue
        if any(marker in low for marker in _HOLO_ERROR_MARKERS):
            return line
    return None


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
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Run HoloPatcher headlessly, streaming its output line by line to cb.
    namespace_index: 0-based index into namespaces.ini options.
    stop_event: when set, terminates the subprocess and raises PatcherError.
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
        proc = subprocess.Popen(
            cmd,
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,  # HoloPatcher shells out to nwnnsscomp.exe,
            # which inherits our stdin handle; an unset/invalid one here causes
            # "OSError: [WinError 6] The handle is invalid" in that grandchild.
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr so one stream to read
            text=True,
            errors="replace",
        )
    except FileNotFoundError:
        raise PatcherError(f"Could not launch HoloPatcher: {exe}")

    all_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            stripped = raw_line.rstrip()
            if stripped:
                _log(f"  {stripped}", cb)
                all_lines.append(stripped)
            if stop_event and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise PatcherError("Installation cancelled.")
    except PatcherError:
        raise
    except Exception as e:
        proc.kill()
        raise PatcherError(f"Error reading HoloPatcher output: {e}") from e

    try:
        proc.wait(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        proc.kill()
        raise PatcherError(f"HoloPatcher timed out after {timeout}s")

    combined = "\n".join(all_lines)

    # A non-zero (other than 1 = "completed with warnings") exit is a failure.
    if proc.returncode not in (0, 1):
        raise PatcherError(
            f"HoloPatcher exited with code {proc.returncode}.\n"
            f"{combined[-400:]}"
        )

    # Even on a 0/1 exit, HoloPatcher may have logged a fatal error (e.g. an
    # invalid game directory). Surface it instead of falsely reporting success.
    err_line = _scan_patcher_output(combined)
    if err_line:
        raise PatcherError(f"HoloPatcher reported an error: {err_line}")

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
