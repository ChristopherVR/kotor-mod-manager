"""
Downloaders for mods hosted outside DeadlyStream and Nexus: MEGA, Google Drive,
GitHub releases, and plain file URLs. Each returns the downloaded file path(s).

MEGA public links carry their own decryption key after the '#', so no account is
needed: the file is fetched encrypted and decrypted as it streams to disk.
"""

import base64
import json
import re
import struct
import threading
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

import requests

ProgressCallback = Callable[[int, int, str], None]

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".exe")


class HostDownloadError(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = _UA
    return s


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "download"


def _name_from_headers(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I)
    if m:
        return _safe_name(urllib.parse.unquote(m.group(1).strip().strip('"')))
    m = re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        return _safe_name(m.group(1))
    return _safe_name(fallback)


def _stream_to_file(chunks, total: int, dest_dir: Path, filename: str,
                    progress: Optional[ProgressCallback],
                    cancel_event: Optional[threading.Event],
                    pause_event: Optional[threading.Event],
                    offset: int = 0) -> Path:
    """Write chunks to <name>.part, then rename, so a partial file is never
    mistaken for a finished archive. With `offset`, the chunks continue a
    partial file that is already on disk. The partial is kept when a download is
    cancelled or cut short, so it can be carried on later."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    part = dest_dir / (filename + ".part")
    done = offset
    with open(part, "ab" if offset else "wb") as f:
        for chunk in chunks:
            while (pause_event is not None and not pause_event.is_set()
                   and not (cancel_event is not None and cancel_event.is_set())):
                pause_event.wait(timeout=0.25)
            if cancel_event is not None and cancel_event.is_set():
                raise HostDownloadError("Download cancelled.")
            if chunk:
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, filename)
    if total and done != total:
        raise HostDownloadError(
            f"The download was cut short ({done} of {total} bytes). "
            f"Press Install to continue it.")
    part.replace(dest)
    return dest


def _check_not_html(resp: requests.Response, url: str) -> None:
    if "text/html" in resp.headers.get("Content-Type", "").lower():
        resp.close()
        raise HostDownloadError(
            f"Expected a file but received a web page for {url}. "
            "The link may have moved or need a sign-in.")


# ---------------------------------------------------------------------------
# Direct file URLs
# ---------------------------------------------------------------------------

def download_direct(url: str, dest_dir: Path, progress=None, cancel_event=None,
                    pause_event=None, session: Optional[requests.Session] = None) -> Path:
    s = session or _session()
    try:
        resp = s.get(url, stream=True, timeout=60, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HostDownloadError(f"Could not download {url}: {e}") from e
    _check_not_html(resp, url)
    fallback = Path(urllib.parse.urlparse(resp.url).path).name or "download.zip"
    name = _name_from_headers(resp, urllib.parse.unquote(fallback))
    total = 0 if resp.headers.get("Content-Encoding") else int(resp.headers.get("Content-Length", 0))
    # A partial file from an earlier run: ask for the rest instead of starting over.
    part = dest_dir / (name + ".part")
    have = part.stat().st_size if part.exists() else 0
    offset = 0
    if have > 0 and total and have < total:
        try:
            rest = s.get(url, stream=True, timeout=60, allow_redirects=True,
                         headers={"Range": f"bytes={have}-"})
        except requests.RequestException:
            rest = None
        if (rest is not None and rest.status_code == 206
                and "text/html" not in rest.headers.get("Content-Type", "").lower()):
            resp.close()
            resp, offset = rest, have
        elif rest is not None:
            rest.close()
    return _stream_to_file(resp.iter_content(512 * 1024), total, dest_dir, name,
                           progress, cancel_event, pause_event, offset=offset)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def _github_asset_url(url: str, session: requests.Session) -> str:
    """The download URL for a github.com link: itself if it is already a file,
    otherwise the first archive attached to the (latest or named) release."""
    blob = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    if blob:
        # A file in a repository: fetch the raw file rather than looking for a release.
        return "https://raw.githubusercontent.com/%s/%s/%s" % blob.groups()
    if "/releases/download/" in url or "/archive/" in url or \
            urllib.parse.urlparse(url).path.lower().endswith(_ARCHIVE_EXTS):
        return url
    m = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", url)
    if not m:
        raise HostDownloadError(f"Not a GitHub release link: {url}")
    owner, repo = m.group(1), m.group(2)
    tag = re.search(r"/releases/tag/([^/#?]+)", url)
    api = (f"https://api.github.com/repos/{owner}/{repo}/releases/"
           + (f"tags/{tag.group(1)}" if tag else "latest"))
    try:
        r = session.get(api, timeout=20, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        assets = r.json().get("assets", [])
    except (requests.RequestException, ValueError) as e:
        raise HostDownloadError(f"Could not read the GitHub release for {owner}/{repo}: {e}") from e
    for a in assets:
        if a.get("name", "").lower().endswith(_ARCHIVE_EXTS):
            return a["browser_download_url"]
    raise HostDownloadError(f"The GitHub release for {owner}/{repo} has no downloadable archive.")


def download_github(url: str, dest_dir: Path, progress=None, cancel_event=None,
                    pause_event=None) -> Path:
    s = _session()
    return download_direct(_github_asset_url(url, s), dest_dir, progress,
                           cancel_event, pause_event, session=s)


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

def _gdrive_id(url: str) -> str:
    m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if not m:
        raise HostDownloadError(
            "This Google Drive link is a folder or an unrecognised link; "
            "only single-file links can be downloaded.")
    return m.group(1)


def download_gdrive(url: str, dest_dir: Path, progress=None, cancel_event=None,
                    pause_event=None) -> Path:
    file_id = _gdrive_id(url)
    s = _session()
    endpoint = "https://drive.usercontent.google.com/download"
    params = {"id": file_id, "export": "download", "confirm": "t"}
    try:
        resp = s.get(endpoint, params=params, stream=True, timeout=60)
        resp.raise_for_status()
        if "text/html" in resp.headers.get("Content-Type", "").lower():
            # Large files show a virus-scan warning first; follow its form.
            html = resp.text
            form = re.search(r'<form[^>]+action="([^"]+)"', html)
            fields = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', html))
            if not form or not fields:
                raise HostDownloadError(
                    "Google Drive would not hand over the file (it may be private "
                    "or over its download quota).")
            resp = s.get(form.group(1).replace("&amp;", "&"), params=fields,
                         stream=True, timeout=60)
            resp.raise_for_status()
    except requests.RequestException as e:
        raise HostDownloadError(f"Could not download from Google Drive: {e}") from e
    _check_not_html(resp, url)
    name = _name_from_headers(resp, f"gdrive_{file_id}.zip")
    return _stream_to_file(resp.iter_content(512 * 1024),
                           int(resp.headers.get("Content-Length", 0)),
                           dest_dir, name, progress, cancel_event, pause_event)


# ---------------------------------------------------------------------------
# MEGA (public file links)
# ---------------------------------------------------------------------------

_MEGA_API = "https://g.api.mega.co.nz/cs"
_MEGA_ERRORS = {
    -9: "MEGA says this file no longer exists.",
    -16: "MEGA has blocked this file.",
    -17: "MEGA's download quota for your connection is used up. Try again later.",
    -18: "MEGA says this file is temporarily unavailable.",
}


def _mega_b64(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/").replace(",", "")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _mega_parse(url: str) -> tuple[str, bytes]:
    if "/folder/" in url or "#F!" in url:
        raise HostDownloadError("MEGA folder links are not supported; only single-file links.")
    m = re.search(r"mega\.(?:nz|co\.nz)/file/([\w-]+)#([\w,-]+)", url) or \
        re.search(r"mega\.(?:nz|co\.nz)/#!([\w-]+)!([\w,-]+)", url)
    if not m:
        raise HostDownloadError(f"Unrecognised MEGA link: {url}")
    key = _mega_b64(m.group(2))
    if len(key) != 32:
        raise HostDownloadError("This MEGA link's key is incomplete.")
    return m.group(1), key


def download_mega(url: str, dest_dir: Path, progress=None, cancel_event=None,
                  pause_event=None) -> Path:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    handle, key = _mega_parse(url)
    k = struct.unpack(">8I", key)
    aes_key = struct.pack(">4I", k[0] ^ k[4], k[1] ^ k[5], k[2] ^ k[6], k[3] ^ k[7])
    iv = struct.pack(">4I", k[4], k[5], 0, 0)

    s = _session()
    try:
        r = s.post(_MEGA_API, params={"id": 0}, json=[{"a": "g", "g": 1, "p": handle}], timeout=20)
        r.raise_for_status()
        info = r.json()[0]
    except (requests.RequestException, ValueError, IndexError) as e:
        raise HostDownloadError(f"Could not reach MEGA: {e}") from e
    if isinstance(info, int):
        raise HostDownloadError(_MEGA_ERRORS.get(info, f"MEGA refused the download (error {info})."))

    name = f"mega_{handle}"
    try:
        raw = _mega_b64(info["at"])
        dec = Cipher(algorithms.AES(aes_key), modes.CBC(b"\0" * 16)).decryptor()
        attrs = (dec.update(raw + b"\0" * (-len(raw) % 16)) + dec.finalize()).rstrip(b"\0")
        if attrs.startswith(b"MEGA"):
            name = json.loads(attrs[4:].decode("utf-8")).get("n") or name
    except Exception:
        pass  # keep the fallback name

    try:
        resp = s.get(info["g"], stream=True, timeout=60)
        resp.raise_for_status()
    except (requests.RequestException, KeyError) as e:
        raise HostDownloadError(f"Could not download from MEGA: {e}") from e

    decryptor = Cipher(algorithms.AES(aes_key), modes.CTR(iv)).decryptor()
    chunks = (decryptor.update(c) for c in resp.iter_content(512 * 1024))
    return _stream_to_file(chunks, int(info.get("s", 0)), dest_dir, _safe_name(name),
                           progress, cancel_event, pause_event)


_DOWNLOADERS = {
    "direct": download_direct,
    "github": download_github,
    "googledrive": download_gdrive,
    "mega": download_mega,
}


def can_download(host: str) -> bool:
    return host in _DOWNLOADERS


def download_from_host(host: str, url: str, dest_dir: Path, progress=None,
                       cancel_event=None, pause_event=None) -> list[Path]:
    """Download a mod from a supported host. Returns the file(s) written."""
    fn = _DOWNLOADERS.get(host)
    if fn is None:
        raise HostDownloadError(f"No downloader for {host}.")
    return [fn(url, dest_dir, progress, cancel_event, pause_event)]
