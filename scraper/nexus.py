"""
Nexus Mods integration.

The official public API (api.nexusmods.com/v1) has no name-search endpoint, so
to resolve a mod *name* to its actual Nexus page we use the site search
autocomplete (search.nexusmods.com) — best-effort, with graceful fallback to a
search URL. The officially-supported accurate lookup is by file MD5, exposed
here as `lookup_by_md5` for callers that have the downloaded file.

A personal API key is required (Settings → Nexus, or config `nexus_api_key`).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

_API = "https://api.nexusmods.com/v1"
_SEARCH = "https://search.nexusmods.com/mods"
_UA = "kotor-mod-installer"

# KOTOR game identifiers on Nexus.
GAME_ID = {"KOTOR1": 234, "KOTOR2": 198}
GAME_DOMAIN = {"KOTOR1": "kotor", "KOTOR2": "kotor2"}


def _get_json(url: str, key: str, timeout: int = 10) -> Optional[dict | list]:
    req = urllib.request.Request(url, headers={
        "apikey": key,
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def validate(key: str) -> dict:
    """Validate an API key. Returns {ok, name?, error?}."""
    if not key:
        return {"ok": False, "error": "no_key"}
    try:
        data = _get_json(f"{_API}/users/validate.json", key)
        if isinstance(data, dict) and data.get("name"):
            return {"ok": True, "name": data["name"],
                    "is_premium": bool(data.get("is_premium"))}
        return {"ok": False, "error": "invalid"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mod_page_url(game: str, mod_id: int) -> str:
    domain = GAME_DOMAIN.get(game, "kotor")
    return f"https://www.nexusmods.com/{domain}/mods/{mod_id}"


def search_url(game: str, name: str) -> str:
    domain = GAME_DOMAIN.get(game, "kotor")
    q = urllib.parse.quote_plus(name or "")
    if not q:
        return f"https://www.nexusmods.com/{domain}/mods/"
    return f"https://www.nexusmods.com/{domain}/search/?gsearch={q}&gsearchtype=mods"


def search_by_name(name: str, game: str, key: str) -> Optional[str]:
    """
    Resolve a mod name to its real Nexus page URL via the site search
    autocomplete. Returns None if no confident match / unavailable.
    """
    if not name or not key:
        return None
    gid = GAME_ID.get(game)
    if not gid:
        return None
    url = f"{_SEARCH}?terms={urllib.parse.quote_plus(name)}&game_id={gid}"
    try:
        data = _get_json(url, key, timeout=8)
    except Exception:
        return None
    results = (data or {}).get("results") if isinstance(data, dict) else None
    if not results:
        return None
    top = results[0]
    # Prefer the explicit url; otherwise build from mod_id.
    if top.get("url"):
        u = top["url"]
        return u if u.startswith("http") else f"https:{u}" if u.startswith("//") else u
    if top.get("mod_id"):
        return mod_page_url(game, int(top["mod_id"]))
    return None


def lookup_by_md5(md5_hash: str, game: str, key: str) -> Optional[str]:
    """Exact mod lookup by file MD5 (officially-supported, very accurate)."""
    if not md5_hash or not key:
        return None
    domain = GAME_DOMAIN.get(game, "kotor")
    url = f"{_API}/games/{domain}/mods/md5_search/{md5_hash}.json"
    try:
        data = _get_json(url, key, timeout=10)
    except Exception:
        return None
    if isinstance(data, list) and data:
        mod = data[0].get("mod") or {}
        mid = mod.get("mod_id")
        if mid:
            return mod_page_url(game, int(mid))
    return None
