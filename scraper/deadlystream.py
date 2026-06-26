"""Authentication and downloading from deadlystream.com."""

import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import keyring
import requests
from bs4 import BeautifulSoup

SERVICE_NAME = "kotor_mod_installer_ds"
CSRF_RE = re.compile(r'"csrfKey"\s*:\s*"([a-f0-9]+)"', re.IGNORECASE)
# Also try meta tag
CSRF_META_RE = re.compile(r'data-csrfkey="([a-f0-9]+)"', re.IGNORECASE)
# Fallback: the key appears as a URL param on links (csrfKey=<hex>), possibly
# HTML-encoded as &amp;csrfKey=<hex>.
CSRF_PARAM_RE = re.compile(r'csrfKey=([a-f0-9]{16,})', re.IGNORECASE)

BASE = "https://deadlystream.com"
LOGIN_URL = f"{BASE}/login/"


def download_name_matches(record_name: str, keep_names: list[str]) -> bool:
    """
    Whether a download record matches one of the build guide's "download only X"
    filenames. Comparison ignores case, punctuation, and the file extension so
    'hd_twilek_female.rar' matches a record shown as 'HD Twilek Female' etc.
    Empty keep_names means "keep everything".
    """
    if not keep_names:
        return True

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    rn = norm(record_name)
    if not rn:
        return False
    for k in keep_names:
        stem = k.rsplit(".", 1)[0] if "." in k else k
        kn = norm(stem) or norm(k)
        if kn and (kn in rn or rn in kn):
            return True
    return False


class AuthError(Exception):
    pass


class DownloadError(Exception):
    pass


