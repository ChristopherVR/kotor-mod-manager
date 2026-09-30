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

import contextlib
import json
import re
import threading
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

    def __init__(self, message: str, free_account: bool = False):
        super().__init__(message)
        # True when Nexus wants the free-account "Mod manager download" handoff.
        self.free_account = free_account


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


def pick_files(files: list[dict], keep_names: Optional[list[str]] = None,
               ignore_names: Optional[list[str]] = None) -> list[dict]:
    """
    Choose which of a mod's files to download.

    Build guides say "download only X" / "skip Y"; without those, take the
    primary MAIN file (newest if there are several). Old, archived and deleted
    files are never offered.
    """
    from scraper.deadlystream import download_name_excluded, download_name_matches

    usable = [f for f in files
              if (f.get("category_name") or "").upper()
              in ("MAIN", "UPDATE", "OPTIONAL", "MISCELLANEOUS")]
    if ignore_names:
        usable = [f for f in usable
                  if not download_name_excluded(f.get("file_name", ""), ignore_names)]

    def newest(fs: list[dict]) -> dict:
        return max(fs, key=lambda f: f.get("uploaded_timestamp") or 0)

    if keep_names:
        # The exact file first; a name that merely starts the same is a last resort.
        named = [f for f in usable
                 if download_name_matches(f.get("file_name", ""), keep_names, strict=True)]
        if not named:
            named = [f for f in usable
                     if download_name_matches(f.get("file_name", ""), keep_names)]
        if named:
            return named
    mains = [f for f in usable if (f.get("category_name") or "").upper() == "MAIN"]
    primary = [f for f in mains if f.get("is_primary")]
    pool = primary or mains or usable
    return [newest(pool)] if pool else []


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
                "can download without that step.",
                free_account=True,
            ) from e
        if e.code == 401:
            raise NexusAuthError("Nexus rejected the API key.") from e
        raise NexusDownloadError(f"Nexus returned HTTP {e.code}.") from e
    if isinstance(data, list) and data:
        uri = data[0].get("URI")
        if uri:
            return uri
    raise NexusDownloadError("Nexus returned no download URL.")


