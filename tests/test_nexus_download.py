"""Tests for Nexus sign-in and downloading.

The key behaviour to pin down is the free-vs-Premium split: a free account can
only download with the short-lived key/expires pair minted by clicking
"Mod manager download" on the site, and without it Nexus answers 403. That is an
account tier rule, so the error has to say so rather than look like a bad key.
"""

import urllib.error
from pathlib import Path

import pytest

from scraper import nexus


# ---------------------------------------------------------------------------
# nxm:// parsing
# ---------------------------------------------------------------------------

def test_parses_a_free_account_link_with_its_key():
    link = nexus.parse_nxm(
        "nxm://kotor/mods/1364/files/2213?key=abc123&expires=1785055347")
    assert (link.game_domain, link.mod_id, link.file_id) == ("kotor", 1364, 2213)
    assert link.key == "abc123"
    assert link.expires == "1785055347"
    assert link.is_free_account_link


def test_parses_a_premium_link_without_a_key():
    link = nexus.parse_nxm("nxm://kotor2/mods/99/files/12")
    assert (link.game_domain, link.mod_id, link.file_id) == ("kotor2", 99, 12)
    assert not link.is_free_account_link


def test_rejects_a_non_nxm_url():
    with pytest.raises(ValueError):
        nexus.parse_nxm("https://www.nexusmods.com/kotor/mods/1364")


# ---------------------------------------------------------------------------
# download_link
# ---------------------------------------------------------------------------

def _http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, None)


def test_free_account_403_explains_the_tier_limit(monkeypatch):
    """A 403 here means 'no Premium and no nxm key', not 'bad key'. Saying
    'invalid key' would send the player off resetting a working credential."""
    monkeypatch.setattr(nexus, "_get_json",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(403)))
    with pytest.raises(nexus.NexusAuthError) as e:
        nexus.download_link("KOTOR1", 1364, 2213, "apikey")
    msg = str(e.value).lower()
    assert "premium" in msg and "mod manager download" in msg


def test_bad_key_is_reported_as_a_rejected_key(monkeypatch):
    monkeypatch.setattr(nexus, "_get_json",
                        lambda *a, **k: (_ for _ in ()).throw(_http_error(401)))
    with pytest.raises(nexus.NexusAuthError, match="rejected the API key"):
        nexus.download_link("KOTOR1", 1364, 2213, "apikey")


def test_nxm_credentials_are_sent_as_query_parameters(monkeypatch):
    seen = {}

    def fake(url, key, timeout=10):
        seen["url"] = url
        return [{"URI": "https://cdn.example/file.rar"}]

    monkeypatch.setattr(nexus, "_get_json", fake)
    uri = nexus.download_link("KOTOR1", 1364, 2213, "apikey",
                              nxm_key="k1", nxm_expires="999")
    assert uri == "https://cdn.example/file.rar"
    assert "key=k1" in seen["url"] and "expires=999" in seen["url"]


def test_premium_request_carries_no_query_parameters(monkeypatch):
    seen = {}

    def fake(url, key, timeout=10):
        seen["url"] = url
        return [{"URI": "https://cdn.example/file.rar"}]

    monkeypatch.setattr(nexus, "_get_json", fake)
    nexus.download_link("KOTOR1", 1364, 2213, "apikey")
    assert "?" not in seen["url"]


def test_empty_response_is_a_download_error(monkeypatch):
    monkeypatch.setattr(nexus, "_get_json", lambda *a, **k: [])
    with pytest.raises(nexus.NexusDownloadError):
        nexus.download_link("KOTOR1", 1364, 2213, "apikey")


# ---------------------------------------------------------------------------
# Credential storage
# ---------------------------------------------------------------------------

def test_keyring_value_wins_over_the_plain_text_config(monkeypatch):
    monkeypatch.setattr(nexus, "keyring",
                        type("K", (), {"get_password": staticmethod(
                            lambda s, u: "from-keyring")}))
    assert nexus.load_api_key("from-config") == "from-keyring"


def test_falls_back_to_config_when_nothing_is_stored(monkeypatch):
    monkeypatch.setattr(nexus, "keyring",
                        type("K", (), {"get_password": staticmethod(
                            lambda s, u: None)}))
    assert nexus.load_api_key("from-config") == "from-config"


def test_sign_in_does_not_store_an_invalid_key(monkeypatch):
    saved = []
    monkeypatch.setattr(nexus, "validate", lambda k: {"ok": False, "error": "invalid"})
    monkeypatch.setattr(nexus, "save_api_key", lambda k: saved.append(k))
    assert nexus.sign_in("bad")["ok"] is False
    assert saved == []


def test_sign_in_stores_a_valid_key_and_reports_tier(monkeypatch):
    saved = []
    monkeypatch.setattr(nexus, "validate",
                        lambda k: {"ok": True, "name": "Stoofie3", "is_premium": False})
    monkeypatch.setattr(nexus, "save_api_key", lambda k: saved.append(k))
    out = nexus.sign_in("good")
    assert out["ok"] and out["is_premium"] is False
    assert saved == ["good"]


def test_download_from_nxm_forwards_the_link_credentials(monkeypatch, tmp_path):
    captured = {}

    def fake_download(game, mod_id, file_id, dest_dir, api_key,
                      nxm_key="", nxm_expires="", **kw):
        captured.update(mod_id=mod_id, file_id=file_id,
                        nxm_key=nxm_key, nxm_expires=nxm_expires)
        return Path(dest_dir) / "x.rar"

    monkeypatch.setattr(nexus, "download_file", fake_download)
    nexus.download_from_nxm(
        "nxm://kotor/mods/1364/files/2213?key=kk&expires=77", tmp_path, "apikey")
    assert captured == {"mod_id": 1364, "file_id": 2213,
                        "nxm_key": "kk", "nxm_expires": "77"}
