"""Downloaders for MEGA, GitHub, Google Drive and plain URLs (no network)."""
import base64
import json
import struct

import pytest

from scraper import hosts


class FakeResp:
    def __init__(self, body=b"", headers=None, url="https://x/y.zip", json_data=None, text=""):
        self._body, self.headers, self.url = body, headers or {}, url
        self._json, self.text = json_data, text
        self.status_code = 200

    def raise_for_status(self): pass
    def json(self): return self._json
    def iter_content(self, n): 
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]
    def close(self): pass


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def test_direct_download_uses_the_server_filename(tmp_path, monkeypatch):
    resp = FakeResp(b"PKdata", {"Content-Type": "application/zip",
                                "Content-Disposition": 'attachment; filename="My Mod.zip"',
                                "Content-Length": "6"})
    monkeypatch.setattr(hosts.requests.Session, "get", lambda self, *a, **k: resp)
    p = hosts.download_direct("https://x/dl", tmp_path)
    assert p.name == "My Mod.zip" and p.read_bytes() == b"PKdata"
    assert not list(tmp_path.glob("*.part"))


def test_html_instead_of_a_file_is_an_error(tmp_path, monkeypatch):
    resp = FakeResp(b"<html>", {"Content-Type": "text/html"})
    monkeypatch.setattr(hosts.requests.Session, "get", lambda self, *a, **k: resp)
    with pytest.raises(hosts.HostDownloadError, match="web page"):
        hosts.download_direct("https://x/dl", tmp_path)


def test_github_release_page_resolves_to_its_first_archive(monkeypatch):
    s = hosts._session()
    resp = FakeResp(json_data={"assets": [
        {"name": "notes.txt", "browser_download_url": "https://gh/notes.txt"},
        {"name": "mod.7z", "browser_download_url": "https://gh/mod.7z"}]})
    monkeypatch.setattr(s, "get", lambda *a, **k: resp)
    assert hosts._github_asset_url("https://github.com/o/r/releases", s) == "https://gh/mod.7z"
    assert hosts._github_asset_url("https://github.com/o/r/releases/download/v1/x.zip", s) \
        == "https://github.com/o/r/releases/download/v1/x.zip"


def test_google_drive_ids_and_folders():
    assert hosts._gdrive_id("https://drive.google.com/file/d/AbC_123-x/view?usp=sharing") == "AbC_123-x"
    assert hosts._gdrive_id("https://drive.google.com/uc?id=Q1w&export=download") == "Q1w"
    with pytest.raises(hosts.HostDownloadError):
        hosts._gdrive_id("https://drive.google.com/drive/folders/abc")


def test_mega_decrypts_a_file_it_was_given(tmp_path, monkeypatch):
    """Encrypt with MEGA's scheme, serve it, and check the download round-trips."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    plain = b"hello kotor mod " * 5000
    aes_key = bytes(range(1, 17))
    nonce = bytes(range(21, 29))
    k = struct.unpack(">4I", aes_key)
    n = struct.unpack(">2I", nonce)
    mac = (7, 8)  # the MAC half of the key; unused for decryption
    key32 = struct.pack(">8I", k[0] ^ n[0], k[1] ^ n[1], k[2] ^ mac[0], k[3] ^ mac[1],
                        n[0], n[1], mac[0], mac[1])
    iv = struct.pack(">4I", n[0], n[1], 0, 0)
    enc = Cipher(algorithms.AES(aes_key), modes.CTR(iv)).encryptor()
    cipher = enc.update(plain) + enc.finalize()
    attrs = b"MEGA" + json.dumps({"n": "Cool Mod.7z"}).encode()
    attrs += b"\0" * (-len(attrs) % 16)
    e = Cipher(algorithms.AES(aes_key), modes.CBC(b"\0" * 16)).encryptor()
    at = _b64(e.update(attrs) + e.finalize())

    # The real key the URL carries, recovered the way MEGA defines it.
    kk = struct.unpack(">8I", key32)
    assert struct.pack(">4I", kk[0] ^ kk[4], kk[1] ^ kk[5], kk[2] ^ kk[6], kk[3] ^ kk[7]) == aes_key

    api = FakeResp(json_data=[{"g": "https://cdn/file", "s": len(cipher), "at": at}])
    body = FakeResp(cipher, {"Content-Type": "application/octet-stream"})
    monkeypatch.setattr(hosts.requests.Session, "post", lambda self, *a, **k: api)
    monkeypatch.setattr(hosts.requests.Session, "get", lambda self, *a, **k: body)

    out = hosts.download_mega(f"https://mega.nz/file/AbCdEfGh#{_b64(key32)}", tmp_path)
    assert out.name == "Cool Mod.7z" and out.read_bytes() == plain


def test_mega_errors_and_folders_are_explained(tmp_path, monkeypatch):
    with pytest.raises(hosts.HostDownloadError, match="folder"):
        hosts.download_mega("https://mega.nz/folder/abc#def", tmp_path)
    key = _b64(bytes(32))
    monkeypatch.setattr(hosts.requests.Session, "post",
                        lambda self, *a, **k: FakeResp(json_data=[-9]))
    with pytest.raises(hosts.HostDownloadError, match="no longer exists"):
        hosts.download_mega(f"https://mega.nz/file/AbCdEfGh#{key}", tmp_path)


def test_pipeline_routes_a_mega_mod_to_the_mega_downloader(tmp_path, monkeypatch):
    from tests.test_pipeline_fixes import _mod, _pipeline
    mod = _mod()
    mod.source_host, mod.url = "mega", "https://mega.nz/file/x#y"
    p = _pipeline(tmp_path, [mod])
    seen = []

    def fake(host, url, dest, progress, cancel, pause):
        seen.append((host, url))
        f = dest / "m.7z"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"7z")
        return [f]

    monkeypatch.setattr(hosts, "download_from_host", fake)
    p._client.download_all_files = lambda **kw: (_ for _ in ()).throw(AssertionError("DeadlyStream used"))
    p._download_mod(p.mods[0])
    assert seen == [("mega", "https://mega.nz/file/x#y")]
    assert [a.name for a in p.mods[0].archive_paths] == ["m.7z"]
