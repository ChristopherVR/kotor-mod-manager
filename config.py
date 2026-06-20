import json
import os
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
}

DEADLYSTREAM_BASE = "https://deadlystream.com"
DEADLYSTREAM_LOGIN = "https://deadlystream.com/login/"
DEADLYSTREAM_DOWNLOAD = "https://deadlystream.com/files/file/{file_id}/?do=download&csrfKey={csrf_key}"


def load() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save(DEFAULTS.copy())
        return DEFAULTS.copy()
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    merged = {**DEFAULTS, **data}
    return merged


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