class DeadlyStreamClient:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._logged_in = False
        self._csrf_key: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Credential storage (uses Windows Credential Manager via keyring)
    # ------------------------------------------------------------------

    @staticmethod
    def save_credentials(username: str, password: str) -> None:
        keyring.set_password(SERVICE_NAME, username, password)
        keyring.set_password(SERVICE_NAME, "__last_user__", username)

    @staticmethod
    def load_credentials() -> tuple[str, str]:
        username = keyring.get_password(SERVICE_NAME, "__last_user__") or ""
        password = keyring.get_password(SERVICE_NAME, username) if username else ""
        return username, password or ""

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _extract_csrf(self, html: str) -> Optional[str]:
        m = CSRF_RE.search(html)
        if m:
            return m.group(1)
        m = CSRF_META_RE.search(html)
        if m:
            return m.group(1)
        # BeautifulSoup fallback (hidden form input)
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("input", {"name": "csrfKey"})
        if tag and tag.get("value"):
            return tag["value"]
        # Last resort: the key appears as a URL param on many links/buttons,
        # e.g. ?do=download&amp;csrfKey=<hex>. Handle the &amp; HTML entity.
        m = CSRF_PARAM_RE.search(html)
        if m:
            return m.group(1)
        return None

    def login(self, username: str, password: str) -> None:
        with self._lock:
            # Get login page to grab CSRF
            resp = self._session.get(LOGIN_URL, timeout=20)
            resp.raise_for_status()

            csrf = self._extract_csrf(resp.text)
            if not csrf:
                raise AuthError("Could not find CSRF key on login page.")

            payload = {
                "_processLogin": "usernamepassword",
                "auth": username,
                "password": password,
                "csrfKey": csrf,
                "remember_me": "1",
            }
            resp = self._session.post(LOGIN_URL, data=payload, timeout=20, allow_redirects=True)
            resp.raise_for_status()

            # Check if login succeeded
            if "sign_out" in resp.text.lower() or "logout" in resp.text.lower():
                self._logged_in = True
                self._csrf_key = self._extract_csrf(resp.text)
                return

            # Try checking cookies
            for cookie in self._session.cookies:
                if "member" in cookie.name.lower() or "ips" in cookie.name.lower():
                    self._logged_in = True
                    self._csrf_key = self._extract_csrf(resp.text)
                    return

            raise AuthError(
                "Login failed - check your username/password. "
                "DeadlyStream may also be rate-limiting logins."
            )

    def ensure_logged_in(self, username: str = "", password: str = "") -> None:
        if self._logged_in:
            return
        if not username:
            username, password = self.load_credentials()
        if not username or not password:
            raise AuthError("No credentials provided and none saved.")
        self.login(username, password)

    # ------------------------------------------------------------------
    # CSRF key retrieval (refreshed from file page when needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _file_page_url(file_id: str, slug: str = "") -> str:
        """
        Slugged file page URL. DeadlyStream (IPS/Invision) 404s on
        /files/file/{id}/ without the slug, which breaks CSRF extraction and
        the download links. Always prefer the {file_id}-{slug} form.
        """
        if slug:
            return f"{BASE}/files/file/{file_id}-{slug}/"
        return f"{BASE}/files/file/{file_id}/"   # legacy fallback (will 404 on DS)

    def _get_csrf_for_file(self, file_id: str, slug: str = "") -> str:
        url = self._file_page_url(file_id, slug)
        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()
        csrf = self._extract_csrf(resp.text)
        if not csrf:
            raise DownloadError(f"Could not extract CSRF key from file page {file_id}-{slug}.")
        return csrf

    def _get_file_info(self, file_id: str, slug: str = "") -> dict:
        """Fetch title, description, category from the mod page."""
        url = self._file_page_url(file_id, slug)
        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else f"Mod {file_id}"
        title = re.sub(r"\s*-\s*DeadlyStream.*$", "", title, flags=re.IGNORECASE).strip()

        desc_tag = soup.find("div", class_=re.compile("ipsType_richText|file_description", re.I))
        description = desc_tag.get_text(" ", strip=True)[:500] if desc_tag else ""

        csrf = self._extract_csrf(resp.text)

        return {"title": title, "description": description, "csrf": csrf, "file_id": file_id}

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------

    def download_file(
        self,
        file_id: str,
        dest_dir: Path,
        slug: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> Path:
        """
        Download a (single-file) submission from deadlystream.

        progress_callback(bytes_downloaded, total_bytes, filename)
        cancel_event: set() to abort mid-download
        pause_event: when provided, a CLEARED event pauses the download in place;
        setting it again resumes from where it left off (HTTP range request).
        Returns the local path of the downloaded file.
        """
        page_url = self._file_page_url(file_id, slug)
        with self._lock:
            csrf = self._get_csrf_for_file(file_id, slug)

        download_url = f"{page_url}?do=download&csrfKey={csrf}"
        return self._download_from_url(
            download_url, dest_dir, file_id,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            pause_event=pause_event,
            referer=page_url,
        )

    def get_file_info(self, file_id: str, slug: str = "") -> dict:
        return self._get_file_info(file_id, slug)

    # Real screenshots live under uploads/attachments; everything else
    # (avatars, the site logo, theme icons, emoticons) is filtered out.
    _IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    _IMG_EXCLUDE = (
        "avatar", "/profile", "profile_", "photo-thumb", "default_photo",
        "set_resources", "logo", "favicon", "/icon", "emoticon", "/style_",
        "themes/", "/theme/", "badge", "spinner", "sprite", "rank",
        "placeholder", "loading", "blank.", "/r/",
        # forum/site chrome that isn't a mod screenshot
        "/reactions/", "deadly_stream", "_banner", "/comment", "/uploads/monthly",
    )
    # The actual file screenshot gallery lives under /downloads/screens/.
    _IMG_SCREENSHOT_HINTS = ("/downloads/screens/",)
    _IMG_CONTENT_HINTS = ("/downloads/screens/", "/uploads/", "/gallery/", "screenshot", "/attachments/")

    @staticmethod
    def _norm_img_url(src: str) -> str:
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return BASE + src
        return src

    @classmethod
    def _looks_like_screenshot(cls, url: str) -> bool:
        low = url.lower()
        if any(k in low for k in cls._IMG_EXCLUDE):
            return False
        # Must come from a real content area (uploads/attachments/gallery).
        return any(k in low for k in cls._IMG_CONTENT_HINTS)

    def _extract_screenshots(self, soup) -> list:
        urls: list[str] = []

        def add(src: str) -> None:
            if not src:
                return
            full = self._norm_img_url(src)
            if self._looks_like_screenshot(full) and full not in urls:
                urls.append(full)

        # 1. Attachment/lightbox image links = the full-size screenshots.
        for a in soup.find_all("a", href=True):
            cls = " ".join(a.get("class", [])).lower()
            ext = (a.get("data-fileext") or "").lower()
            if "ipsattachlink" in cls or "lightbox" in cls or ext in ("jpg", "jpeg", "png", "gif", "webp"):
                add(a["href"])
        # 2. Inline images (description + record gallery).
        for img in soup.find_all("img"):
            add(img.get("data-src") or img.get("src") or "")
        # 3. og:image last (often the site logo - only kept if it passes the filter).
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            add(og["content"])

        # Prefer the file's real screenshot gallery (/downloads/screens/) when present;
        # only fall back to other content images if there are none.
        screens = [u for u in urls if any(h in u.lower() for h in self._IMG_SCREENSHOT_HINTS)]
        return (screens or urls)[:10]

    def get_mod_details(self, file_id: str, slug: str = "") -> dict:
        """
        Rich detail for a mod page: title, description, screenshot image URLs,
        author, and the canonical DeadlyStream URL. Best-effort (returns what it
        can parse).
        """
        page_url = self._file_page_url(file_id, slug)
        try:
            resp = self._session.get(page_url, timeout=20)
            resp.raise_for_status()
        except (requests.RequestException, OSError) as e:
            return {"error": str(e), "ds_url": page_url}

        soup = BeautifulSoup(resp.text, "lxml")

        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else f"Mod {file_id}"
        title = re.sub(r"\s*-\s*DeadlyStream.*$", "", title, flags=re.IGNORECASE).strip()

        desc_tag = soup.find("div", class_=re.compile("ipsType_richText|file_description|cFileDescription", re.I))
        description = desc_tag.get_text("\n", strip=True)[:2000] if desc_tag else ""

        images = self._extract_screenshots(soup)

        author = ""
        a_tag = soup.find("a", href=re.compile(r"/profile/"))
        if a_tag:
            author = a_tag.get_text(strip=True)

        return {
            "file_id": file_id, "slug": slug, "title": title,
            "description": description, "images": images, "author": author,
            "ds_url": page_url,
        }

    # ------------------------------------------------------------------
    # Multi-file submissions
    # ------------------------------------------------------------------

    def list_download_records(self, file_id: str, slug: str = "") -> list[dict]:
        """
        Inspect a mod's download page and return every downloadable record.

        IPS/IPB stores multi-file submissions as separate records, each with a
        `&r=<id>` parameter on the download URL. Returns a list of
        {"name": str, "url": str, "record_id": str|None}. Always returns at
        least one entry (the primary download) so callers can iterate uniformly.
        """
        page_url = self._file_page_url(file_id, slug)
        with self._lock:
            csrf = self._get_csrf_for_file(file_id, slug)

        # The /?do=download page (without confirm) lists individual files when
        # a submission has more than one. Send the file page as Referer.
        list_url = f"{page_url}?do=download"
        records: list[dict] = []
        try:
            resp = self._session.get(list_url, timeout=20, headers={"Referer": page_url})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "do=download" not in href or "r=" not in href:
                    continue
                rmatch = re.search(r"[?&]r=(\d+)", href)
                record_id = rmatch.group(1) if rmatch else None
                # Build absolute URL with our fresh csrf
                if href.startswith("/"):
                    href = BASE + href
                if "csrfKey=" not in href:
                    sep = "&" if "?" in href else "?"
                    href = f"{href}{sep}csrfKey={csrf}"
                name = a.get_text(strip=True) or f"file_{record_id or len(records)}"
                if not any(r["record_id"] == record_id for r in records):
                    records.append({"name": name, "url": href, "record_id": record_id})
        except (requests.RequestException, OSError):
            pass

        if not records:
            # Single-file submission - fall back to the primary download URL.
            records.append({
                "name": f"mod_{file_id}",
                "url": f"{page_url}?do=download&csrfKey={csrf}",
                "record_id": None,
            })
        return records

    def download_all_files(
        self,
        file_id: str,
        dest_dir: Path,
        slug: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        keep_names: Optional[list[str]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> list[Path]:
        """
        Download files in a (possibly multi-file) submission.

        keep_names: if set (from a build guide "download only X" instruction),
        only records matching one of those filenames are fetched. If the filter
        matches nothing, every file is downloaded (so we never download nothing
        because a name didn't line up).

        Returns the list of downloaded local paths in page order.
        """
        records = self.list_download_records(file_id, slug)
        referer = self._file_page_url(file_id, slug)

        def _fetch(recs, names):
            out: list[Path] = []
            for rec in recs:
                if cancel_event and cancel_event.is_set():
                    raise DownloadError("Download cancelled.")
                path = self._download_from_url(
                    rec["url"], dest_dir, file_id,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    fallback_name=rec["name"],
                    referer=referer,
                    keep_names=names,
                )
                if path is not None:
                    out.append(path)
            return out

        # DeadlyStream's download page rarely exposes per-file names, so we
        # decide from the real filename in each download's headers (see
        # _download_from_url). If the "download only X" filter ends up matching
        # nothing, fall back to downloading everything rather than nothing.
        if keep_names and len(records) > 1:
            paths = _fetch(records, keep_names)
            if paths:
                return paths
        return _fetch(records, None)

    def _download_from_url(
        self,
        download_url: str,
        dest_dir: Path,
        file_id: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        fallback_name: str = "",
        referer: str = "",
        keep_names: Optional[list[str]] = None,
        pause_event: Optional[threading.Event] = None,
    ) -> "Path | None":
        headers = {"Referer": referer} if referer else {}

        def _paused() -> bool:
            return pause_event is not None and not pause_event.is_set()

        def _aborted() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        resp = self._session.get(
            download_url, stream=True, timeout=60, allow_redirects=True, headers=headers
        )
        resp.raise_for_status()

        # Guard: a logged-out / bad-CSRF / confirm-interstitial response comes
        # back as HTML (HTTP 200). Don't write an HTML page into a .zip.
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" in ctype:
            resp.close()
            raise DownloadError(
                "Expected a file but received an HTML page (login, CSRF, or "
                f"download-confirm issue) for {download_url}"
            )

        cd = resp.headers.get("Content-Disposition", "")
        filename_match = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)["\']?', cd)
        if filename_match:
            filename = filename_match.group(1).strip().strip('"\'')
            filename = re.sub(r"^UTF-8''", "", filename)
        else:
            filename = fallback_name or f"mod_{file_id}.zip"
        # Sanitise
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

        # "Download only X" filtering: the per-file name is only reliable here in
        # the response headers, so skip the body of files we were told to ignore.
        if keep_names and not download_name_matches(filename, keep_names):
            resp.close()
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        # Stream into a .part file so a half-finished download is never mistaken
        # for a complete archive; rename to the real name only once it's done.
        part_path = dest_dir / (filename + ".part")

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        current = resp
        from installer.fs_retry import with_lock_retry
        f = with_lock_retry(lambda: open(part_path, "wb"))
        # Throttle progress reports to ~3 per second so the WS bus doesn't
        # flood the frontend with hundreds of messages for a big archive.
        _last_report: float = 0.0
        try:
            while True:
                paused = False
                for chunk in current.iter_content(chunk_size=1024 * 512):
                    if _aborted():
                        f.close()
                        current.close()
                        part_path.unlink(missing_ok=True)
                        raise DownloadError("Download cancelled.")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            now = time.monotonic()
                            if now - _last_report >= 0.33:
                                progress_callback(downloaded, total, filename)
                                _last_report = now
                    # Check AFTER writing so `downloaded` is exact for the resume
                    # range request - we must not drop the chunk we just pulled.
                    if _paused():
                        paused = True
                        break
                current.close()
                if not paused:
                    break

                # Paused: flush what we have to disk, then wait to be resumed.
                f.flush()
                os.fsync(f.fileno())
                while _paused() and not _aborted():
                    pause_event.wait(timeout=0.25)
                if _aborted():
                    f.close()
                    part_path.unlink(missing_ok=True)
                    raise DownloadError("Download cancelled.")

                # Resume: ask the server to continue from where we stopped.
                current = self._session.get(
                    download_url, stream=True, timeout=60, allow_redirects=True,
                    headers={**headers, "Range": f"bytes={downloaded}-"},
                )
                current.raise_for_status()
                if current.status_code != 206:
                    # Server ignored the range (sent the whole file again) - start
                    # over so we don't append a duplicate body onto the partial.
                    f.close()
                    f = open(part_path, "wb")
                    downloaded = 0
                    total = int(current.headers.get("Content-Length", total)) or total
        finally:
            if not f.closed:
                f.close()

        # Final progress ping so the UI always reaches 100 % even when the
        # last chunk happened to be sent within the throttle window.
        if progress_callback:
            progress_callback(downloaded, total or downloaded, filename)

        # Antivirus/indexer may briefly hold the freshly written file or an old
        # copy of the destination open (WinError 32); retry the rename past it.
        from installer.fs_retry import with_lock_retry
        with_lock_retry(lambda: os.replace(part_path, dest_path))
        return dest_path
