"""Free Nexus accounts: the "Mod manager download" clicks are collected ahead of
the downloads, so the downloads then run without the player watching."""
import threading
import time

import pytest

from scraper import nexus
from installer.pipeline import ModStatus
from tests.test_pipeline_fixes import _mod, _pipeline


def _nexus_mod(i):
    m = _mod()
    m.file_id = f"guide:{i}"
    m.slug = f"mod-{i}"
    m.name = f"Mod {i}"
    m.source_host = "nexus"
    m.url = f"https://www.nexusmods.com/kotor/mods/{1000 + i}"
    return m


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A fresh broker, a fake Nexus account, and a 'browser' that records the
    pages it is asked to open and clicks the button for each."""
    broker = nexus.NxmBroker()
    monkeypatch.setattr(nexus, "NXM", broker)
    monkeypatch.setattr(nexus, "load_api_key", lambda fallback="": "KEY")
    state = {"premium": False, "opened": [], "click": True}
    monkeypatch.setattr(nexus, "validate",
                        lambda key: {"ok": True, "name": "x", "is_premium": state["premium"]})
    monkeypatch.setattr(nexus, "list_files", lambda g, m, k: [
        {"file_id": m + 1, "file_name": f"{m}.zip", "category_name": "MAIN", "is_primary": True}])

    def open_page(url):
        state["opened"].append(url)
        if state["click"]:
            mod_id = int(url.split("/mods/")[1].split("?")[0])
            link = nexus.parse_nxm(f"nxm://kotor/mods/{mod_id}/files/{mod_id + 1}?key=K{mod_id}&expires=9")
            threading.Timer(0.05, broker.deliver, args=(link,)).start()

    import webbrowser
    monkeypatch.setattr(webbrowser, "open", open_page)
    state["broker"] = broker
    return state


def _run_queue(p, mods):
    p._start_click_queue(list(p.mods))
    deadline = time.time() + 10
    while not p._nxm_queue_done.is_set() and time.time() < deadline:
        time.sleep(0.05)


def test_every_page_opens_up_front_one_after_another(env, tmp_path):
    p = _pipeline(tmp_path, [_nexus_mod(1), _nexus_mod(2), _nexus_mod(3)])
    _run_queue(p, p.mods)
    assert [u.split("/mods/")[1].split("?")[0] for u in env["opened"]] == ["1001", "1002", "1003"]
    # All three links are held, ready for their downloads, with no download started.
    assert len(p._nxm_links) == 3
    assert not p._dl_started


def test_a_download_uses_the_link_it_already_has_without_opening_a_page(env, tmp_path, monkeypatch):
    p = _pipeline(tmp_path, [_nexus_mod(1)])
    _run_queue(p, p.mods)
    opened_before = len(env["opened"])
    used = {}

    def fake_download(game, mod_id, file_id, dest, key, nxm_key="", nxm_expires="", **kw):
        if not nxm_key:
            raise nexus.NexusAuthError("free", free_account=True)
        used["key"] = nxm_key
        f = dest / "m.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return f

    monkeypatch.setattr(nexus, "download_file", fake_download)
    p._download_mod(p.mods[0])
    assert used["key"] == "K1001"
    assert len(env["opened"]) == opened_before  # no second page
    assert p.mods[0].status == ModStatus.READY


def test_premium_accounts_are_never_asked_to_click(env, tmp_path):
    env["premium"] = True
    p = _pipeline(tmp_path, [_nexus_mod(1), _nexus_mod(2)])
    _run_queue(p, p.mods)
    assert env["opened"] == []


def test_mods_already_downloaded_are_left_alone(env, tmp_path):
    mods = [_nexus_mod(1), _nexus_mod(2)]
    p = _pipeline(tmp_path, mods)
    done = p._mod_dir(p.mods[0])
    done.mkdir(parents=True)
    (done / "a.zip").write_bytes(b"PK")
    p._write_cache_manifest(done, [done / "a.zip"])
    _run_queue(p, p.mods)
    assert [u.split("/mods/")[1].split("?")[0] for u in env["opened"]] == ["1002"]


def test_no_click_in_time_stops_asking_and_later_mods_ask_for_themselves(env, tmp_path, monkeypatch):
    import installer.pipeline as pl
    monkeypatch.setattr(pl, "_NXM_CLICK_TIMEOUT", 0.6)
    env["click"] = False
    p = _pipeline(tmp_path, [_nexus_mod(1), _nexus_mod(2)])
    _run_queue(p, p.mods)
    assert len(env["opened"]) == 1           # did not flood the browser with the rest
    assert not p._nxm_pending_mods           # downloads will not wait for a dead queue


def test_a_link_that_expired_before_its_turn_asks_again(env, tmp_path, monkeypatch):
    badges = []
    p = _pipeline(tmp_path, [_nexus_mod(1)],
                  on_status=lambda fid, st, detail: badges.append(detail))
    _run_queue(p, p.mods)
    seen = []

    def fake_download(game, mod_id, file_id, dest, key, nxm_key="", nxm_expires="", **kw):
        seen.append(nxm_key)
        if not nxm_key or nxm_key == "K1001" and len(seen) <= 2:
            raise nexus.NexusAuthError("free / expired", free_account=True)
        f = dest / "m.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return f

    monkeypatch.setattr(nexus, "download_file", fake_download)
    p._download_mod(p.mods[0])
    assert p.mods[0].status == ModStatus.READY
    assert len(env["opened"]) == 2            # the one ahead, then a fresh ask
    assert "Nexus link expired, click again" in badges  # and the badge says why


def test_badge_returns_to_pending_while_a_click_waits_for_its_turn(env, tmp_path):
    seen = []
    p = _pipeline(tmp_path, [_nexus_mod(1)],
                  on_status=lambda fid, st, detail: seen.append((st.name, detail)))
    _run_queue(p, p.mods)
    assert ("DOWNLOADING", "Waiting for your click on Nexus") in seen
    assert p.mods[0].status == ModStatus.PENDING


def test_hold_keeps_links_claimed_across_the_whole_run():
    events = []
    b = nexus.NxmBroker(on_active=events.append)
    with b.hold():
        b.wait("kotor", 1, 1, timeout=0.3)
        b.wait("kotor", 2, 2, timeout=0.3)
    assert events == [True, False]   # not False/True/False/True between waits


def test_full_run_opens_each_page_once_downloads_unattended_and_installs_in_order(env, tmp_path, monkeypatch):
    mods = [_nexus_mod(1), _nexus_mod(2), _nexus_mod(3)]
    p = _pipeline(tmp_path, mods)
    order = []

    def fake_download(game, mod_id, file_id, dest, key, nxm_key="", nxm_expires="", **kw):
        if not nxm_key:
            raise nexus.NexusAuthError("free", free_account=True)
        f = dest / f"{mod_id}.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return f

    monkeypatch.setattr(nexus, "download_file", fake_download)
    p._extract_and_install = lambda pm: order.append(pm.build_mod.file_id)
    p._capture_baseline_once = lambda: None
    p._apply_layer_order = lambda: None
    p._resolve_skip_constraints = lambda: None
    p._check_dependencies = lambda: None
    p._log_overlap_summary = lambda: None
    t = threading.Thread(target=p._run)
    t.start()
    t.join(20)
    assert not t.is_alive()
    assert len(env["opened"]) == 3            # one page each, none opened twice
    assert order == ["guide:1", "guide:2", "guide:3"]
    assert all(pm.status == ModStatus.READY for pm in p.mods)


def test_waiting_note_is_cleared_when_the_queued_link_arrives(env, tmp_path):
    seen = []
    p = _pipeline(tmp_path, [_nexus_mod(1)],
                  on_status=lambda fid, st, detail: seen.append((st.name, detail)))
    mod = p.mods[0].build_mod
    with p._nexus_lock:
        p._nxm_pending_mods = {mod.file_id}      # the click queue has not reached it
    p._nxm_queue_done.clear()
    link = nexus.parse_nxm("nxm://kotor/mods/1001/files/1002?key=K&expires=9")
    threading.Timer(0.3, lambda: p._nxm_links.__setitem__(("kotor", 1001, 1002), link)).start()
    got = p._link_for(p.mods[0], mod, 1001, 1002)
    assert got.key == "K"
    assert ("DOWNLOADING", "Waiting for your click on Nexus") in seen
    assert seen[-1] == ("DOWNLOADING", "")        # the note does not outlive the wait
