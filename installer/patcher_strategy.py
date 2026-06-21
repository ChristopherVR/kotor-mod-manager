"""
Patcher execution strategy cascade.

For a TSLPatcher-style mod we try a sequence of strategies, falling through to
the next whenever one is unavailable or fails:

  1. holopatcher_shim     - run a system HoloPatcher.exe headlessly against the
                            mod's tslpatchdata/ (HoloPatcher is a headless
                            reimplementation of TSLPatcher and reads the exact
                            same changes.ini / namespaces.ini format). This is
                            the "dynamic patcher": one universal engine that
                            installs ANY TSLPatcher mod - old or new - with no
                            GUI and no per-mod clicking.
  2. win32_automation     - drive the real TSLPatcher.exe GUI via raw Win32 API
                            (ctypes): fill the path field, click Install, watch
                            the log, dismiss the completion dialog.
  3. pywinauto_automation - same idea via pywinauto (handles .NET / UIA GUIs).
  4. gui_manual           - launch the GUI, copy the path to clipboard, and let
                            the user click once (the original behaviour).

Everything is configured from installer_config.json so new patcher quirks /
versions can be supported without code changes.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from installer.config_loader import (
    find_system_holopatcher,
    get_strategy_config,
    get_execution_config,
)
from installer.runner import PatcherError, run_holopatcher, run_tslpatcher
from installer import ui_automation

ProgressCallback = Callable[[str], None]


@dataclass
class StrategyResult:
    success: bool
    strategy: str
    needs_user_gui: bool = False   # True only for gui_manual fallback
    message: str = ""


def _log(msg: str, cb: Optional[ProgressCallback]) -> None:
    if cb:
        cb(msg)


# ---------------------------------------------------------------------------
# tslpatchdata / namespace resolution
# ---------------------------------------------------------------------------

def _find_tslpatchdata(mod_root: Path, exe: Optional[Path]) -> Optional[Path]:
    """Locate the tslpatchdata directory for a mod."""
    # Next to the exe is the common case
    if exe:
        candidate = exe.parent / "tslpatchdata"
        if candidate.is_dir():
            return candidate
    # Search the mod tree
    for p in mod_root.rglob("tslpatchdata"):
        if p.is_dir():
            return p
    # Some very old mods put changes.ini at root with no tslpatchdata folder
    if (mod_root / "changes.ini").exists():
        return mod_root
    return None


def _parse_namespace_options(tslpatchdata: Path) -> list[tuple[str, str]]:
    """
    Return [(key, name), ...] from namespaces.ini, in declared order.
    Empty list means a single default install (changes.ini).
    """
    ns_ini = tslpatchdata / "namespaces.ini"
    if not ns_ini.exists():
        return []
    try:
        text = ns_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    ns_section = re.search(r"\[Namespaces\](.*?)(?=\n\[|\Z)", text, re.S | re.I)
    if not ns_section:
        return []
    keys = re.findall(r"^\s*Namespace\d+\s*=\s*(\S+)", ns_section.group(1), re.M | re.I)

    options: list[tuple[str, str]] = []
    for key in keys:
        section = re.search(rf"\[{re.escape(key)}\](.*?)(?=\n\[|\Z)", text, re.S)
        name = key
        if section:
            nm = re.search(r"^\s*Name\s*=\s*(.+)$", section.group(1), re.M | re.I)
            if nm:
                name = nm.group(1).strip()
        options.append((key, name))
    return options


def resolve_namespace_index(tslpatchdata: Path, option_hint: str,
                            cb: Optional[ProgressCallback] = None) -> int:
    """
    Choose a namespace index from the build-page hint. Returns 0 (default)
    when there is no match or only a single option.
    """
    options = _parse_namespace_options(tslpatchdata)
    if len(options) <= 1:
        return 0
    if option_hint:
        hint = option_hint.replace("_", " ").lower()
        for i, (key, name) in enumerate(options):
            if hint in name.lower() or hint in key.lower():
                _log(f"    Namespace match: '{name}' (index {i})", cb)
                return i
    _log(f"    Namespace: '{options[0][1]}' (default, {len(options)} options)", cb)
    return 0


# ---------------------------------------------------------------------------
# Individual strategies
# ---------------------------------------------------------------------------

def _try_holopatcher_shim(
    mod_root: Path,
    exe: Optional[Path],
    game_dir: Path,
    option_hint: str,
    cb: Optional[ProgressCallback],
) -> StrategyResult:
    holo = find_system_holopatcher()
    if not holo:
        raise PatcherError("No system HoloPatcher available for shim")

    tslpatchdata = _find_tslpatchdata(mod_root, exe)
    if not tslpatchdata:
        raise PatcherError("No tslpatchdata/ found for HoloPatcher shim")

    ns_index = resolve_namespace_index(tslpatchdata, option_hint, cb)
    _log(f"  [shim] Using headless HoloPatcher: {holo.name}", cb)
    run_holopatcher(holo, game_dir, tslpatchdata, ns_index, cb)
    return StrategyResult(True, "holopatcher_shim")


def _try_win32_automation(
    exe: Path,
    game_dir: Path,
    cb: Optional[ProgressCallback],
) -> StrategyResult:
    cfg = get_strategy_config("tslpatcher", "win32_automation")
    if not cfg.get("enabled", True):
        raise PatcherError("win32_automation disabled in config")
    if not exe or not exe.exists():
        raise PatcherError("TSLPatcher.exe not found for win32 automation")
    ui_automation.automate_win32(exe, game_dir, cfg, cb)
    return StrategyResult(True, "win32_automation")


def _try_pywinauto_automation(
    exe: Path,
    game_dir: Path,
    cb: Optional[ProgressCallback],
) -> StrategyResult:
    cfg = get_strategy_config("tslpatcher", "pywinauto_automation")
    if not cfg.get("enabled", True):
        raise PatcherError("pywinauto_automation disabled in config")
    if not ui_automation.PYWINAUTO_AVAILABLE:
        raise PatcherError("pywinauto not installed")
    if not exe or not exe.exists():
        raise PatcherError("TSLPatcher.exe not found for pywinauto automation")
    ui_automation.automate_pywinauto(exe, game_dir, cfg, cb)
    return StrategyResult(True, "pywinauto_automation")


def _try_gui_manual(
    exe: Path,
    game_dir: Path,
    cb: Optional[ProgressCallback],
    on_waiting: Optional[Callable[[], None]],
) -> StrategyResult:
    if not exe or not exe.exists():
        raise PatcherError("TSLPatcher.exe not found for manual GUI")
    run_tslpatcher(exe, game_dir, cb, on_waiting)
    return StrategyResult(True, "gui_manual", needs_user_gui=True)


# ---------------------------------------------------------------------------
# Cascade orchestrator
# ---------------------------------------------------------------------------

_STRATEGY_ORDER_DEFAULT = [
    "holopatcher_shim",
    "win32_automation",
    "pywinauto_automation",
    "gui_manual",
]


def run_tslpatcher_cascade(
    mod_root: Path,
    exe: Optional[Path],
    game_dir: Path,
    option_hint: str = "",
    cb: Optional[ProgressCallback] = None,
    on_waiting: Optional[Callable[[], None]] = None,
    allow_manual: bool = True,
) -> StrategyResult:
    """
    Execute a TSLPatcher mod using the configured strategy cascade.

    mod_root:   extracted mod directory
    exe:        the mod's own TSLPatcher.exe (may be None for shim-only installs)
    game_dir:   KOTOR install root
    option_hint: build-page hint for namespace selection
    on_waiting: called if we fall back to gui_manual (UI shows a banner)
    allow_manual: if False, never fall back to the GUI (fully unattended runs)

    Returns the StrategyResult of the first strategy that succeeds.
    Raises PatcherError if every strategy fails.
    """
    order = get_execution_config("tslpatcher").get("strategies", _STRATEGY_ORDER_DEFAULT)

    errors: list[str] = []
    for strategy in order:
        if strategy == "gui_manual" and not allow_manual:
            continue
        try:
            _log(f"  → Strategy: {strategy}", cb)
            if strategy == "holopatcher_shim":
                return _try_holopatcher_shim(mod_root, exe, game_dir, option_hint, cb)
            elif strategy == "win32_automation":
                return _try_win32_automation(exe, game_dir, cb)
            elif strategy == "pywinauto_automation":
                return _try_pywinauto_automation(exe, game_dir, cb)
            elif strategy == "gui_manual":
                return _try_gui_manual(exe, game_dir, cb, on_waiting)
            else:
                _log(f"  Unknown strategy '{strategy}' - skipping", cb)
        except ui_automation.AutomationError as e:
            errors.append(f"{strategy}: {e}")
            _log(f"  ✗ {strategy} failed: {e}", cb)
        except PatcherError as e:
            errors.append(f"{strategy}: {e}")
            _log(f"  ✗ {strategy} unavailable: {e}", cb)
        except Exception as e:
            errors.append(f"{strategy}: {e}")
            _log(f"  ✗ {strategy} error: {e}", cb)

    raise PatcherError(
        "All TSLPatcher strategies failed:\n  " + "\n  ".join(errors)
    )
