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


def test_free_account_waits_for_the_nxm_click_then_downloads(tmp_path, monkeypatch):
    import threading
    from scraper import nexus

    broker = nexus.NxmBroker()
    got = {}

    def waiter():
        got["link"] = broker.wait("kotor", 5, 9, timeout=5)

    t = threading.Thread(target=waiter)
    t.start()
    broker.deliver(nexus.parse_nxm("nxm://kotor/mods/5/files/9?key=K&expires=123"))
    t.join(3)
    assert got["link"].key == "K" and got["link"].expires == "123"


def test_nxm_link_that_arrives_early_is_not_lost():
    from scraper import nexus
    broker = nexus.NxmBroker()
    broker.deliver(nexus.parse_nxm("nxm://kotor/mods/5/files/9?key=K&expires=1"))
    assert broker.wait("kotor", 5, 9, timeout=1).key == "K"


def test_wait_gives_up_when_stopped():
    import threading
    from scraper import nexus
    stop = threading.Event()
    stop.set()
    assert nexus.NxmBroker().wait("kotor", 1, 2, timeout=30, stop_event=stop) is None


def test_403_is_marked_as_the_free_account_case(monkeypatch):
    import io
    import urllib.error
    from scraper import nexus

    def boom(url, key, timeout=10):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO())

    monkeypatch.setattr(nexus, "_get_json", boom)
    try:
        nexus.download_link("KOTOR1", 1, 2, "KEY")
    except nexus.NexusAuthError as e:
        assert e.free_account
    else:
        raise AssertionError("expected NexusAuthError")


def test_links_for_other_nexus_games_are_refused():
    from scraper import nexus
    broker = nexus.NxmBroker()
    assert not broker.deliver(nexus.parse_nxm("nxm://skyrimspecialedition/mods/5/files/9?key=K&expires=1"))
    assert broker.deliver(nexus.parse_nxm("nxm://kotor2/mods/5/files/9?key=K&expires=1"))


def test_another_games_link_with_the_same_ids_does_not_satisfy_a_wait():
    from scraper import nexus
    broker = nexus.NxmBroker()
    broker.deliver(nexus.parse_nxm("nxm://kotor2/mods/5/files/9?key=K2&expires=1"))
    assert broker.wait("kotor", 5, 9, timeout=1) is None
    assert broker.wait("kotor2", 5, 9, timeout=1).key == "K2"


def test_broker_reports_when_the_first_wait_starts_and_the_last_ends():
    import threading
    from scraper import nexus
    events = []
    broker = nexus.NxmBroker(on_active=events.append)
    t = threading.Thread(target=lambda: broker.wait("kotor", 1, 1, timeout=5))
    t.start()
    for _ in range(50):
        if events:
            break
        threading.Event().wait(0.05)
    assert events == [True]
    broker.deliver(nexus.parse_nxm("nxm://kotor/mods/1/files/1?key=K&expires=1"))
    t.join(3)
    assert events == [True, False]


def test_on_waiting_runs_after_the_app_is_told_to_claim_links():
    import threading
    from scraper import nexus
    order = []
    broker = nexus.NxmBroker(on_active=lambda a: order.append(("active", a)))
    t = threading.Thread(target=lambda: broker.wait(
        "kotor", 1, 1, timeout=5, on_waiting=lambda: order.append("page opened")))
    t.start()
    for _ in range(50):
        if "page opened" in order:
            break
        threading.Event().wait(0.05)
    broker.deliver(nexus.parse_nxm("nxm://kotor/mods/1/files/1?key=K&expires=1"))
    t.join(3)
    assert order[:2] == [("active", True), "page opened"]


def test_cdn_url_with_spaces_is_escaped_and_the_rest_left_alone():
    from scraper import nexus
    raw = ("https://cf-files.nexusmods.com/cdn/234/1368/Ultimate Dantooine High "
           "Resolution - TPC Version-1368-1-2.rar?expires=1790806585&md5=ydEp6xYSoJRNNXr-YRoUpw&user_id=4078484")
    out = nexus._escape_url(raw)
    assert " " not in out
    assert "Ultimate%20Dantooine%20High%20Resolution%20-%20TPC%20Version-1368-1-2.rar" in out
    assert out.endswith("?expires=1790806585&md5=ydEp6xYSoJRNNXr-YRoUpw&user_id=4078484")
    assert nexus._escape_url(out) == out  # already-escaped URLs are unchanged


def test_download_file_requests_the_escaped_url(tmp_path, monkeypatch):
    from scraper import nexus
    monkeypatch.setattr(nexus, "file_info", lambda *a, **k: {"file_name": "m.rar"})
    monkeypatch.setattr(nexus, "download_link", lambda *a, **k: "https://cdn/x/My Mod.rar?e=1")
    seen = []

    class R:
        headers = {"Content-Length": "2"}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n, _d=[b"PK", b""]): return _d.pop(0) if _d else b""

    def fake_open(req, timeout=0):
        seen.append(req.full_url)
        return R()

    monkeypatch.setattr(nexus.urllib.request, "urlopen", fake_open)
    nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY")
    assert seen == ["https://cdn/x/My%20Mod.rar?e=1"]
