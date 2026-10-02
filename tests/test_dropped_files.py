"""Mods the app cannot download: the player adds the file to the mod folder and
the app picks it up, from the mod's own folder or loose in the folder root."""
import threading
import time

import pytest

import installer.pipeline as pl
from tests.test_pipeline_fixes import _mod, _pipeline


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(pl, "_DROP_POLL_SECONDS", 0.05)
    monkeypatch.setattr(pl, "_DROP_SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(pl, "_DROP_WAIT_SECONDS", 5)


def _manual_mod(name="Vurt's K1 Hi-Res Ebon Hawk Retexture", host="unknown"):
    m = _mod()
    m.file_id, m.slug, m.name = "guide:86", "vurt-s-k1-hi-res-ebon-hawk-ret", name
    m.source_host, m.url = host, "https://example.com/page"
    return m


def _later(delay, fn):
    threading.Timer(delay, fn).start()


def test_a_file_dropped_loose_in_the_mod_folder_is_picked_up_and_filed(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod()])
    root = tmp_path / "dl"
    root.mkdir()
    _later(0.2, lambda: (root / "vurt_k1_eh_retexture_v10.rar").write_bytes(b"Rar!data"))
    p._download_mod(p.mods[0])
    dest = p._mod_dir(p.mods[0]) / "vurt_k1_eh_retexture_v10.rar"
    assert dest.read_bytes() == b"Rar!data"
    assert not (root / "vurt_k1_eh_retexture_v10.rar").exists()     # filed, not copied
    assert p.mods[0].status.name == "READY"
    assert p.mods[0].archive_paths == [dest]


def test_a_file_put_in_the_mods_own_folder_works_too(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod()])
    folder = p._mod_dir(p.mods[0])
    _later(0.2, lambda: (folder.mkdir(parents=True, exist_ok=True),
                         (folder / "anything.zip").write_bytes(b"PKdata")))
    p._download_mod(p.mods[0])
    assert [a.name for a in p.mods[0].archive_paths] == ["anything.zip"]
    assert p.mods[0].status.name == "READY"


def test_a_file_that_is_still_being_copied_in_is_not_taken_early(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod()])
    root = tmp_path / "dl"
    root.mkdir()

    def copy_slowly():
        f = root / "vurt_retexture.zip"
        with open(f, "wb") as out:
            for _ in range(6):
                out.write(b"x" * 1000)
                out.flush()
                time.sleep(0.15)

    _later(0.1, copy_slowly)
    p._download_mod(p.mods[0])
    assert p.mods[0].archive_paths[0].stat().st_size == 6000


def test_with_several_loose_files_the_one_named_like_the_mod_is_taken(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod()])
    root = tmp_path / "dl"
    root.mkdir()
    (root / "unrelated-thing.zip").write_bytes(b"PKaaa")
    (root / "vurt_k1_eh_retexture_v10.rar").write_bytes(b"Rar!bbb")
    p._download_mod(p.mods[0])
    assert p.mods[0].archive_paths[0].name == "vurt_k1_eh_retexture_v10.rar"
    assert (root / "unrelated-thing.zip").exists()                   # left for its own mod


def test_several_loose_files_none_named_like_the_mod_are_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_DROP_WAIT_SECONDS", 0.6)
    p = _pipeline(tmp_path, [_manual_mod()])
    root = tmp_path / "dl"
    root.mkdir()
    (root / "one.zip").write_bytes(b"PKaaa")
    (root / "two.zip").write_bytes(b"PKbbb")
    p._download_mod(p.mods[0])
    assert p.mods[0].status.name == "ERROR"
    assert (root / "one.zip").exists() and (root / "two.zip").exists()


def test_gamefront_mods_wait_for_a_dropped_file_like_any_site_the_app_cannot_download_from(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod(host="gamefront")])
    root = tmp_path / "dl"
    root.mkdir()
    called = []
    p._client.download_all_files = lambda **kw: called.append(kw)
    _later(0.3, lambda: (root / "vurt_k1_eh_retexture_v10.rar").write_bytes(b"Rar!data"))
    p._download_mod(p.mods[0])
    assert not called                                   # nothing is fetched from DeadlyStream
    assert p.mods[0].status.name == "READY"
    assert p.mods[0].archive_paths[0].name == "vurt_k1_eh_retexture_v10.rar"


def test_stopping_ends_the_wait(tmp_path):
    p = _pipeline(tmp_path, [_manual_mod()])
    (tmp_path / "dl").mkdir()
    t = threading.Thread(target=p._download_mod, args=(p.mods[0],))
    t.start()
    time.sleep(0.3)
    p._stop_event.set()
    t.join(3)
    assert not t.is_alive()


def test_a_lone_unrelated_file_is_not_handed_to_the_waiting_mod(tmp_path, monkeypatch):
    """The 4GB Patcher once got an Ebon Hawk retexture because it was the only file."""
    monkeypatch.setattr(pl, "_DROP_WAIT_SECONDS", 0.6)
    p = _pipeline(tmp_path, [_manual_mod(name="4GB Patcher")])
    root = tmp_path / "dl"
    root.mkdir()
    (root / "vurt_k1_eh_retexture_v10.rar").write_bytes(b"Rar!data")
    p._download_mod(p.mods[0])
    assert p.mods[0].status.name == "ERROR"
    assert (root / "vurt_k1_eh_retexture_v10.rar").exists()
