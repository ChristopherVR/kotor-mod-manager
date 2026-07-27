"""
Nexus Mods integration.

Authentication
--------------
Nexus authenticates API callers with a **personal API key**, not a username and
password. There is no password-based API login to implement: the key from
https://www.nexusmods.com/users/myaccount?tab=api is the credential. It is
stored in the OS keyring (same as the DeadlyStream password) rather than in
config.json, so it does not sit in plain text on disk.

Downloading, and why a free account cannot be fully automated
-------------------------------------------------------------
`download_link.json` behaves differently depending on the account:

* **Premium** - returns a CDN link for any file. Fully automatic; the app can
  download a whole build unattended.
* **Free** - returns HTTP 403 unless the request carries a short-lived
  `key`/`expires` pair. That pair is minted only when the user clicks
  "Mod manager download" on the mod page, which sends the browser to an
  `nxm://` link. This is a deliberate anti-leeching measure, not something a
  login can bypass; Vortex and Mod Organizer work the same way.

So `download_file` supports both: pass the nxm parameters for a free account, or
nothing at all for Premium. `parse_nxm` turns the URL the browser hands over
into those parameters, which is what a registered `nxm://` handler receives.

The search helper below uses the site autocomplete because the public API has no
name-search endpoint; the officially-supported accurate lookup is by file MD5.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import keyring
except ImportError:  # keyring is optional for library use
    keyring = None

_API = "https://api.nexusmods.com/v1"
_SEARCH = "https://search.nexusmods.com/mods"
_UA = "kotor-mod-installer"

SERVICE_NAME = "kotor_mod_installer_nexus"
_KEY_ENTRY = "__api_key__"


class NexusAuthError(Exception):
    """The API key is missing, invalid, or lacks rights for this download."""


class NexusDownloadError(Exception):
    pass

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


# ---------------------------------------------------------------------------
# Credential storage
# ---------------------------------------------------------------------------

def save_api_key(key: str) -> None:
    """Store the personal API key in the OS keyring."""
    if keyring is None:
        raise NexusAuthError("keyring is not available on this system.")
    keyring.set_password(SERVICE_NAME, _KEY_ENTRY, key)


def load_api_key(fallback: str = "") -> str:
    """
    Read the API key, preferring the keyring over the plain-text config value.

    fallback lets callers pass config['nexus_api_key'] so existing installs keep
    working; the keyring copy wins once one has been saved.
    """
    if keyring is not None:
        try:
            stored = keyring.get_password(SERVICE_NAME, _KEY_ENTRY)
            if stored:
                return stored
        except Exception:
            pass
    return fallback


def sign_in(key: str, persist: bool = True) -> dict:
    """
    Validate an API key and remember it. Returns the same shape as validate(),
    with is_premium telling the caller whether unattended downloads are possible.
    """
    result = validate(key)
    if result.get("ok") and persist:
        try:
            save_api_key(key)
        except NexusAuthError:
            pass
    return result


# ---------------------------------------------------------------------------
# nxm:// handoff
# ---------------------------------------------------------------------------

@dataclass
class NxmLink:
    """A download handoff from the Nexus website."""
    game_domain: str
    mod_id: int
    file_id: int
    key: str = ""
    expires: str = ""

    @property
    def is_free_account_link(self) -> bool:
        return bool(self.key and self.expires)


_NXM_RE = re.compile(
    r"^nxm://(?P<domain>[^/]+)/mods/(?P<mod>\d+)/files/(?P<file>\d+)", re.I)


def parse_nxm(url: str) -> NxmLink:
    """
    Parse the nxm:// URL the browser hands to a registered mod manager.

    Format: nxm://<game>/mods/<mod_id>/files/<file_id>?key=<k>&expires=<e>
    The key/expires pair is present for free accounts and absent for Premium.
    """
    m = _NXM_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not an nxm:// download link: {url[:80]}")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return NxmLink(
        game_domain=m.group("domain").lower(),
        mod_id=int(m.group("mod")),
        file_id=int(m.group("file")),
        key=(q.get("key") or [""])[0],
        expires=(q.get("expires") or [""])[0],
    )


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def file_info(game: str, mod_id: int, file_id: int, key: str) -> dict:
    domain = GAME_DOMAIN.get(game, game)
    url = f"{_API}/games/{domain}/mods/{mod_id}/files/{file_id}.json"
    return _get_json(url, key) or {}


def list_files(game: str, mod_id: int, key: str) -> list[dict]:
    domain = GAME_DOMAIN.get(game, game)
    data = _get_json(f"{_API}/games/{domain}/mods/{mod_id}/files.json", key)
    return (data or {}).get("files", []) if isinstance(data, dict) else []


def download_link(game: str, mod_id: int, file_id: int, api_key: str,
                  nxm_key: str = "", nxm_expires: str = "") -> str:
    """
    Resolve a CDN download URL.

    With nxm_key/nxm_expires this works on a free account. Without them it
    requires Premium, and Nexus answers 403 otherwise - which is an account
    tier limitation, not a bad key, so the error says so explicitly.
    """
    domain = GAME_DOMAIN.get(game, game)
    url = (f"{_API}/games/{domain}/mods/{mod_id}/files/{file_id}"
           f"/download_link.json")
    if nxm_key and nxm_expires:
        url += "?" + urllib.parse.urlencode({"key": nxm_key,
                                             "expires": nxm_expires})
    try:
        data = _get_json(url, api_key, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise NexusAuthError(
                "Nexus refused the download link. Free accounts can only "
                "download after clicking 'Mod manager download' on the mod "
                "page, which hands this app an nxm:// link. A Premium account "
                "can download without that step."
            ) from e
        if e.code == 401:
            raise NexusAuthError("Nexus rejected the API key.") from e
        raise NexusDownloadError(f"Nexus returned HTTP {e.code}.") from e
    if isinstance(data, list) and data:
        uri = data[0].get("URI")
        if uri:
            return uri
    raise NexusDownloadError("Nexus returned no download URL.")


def download_file(game: str, mod_id: int, file_id: int, dest_dir: Path,
                  api_key: str, nxm_key: str = "", nxm_expires: str = "",
                  progress_callback: Optional[Callable[[int, int, str], None]] = None,
                  cancel_event=None) -> Path:
    """Fetch one Nexus file into dest_dir and return its path."""
    info = file_info(game, mod_id, file_id, api_key)
    filename = re.sub(r'[<>:"/\\|?*]', "_",
                      info.get("file_name") or f"nexus_{mod_id}_{file_id}.zip")

    url = download_link(game, mod_id, file_id, api_key, nxm_key, nxm_expires)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    part = dest_dir / (filename + ".part")

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(part, "wb") as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    part.unlink(missing_ok=True)
                    raise NexusDownloadError("Download cancelled.")
                chunk = r.read(512 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total, filename)
    part.replace(dest)
    return dest


def download_from_nxm(url: str, dest_dir: Path, api_key: str,
                      game: str = "KOTOR1", **kw) -> Path:
    """Handle an nxm:// link end to end (what an nxm handler calls)."""
    link = parse_nxm(url)
    return download_file(game, link.mod_id, link.file_id, dest_dir, api_key,
                         nxm_key=link.key, nxm_expires=link.expires, **kw)


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