def _escape_url(url: str) -> str:
    """Escape what Nexus leaves raw (its CDN paths contain spaces from the file
    name) without touching sequences that are already escaped."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        p.scheme, p.netloc,
        urllib.parse.quote(p.path, safe="/%:@+,;=~!$&'()*-._"),
        p.query.replace(" ", "%20"), p.fragment))


def download_file(game: str, mod_id: int, file_id: int, dest_dir: Path,
                  api_key: str, nxm_key: str = "", nxm_expires: str = "",
                  progress_callback: Optional[Callable[[int, int, str], None]] = None,
                  cancel_event=None, pause_event=None) -> Path:
    """Fetch one Nexus file into dest_dir and return its path.

    pause_event: a cleared event holds the download until it is set again.
    """
    info = file_info(game, mod_id, file_id, api_key)
    filename = re.sub(r'[<>:"/\\|?*]', "_",
                      info.get("file_name") or f"nexus_{mod_id}_{file_id}.zip")

    url = download_link(game, mod_id, file_id, api_key, nxm_key, nxm_expires)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    part = dest_dir / (filename + ".part")

    safe_url = _escape_url(url)
    # A partial file from an earlier run (the app was closed, or the connection
    # dropped): ask for the rest instead of starting over.
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": _UA}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        r = urllib.request.urlopen(urllib.request.Request(safe_url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        if not (offset and e.code == 416):
            raise
        # The partial cannot be continued (it is already whole, or the file changed).
        part.unlink(missing_ok=True)
        offset = 0
        r = urllib.request.urlopen(
            urllib.request.Request(safe_url, headers={"User-Agent": _UA}), timeout=60)
    with r:
        resumed = offset > 0 and r.getcode() == 206
        if not resumed:
            offset = 0
        length = int(r.headers.get("Content-Length", 0))
        total = offset + length if length else 0
        done = offset
        with open(part, "ab" if resumed else "wb") as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    # The partial file stays, so a later run can carry on from it.
                    raise NexusDownloadError("Download cancelled.")
                while (pause_event is not None and not pause_event.is_set()
                       and not (cancel_event is not None and cancel_event.is_set())):
                    pause_event.wait(timeout=0.25)
                chunk = r.read(512 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total, filename)
    if total and done != total:
        raise NexusDownloadError(
            f"The download was cut short ({done} of {total} bytes). "
            f"Press Install to continue it.")
    part.replace(dest)
    return dest


class NxmBroker:
    """
    Hands nxm:// links from the Nexus website to the download that is waiting
    for them. A free account's download cannot start until the player clicks
    "Mod manager download", so the pipeline waits here for that click.

    nxm:// links exist for every game on Nexus, so links are matched on the game
    as well as the ids, and links for other games are refused.
    """

    def __init__(self, on_active: Optional[Callable[[bool], None]] = None) -> None:
        self._lock = threading.Lock()
        self._links: "dict[tuple[str, int, int], NxmLink]" = {}
        self._events: "dict[tuple[str, int, int], threading.Event]" = {}
        self._waiting = 0
        # Called with True when the first download starts waiting and False when
        # the last one stops, so the app only claims nxm:// links while needed.
        self.on_active = on_active

    @contextlib.contextmanager
    def hold(self):
        """Keep nxm:// links claimed for a whole run of waits, so the app does
        not hand them back and take them again between one mod and the next."""
        with self._lock:
            self._waiting += 1
            first = self._waiting == 1
        if first and self.on_active:
            self.on_active(True)
        try:
            yield
        finally:
            with self._lock:
                self._waiting -= 1
                last = self._waiting == 0
            if last and self.on_active:
                self.on_active(False)

    @staticmethod
    def _key(domain: str, mod_id: int, file_id: int) -> "tuple[str, int, int]":
        return (domain.lower(), mod_id, file_id)

    def deliver(self, link: NxmLink) -> bool:
        """Accept a link. False if it is for a game this app does not handle."""
        if link.game_domain.lower() not in GAME_DOMAIN.values():
            return False
        k = self._key(link.game_domain, link.mod_id, link.file_id)
        with self._lock:
            self._links[k] = link
            ev = self._events.get(k)
        if ev:
            ev.set()
        return True

    def wait(self, domain: str, mod_id: int, file_id: int, timeout: float = 600,
             stop_event=None, on_waiting: Optional[Callable[[], None]] = None
             ) -> Optional[NxmLink]:
        """Block until the link for this file arrives. None on timeout or stop.

        on_waiting runs once the wait is registered (and the app has been told
        to claim nxm:// links), so the page the player clicks on is opened only
        after links will actually reach the app."""
        k = self._key(domain, mod_id, file_id)
        with self._lock:
            link = self._links.pop(k, None)
            if link:
                return link
            ev = self._events.setdefault(k, threading.Event())
            self._waiting += 1
            first = self._waiting == 1
        if first and self.on_active:
            self.on_active(True)
        try:
            if on_waiting:
                on_waiting()
            waited = 0.0
            while waited < timeout and not ev.is_set():
                if stop_event is not None and stop_event.is_set():
                    break
                ev.wait(0.5)
                waited += 0.5
            with self._lock:
                self._events.pop(k, None)
                return self._links.pop(k, None)
        finally:
            with self._lock:
                self._waiting -= 1
                last = self._waiting == 0
            if last and self.on_active:
                self.on_active(False)


NXM = NxmBroker()


def nxm_page_url(game: str, mod_id: int, file_id: int) -> str:
    """The mod page opened so the player can click "Mod manager download"."""
    domain = GAME_DOMAIN.get(game, "kotor")
    return (f"https://www.nexusmods.com/{domain}/mods/{mod_id}"
            f"?tab=files&file_id={file_id}&nmm=1")


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
