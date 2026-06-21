import json
import os
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".kotor_mod_installer"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "kotor1_path": "",
    "kotor2_path": "",
    "download_dir": str(Path.home() / "Downloads" / "KOTOR_Mods"),
    "deadlystream_username": "",
    "neocities_urls": [
        "https://kotor.neocities.org/modding/mod_builds/k1/full",
        "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
        "https://kotor.neocities.org/modding/mod_builds/k2/full",
        "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
    ],
    "auto_install": False,
    "keep_archives": True,
    # Game install profiles — supports multiple KOTOR installs on one machine.
    # Each: {id, name, game ("KOTOR1"|"KOTOR2"), path}. The default profile for
    # a game uses id == game so existing manifests map straight across.
    "game_profiles": [],
    "active_profile": "",
}

DEADLYSTREAM_BASE = "https://deadlystream.com"
DEADLYSTREAM_LOGIN = "https://deadlystream.com/login/"
DEADLYSTREAM_DOWNLOAD = "https://deadlystream.com/files/file/{file_id}/?do=download&csrfKey={csrf_key}"


def load() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save(DEFAULTS.copy())
        return DEFAULTS.copy()
    with open(CONFIG_FILE, encoding="utf-8") as f:
        data = json.load(f)
    merged = {**DEFAULTS, **data}
    if _migrate_profiles(merged):
        save(merged)
    return merged


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Game install profiles
# ---------------------------------------------------------------------------

def _migrate_profiles(cfg: dict) -> bool:
    """Seed default profiles from legacy kotor1_path/kotor2_path. Returns True
    if the config was changed."""
    if cfg.get("game_profiles"):
        return False
    profiles = []
    for game, key, name in (("KOTOR1", "kotor1_path", "KOTOR 1"),
                            ("KOTOR2", "kotor2_path", "KOTOR 2")):
        path = cfg.get(key, "")
        # Default profile id == game so existing <game>.json manifests map across.
        profiles.append({"id": game, "name": name, "game": game, "path": path})
    cfg["game_profiles"] = profiles
    if not cfg.get("active_profile"):
        cfg["active_profile"] = "KOTOR1"
    return True


def get_profiles(cfg: dict | None = None) -> list:
    cfg = cfg or load()
    return cfg.get("game_profiles", [])


def get_profile(profile_id: str, cfg: dict | None = None) -> dict | None:
    for p in get_profiles(cfg):
        if p["id"] == profile_id:
            return p
    return None


def add_profile(name: str, game: str, path: str) -> dict:
    cfg = load()
    prof = {"id": uuid.uuid4().hex[:12], "name": name, "game": game, "path": path}
    cfg.setdefault("game_profiles", []).append(prof)
    # Keep the legacy single-path fields pointing at the first profile per game.
    _sync_legacy_paths(cfg)
    save(cfg)
    return prof


def update_profile(profile_id: str, *, name: str | None = None,
                   path: str | None = None) -> dict | None:
    cfg = load()
    prof = None
    for p in cfg.get("game_profiles", []):
        if p["id"] == profile_id:
            if name is not None:
                p["name"] = name
            if path is not None:
                p["path"] = path
            prof = p
            break
    if prof:
        _sync_legacy_paths(cfg)
        save(cfg)
    return prof


def remove_profile(profile_id: str) -> bool:
    cfg = load()
    before = len(cfg.get("game_profiles", []))
    cfg["game_profiles"] = [p for p in cfg.get("game_profiles", []) if p["id"] != profile_id]
    if cfg.get("active_profile") == profile_id:
        cfg["active_profile"] = cfg["game_profiles"][0]["id"] if cfg["game_profiles"] else ""
    changed = len(cfg["game_profiles"]) != before
    if changed:
        _sync_legacy_paths(cfg)
        save(cfg)
    return changed


def set_active_profile(profile_id: str) -> bool:
    cfg = load()
    if not any(p["id"] == profile_id for p in cfg.get("game_profiles", [])):
        return False
    cfg["active_profile"] = profile_id
    save(cfg)
    return True


def _sync_legacy_paths(cfg: dict) -> None:
    """Mirror the first profile of each game back into kotor1/2_path so the
    legacy curated-install flow keeps working."""
    for game, key in (("KOTOR1", "kotor1_path"), ("KOTOR2", "kotor2_path")):
        prof = next((p for p in cfg.get("game_profiles", []) if p["game"] == game), None)
        if prof:
            cfg[key] = prof["path"]
