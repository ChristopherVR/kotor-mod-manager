"""Authentication and downloading from deadlystream.com."""

import re
import threading
from pathlib import Path
from typing import Callable, Optional

import keyring
import requests
from bs4 import BeautifulSoup

SERVICE_NAME = "kotor_mod_installer_ds"
CSRF_RE = re.compile(r'"csrfKey"\s*:\s*"([a-f0-9]+)"', re.IGNORECASE)
# Also try meta tag
CSRF_META_RE = re.compile(r'data-csrfkey="([a-f0-9]+)"', re.IGNORECASE)

BASE = "https://deadlystream.com"
LOGIN_URL = f"{BASE}/login/"


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
        # BeautifulSoup fallback
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("input", {"name": "csrfKey"})
        if tag and tag.get("value"):
            return tag["value"]
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
                "Login failed — check your username/password. "
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
    ) -> Path:
        """
        Download a (single-file) submission from deadlystream.

        progress_callback(bytes_downloaded, total_bytes, filename)
        cancel_event: set() to abort mid-download
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
            referer=page_url,
        )

    def get_file_info(self, file_id: str, slug: str = "") -> dict:
        return self._get_file_info(file_id, slug)

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
            # Single-file submission — fall back to the primary download URL.
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
    ) -> list[Path]:
        """
        Download every file in a (possibly multi-file) submission.
        Returns the list of downloaded local paths in page order.
        """
        records = self.list_download_records(file_id, slug)
        referer = self._file_page_url(file_id, slug)
        paths: list[Path] = []
        for idx, rec in enumerate(records):
            if cancel_event and cancel_event.is_set():
                raise DownloadError("Download cancelled.")
            path = self._download_from_url(
                rec["url"], dest_dir, file_id,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                fallback_name=rec["name"],
                referer=referer,
            )
            paths.append(path)
        return paths

    def _download_from_url(
        self,
        download_url: str,
        dest_dir: Path,
        file_id: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        fallback_name: str = "",
        referer: str = "",
    ) -> Path:
        headers = {"Referer": referer} if referer else {}
        resp = self._session.get(
            download_url, stream=True, timeout=60, allow_redirects=True, headers=headers
        )
        resp.raise_for_status()

        # Guard: a logged-out / bad-CSRF / confirm-interstitial response comes
        # back as HTML (HTTP 200). Don't write an HTML page into a .zip.
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" in ctype:
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

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if cancel_event and cancel_event.is_set():
                    dest_path.unlink(missing_ok=True)
                    raise DownloadError("Download cancelled.")
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total, filename)
        return dest_path
