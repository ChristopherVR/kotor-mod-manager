"""
TSLPatcher GUI automation via Win32 API (ctypes) and optional pywinauto.

Primary strategy: Win32 ctypes — zero extra dependencies, works on all
VB6/Delphi/Win32 patcher versions.

Secondary strategy: pywinauto — better for .NET/UIA-based patchers.
Falls back gracefully if pywinauto is not installed.
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

# Win32 constants
WM_SETTEXT      = 0x000C
WM_GETTEXT      = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_COMMAND      = 0x0111
BM_CLICK        = 0x00F5
BN_CLICKED      = 0
GWL_ID          = -12
WM_CLOSE        = 0x0010

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

ProgressCallback = Callable[[str], None]

PYWINAUTO_AVAILABLE = False
try:
    import pywinauto  # noqa: F401
    PYWINAUTO_AVAILABLE = True
except ImportError:
    pass


class AutomationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def _find_windows(title_substrings: list[str]) -> list[int]:
    """Return HWNDs of top-level windows whose title contains any substring."""
    results: list[int] = []

    def _cb(hwnd: int, _: int) -> bool:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if user32.IsWindowVisible(hwnd) and any(s.lower() in title.lower() for s in title_substrings):
            results.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return results


def _get_window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _enum_children(hwnd: int) -> list[int]:
    children: list[int] = []

    def _cb(child: int, _: int) -> bool:
        children.append(child)
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(_cb), 0)
    return children


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def _get_control_text(hwnd: int) -> str:
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def _set_control_text(hwnd: int, text: str) -> None:
    user32.SendMessageW(hwnd, WM_SETTEXT, 0, text)


def _click_button(hwnd: int) -> None:
    user32.SendMessageW(hwnd, BM_CLICK, 0, 0)


def _get_button_text(hwnd: int) -> str:
    return _get_control_text(hwnd)


def _close_window(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _is_window_alive(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


# ---------------------------------------------------------------------------
# Win32 automation (primary — no extra dependencies)
# ---------------------------------------------------------------------------

def automate_win32(
    exe: Path,
    game_dir: Path,
    config: dict,
    cb: Optional[ProgressCallback] = None,
) -> bool:
    """
    Drive a TSLPatcher window using raw Win32 API.
    Works on VB6, Delphi, and any native Win32 patcher.
    Returns True on success, raises AutomationError on failure.
    """
    if sys.platform != "win32":
        raise AutomationError("Win32 automation is only available on Windows.")

    title_hints    = config.get("window_title_substrings", ["TSL Patcher", "Patcher", "Installer"])
    path_classes   = config.get("path_control_classes", ["TEdit", "Edit", "TMemo"])
    path_index     = config.get("path_control_index", 0)
    install_labels = config.get("install_buttons", ["Install Mod", "Install", "Patch", "Apply"])
    cancel_labels  = [s.lower() for s in config.get("cancel_buttons", ["Cancel", "Exit", "Close", "Quit"])]
    done_titles    = config.get("completion_window_titles", ["Complete", "Success", "Done", "Error"])
    done_texts     = config.get("completion_text_substrings", ["Completed!", "Done.", "Finished"])
    timeout        = config.get("timeout_sec", 300)
    poll_ms        = config.get("poll_interval_ms", 500)
    log_classes    = config.get("read_log_control_classes", ["TMemo", "RichEdit"])

    _cb(f"[Win32] Starting: {exe.name}", cb)

    # Copy game path to clipboard as a user-visible hint
    try:
        subprocess.run(["powershell", "-Command", f"Set-Clipboard '{game_dir}'"],
                       capture_output=True, timeout=5)
    except Exception:
        pass

    # Launch the patcher
    try:
        proc = subprocess.Popen([str(exe), str(game_dir)], cwd=str(exe.parent))
    except Exception as e:
        raise AutomationError(f"Could not launch {exe.name}: {e}")

    pid = proc.pid
    _cb(f"  PID {pid} — waiting for window...", cb)

    # Wait for the patcher window to appear
    patcher_hwnd: Optional[int] = None
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(0.4)
        windows = _find_windows(title_hints)
        for hwnd in windows:
            # Prefer the window belonging to our process (not always possible without extra API)
            patcher_hwnd = hwnd
            break
        if patcher_hwnd:
            break

    if not patcher_hwnd:
        proc.kill()
        raise AutomationError(f"Could not find patcher window. Tried titles: {title_hints}")

    _cb(f"  Window: '{_get_window_title(patcher_hwnd)}'", cb)
    time.sleep(0.5)  # Let the window fully initialise

    # Enumerate child controls
    children = _enum_children(patcher_hwnd)

    # Find the game path field and fill it
    path_controls = [h for h in children if _get_class_name(h) in path_classes]
    if len(path_controls) > path_index:
        _set_control_text(path_controls[path_index], str(game_dir))
        _cb(f"  Set game path in {_get_class_name(path_controls[path_index])}", cb)
    else:
        _cb("  Could not find path field — relying on positional arg / clipboard.", cb)

    time.sleep(0.3)

    # Find and click the install button
    btn_clicked = False
    for hwnd in children:
        cls = _get_class_name(hwnd)
        if cls not in ("Button", "TButton", "TBitBtn"):
            continue
        label = _get_button_text(hwnd).strip()
        if not label:
            continue
        if label.lower() in cancel_labels:
            continue
        if any(install.lower() in label.lower() for install in install_labels):
            _click_button(hwnd)
            _cb(f"  Clicked: '{label}'", cb)
            btn_clicked = True
            break

    if not btn_clicked:
        # Fallback: click first non-cancel button
        for hwnd in children:
            cls = _get_class_name(hwnd)
            if cls not in ("Button", "TButton", "TBitBtn"):
                continue
            label = _get_button_text(hwnd).strip()
            if label and label.lower() not in cancel_labels:
                _click_button(hwnd)
                _cb(f"  Clicked fallback button: '{label}'", cb)
                btn_clicked = True
                break

    if not btn_clicked:
        proc.kill()
        raise AutomationError("Could not find install button in the patcher window.")

    # Monitor progress and wait for completion
    _cb("  Monitoring patcher progress...", cb)
    last_log_line = ""
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(poll_ms / 1000.0)

        # Check if process ended
        if proc.poll() is not None:
            _cb(f"  Patcher exited (code {proc.returncode}).", cb)
            break

        if not _is_window_alive(patcher_hwnd):
            _cb("  Patcher window closed.", cb)
            break

        # Read log control for progress text
        children = _enum_children(patcher_hwnd)
        for hwnd in children:
            if _get_class_name(hwnd) in log_classes:
                text = _get_control_text(hwnd)
                if text:
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    if lines and lines[-1] != last_log_line:
                        last_log_line = lines[-1]
                        _cb(f"  [{exe.name}] {last_log_line}", cb)
                break

        # Check for completion text in log
        if any(done.lower() in last_log_line.lower() for done in done_texts):
            time.sleep(0.5)
            # Dismiss any completion dialog
            completion_windows = _find_windows(done_titles)
            for dlg in completion_windows:
                if dlg != patcher_hwnd:
                    dlg_children = _enum_children(dlg)
                    for btn in dlg_children:
                        if _get_class_name(btn) in ("Button", "TButton"):
                            label = _get_button_text(btn).strip().lower()
                            if label in ("ok", "close", "yes"):
                                _click_button(btn)
                                break
            break

        # Check for a popup completion dialog (different window)
        completion_windows = _find_windows(done_titles)
        for dlg in completion_windows:
            if dlg != patcher_hwnd and _is_window_alive(dlg):
                dlg_title = _get_window_title(dlg)
                _cb(f"  Completion dialog: '{dlg_title}'", cb)
                # Click OK/Close
                dlg_children = _enum_children(dlg)
                for btn in dlg_children:
                    if _get_class_name(btn) in ("Button", "TButton"):
                        label = _get_button_text(btn).strip().lower()
                        if label in ("ok", "close", "yes"):
                            _click_button(btn)
                            break
                break
    else:
        # Timed out — kill the process
        try:
            proc.kill()
        except Exception:
            pass
        raise AutomationError(f"Patcher timed out after {timeout}s for {exe.name}")

    # Close the main window if still alive
    if _is_window_alive(patcher_hwnd):
        _close_window(patcher_hwnd)
        time.sleep(0.8)
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    _cb("[Win32] Automation complete.", cb)
    return True


# ---------------------------------------------------------------------------
# pywinauto automation (secondary — better for .NET / UIA patchers)
# ---------------------------------------------------------------------------

def automate_pywinauto(
    exe: Path,
    game_dir: Path,
    config: dict,
    cb: Optional[ProgressCallback] = None,
) -> bool:
    """
    Drive a patcher GUI via pywinauto.
    Tries win32 backend first, then uia.
    Returns True on success, raises AutomationError on failure.
    """
    if not PYWINAUTO_AVAILABLE:
        raise AutomationError(
            "pywinauto is not installed. Install with: pip install pywinauto"
        )

    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError

    window_re     = config.get("window_title_re", ".*[Pp]atcher.*")
    path_controls = config.get("path_controls", ["TEdit:0", "Edit:0"])
    install_btns  = config.get("install_buttons", ["Install Mod", "Install", "Patch"])
    done_texts    = config.get("completion_text", ["Completed!", "Done.", "Finished"])
    timeout       = config.get("timeout_sec", 300)
    backends      = config.get("backends", ["win32", "uia"])

    _cb(f"[pywinauto] Starting: {exe.name}", cb)

    app = None
    wnd = None
    for backend in backends:
        try:
            app = Application(backend=backend).start(
                str(exe), cwd=str(exe.parent), timeout=15
            )
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    wnd = app.window(title_re=window_re)
                    if wnd.exists(timeout=1):
                        wnd.wait("ready", timeout=10)
                        break
                except ElementNotFoundError:
                    time.sleep(0.3)
            if wnd and wnd.exists():
                _cb(f"  Window found ({backend}): {wnd.window_text()}", cb)
                break
        except Exception as e:
            _cb(f"  Backend {backend} failed: {e}", cb)
            app = None
            wnd = None

    if not wnd or not wnd.exists():
        if app:
            try:
                app.kill()
            except Exception:
                pass
        raise AutomationError(f"Could not find patcher window with pywinauto. Tried: {backends}")

    # Fill game path
    for hint in path_controls:
        try:
            ctrl_type, _, idx_str = hint.partition(":")
            idx = int(idx_str) if idx_str else 0
            controls = [c for c in wnd.children() if c.friendly_class_name() == ctrl_type]
            if idx < len(controls):
                ctrl = controls[idx]
                ctrl.set_focus()
                ctrl.select()
                ctrl.type_keys(str(game_dir), with_spaces=True)
                _cb(f"  Set game path via {ctrl_type}[{idx}]", cb)
                break
        except Exception:
            continue

    time.sleep(0.3)

    # Click install button
    clicked = False
    for label in install_btns:
        try:
            btn = wnd.child_window(title=label, control_type="Button")
            if btn.exists(timeout=2):
                btn.click_input()
                _cb(f"  Clicked: '{label}'", cb)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        try:
            for child in wnd.children():
                if child.friendly_class_name() == "Button":
                    lbl = child.window_text().strip()
                    if lbl and lbl.lower() not in ("cancel", "close", "exit"):
                        child.click_input()
                        _cb(f"  Clicked fallback button: '{lbl}'", cb)
                        clicked = True
                        break
        except Exception as e:
            raise AutomationError(f"Could not click install button: {e}")

    if not clicked:
        try:
            app.kill()
        except Exception:
            pass
        raise AutomationError("Could not find install button via pywinauto")

    # Wait for completion
    _cb("  Waiting for patcher to complete...", cb)
    deadline = time.time() + timeout
    last_text = ""

    while time.time() < deadline:
        time.sleep(0.5)
        try:
            if not app.is_process_running():
                _cb("  Patcher process ended.", cb)
                break

            # Read log (Memo/RichEdit)
            for child in wnd.children():
                fn = child.friendly_class_name()
                if fn in ("TMemo", "RichEdit", "TListBox", "Edit"):
                    try:
                        text = child.window_text()
                        lines = [l.strip() for l in text.splitlines() if l.strip()]
                        if lines and lines[-1] != last_text:
                            last_text = lines[-1]
                            _cb(f"  {last_text}", cb)
                    except Exception:
                        pass

            if any(d.lower() in last_text.lower() for d in done_texts):
                # Dismiss dialogs
                try:
                    top = app.top_window()
                    if top.window_text() != wnd.window_text():
                        for btn_lbl in ["OK", "Close", "Yes"]:
                            try:
                                top.child_window(title=btn_lbl).click_input()
                                break
                            except Exception:
                                pass
                except Exception:
                    pass
                break

        except Exception:
            break

    # Close
    try:
        if app.is_process_running():
            try:
                wnd.close()
            except Exception:
                pass
            time.sleep(0.8)
            if app.is_process_running():
                app.kill()
    except Exception:
        pass

    _cb("[pywinauto] Automation complete.", cb)
    return True


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _cb(msg: str, cb: Optional[ProgressCallback]) -> None:
    if cb:
        cb(msg)
