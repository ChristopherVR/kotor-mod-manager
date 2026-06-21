"""
Loads installer_config.json and resolves runtime resources such as a
system-wide HoloPatcher executable used as a universal TSLPatcher shim.

The config is intentionally data-driven so new patcher types / quirks can be
added without touching code.
"""

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _bundle_root() -> Path:
    """Root for bundled read-only resources (PyInstaller _MEIPASS when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent.parent


def app_dir() -> Path:
    """
    Directory the application lives in. For a frozen build this is the folder
    containing the .exe, so users can drop tools/HoloPatcher/ next to it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


# Bundled config travels inside the package / _MEIPASS as installer/installer_config.json
_CONFIG_PATH = _bundle_root() / "installer" / "installer_config.json"
_USER_CONFIG_PATH = Path.home() / ".kotor_mod_installer" / "installer_config.json"


_DEFAULT_CONFIG = {
    "_version": 1,
    "holopatcher_search_paths": [
        "HoloPatcher.exe",
        "HoloPatcher/HoloPatcher.exe",
    ],
    "installer_types": {},
}


@lru_cache(maxsize=1)
def load_config() -> dict:
    """
    Load installer config. A user override at
    ~/.kotor_mod_installer/installer_config.json is merged on top of the
    bundled default so users can customise without editing package files.
    """
    config = dict(_DEFAULT_CONFIG)

    if _CONFIG_PATH.exists():
        try:
            config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[config] Failed to read bundled config: {e}", file=sys.stderr)

    if _USER_CONFIG_PATH.exists():
        try:
            user = json.loads(_USER_CONFIG_PATH.read_text(encoding="utf-8"))
            config = _deep_merge(config, user)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[config] Failed to read user config: {e}", file=sys.stderr)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_installer_type(type_key: str) -> dict:
    """Return the config block for an installer type (e.g. 'tslpatcher')."""
    return load_config().get("installer_types", {}).get(type_key, {})


def get_execution_config(type_key: str) -> dict:
    return get_installer_type(type_key).get("execution", {})


def get_strategy_config(type_key: str, strategy: str) -> dict:
    """Return the sub-config for a named cascade strategy."""
    return get_execution_config(type_key).get(strategy, {})


def legacy_tslpatcher_exe_names() -> list[str]:
    """All known patcher executable names (current + legacy)."""
    det = get_installer_type("tslpatcher").get("detection", {})
    names = det.get("exe_names", ["TSLPatcher.exe"])
    return names


# ---------------------------------------------------------------------------
# HoloPatcher shim discovery - the universal headless engine
# ---------------------------------------------------------------------------

# Allow an environment override for power users / portable installs.
_ENV_HOLOPATCHER = "KOTOR_HOLOPATCHER_EXE"


def find_system_holopatcher() -> Optional[Path]:
    """
    Locate a system-wide HoloPatcher executable to use as a universal
    headless shim for ANY TSLPatcher mod (since HoloPatcher consumes the
    same tslpatchdata/changes.ini/namespaces.ini format).

    Search order:
      1. KOTOR_HOLOPATCHER_EXE environment variable
      2. Paths listed in installer_config.json -> holopatcher_search_paths
      3. A bundled copy under <project>/tools/HoloPatcher/
    """
    # 1. Environment override
    env = os.environ.get(_ENV_HOLOPATCHER)
    if env:
        p = Path(env)
        if p.exists():
            return p

    # 2. User-configured custom patcher (Settings → Patcher)
    try:
        import config as _appcfg
        custom = _appcfg.load().get("custom_patcher_path", "")
        if custom and Path(custom).exists():
            return Path(custom)
    except Exception:
        pass

    config = load_config()
    search = config.get("holopatcher_search_paths", [])

    # Roots to resolve relative search paths against, in priority order:
    #   1. _bundle_root() - HoloPatcher bundled INSIDE the frozen exe (_MEIPASS)
    #   2. app_dir()      - a copy dropped next to the .exe
    #   3. user data dir
    base = app_dir()
    bundle = _bundle_root()
    roots = [
        bundle / "tools" / "HoloPatcher",
        bundle / "tools",
        base / "tools" / "HoloPatcher",
        base / "tools",
        base,
        Path.home() / ".kotor_mod_installer" / "tools" / "HoloPatcher",
        Path.home() / ".kotor_mod_installer" / "tools",
    ]

    for candidate in search:
        cp = Path(candidate)
        if cp.is_absolute():
            if cp.exists():
                return cp
        else:
            for root in roots:
                resolved = root / cp
                if resolved.exists():
                    return resolved

    return None


def has_holopatcher_shim() -> bool:
    return find_system_holopatcher() is not None
