"""Widescreen program-file setup: consent first, original kept, redo and undo work."""
import threading

import pytest

import config as cfg
from installer import exe_setup
from tests.test_exe_patch import INI, _fake_exe
from tests.test_pipeline_fixes import _mod, _pipeline


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    g = tmp_path / "game"
    g.mkdir()
    (g / "swkotor.exe").write_bytes(bytes(_fake_exe()))
    return g


def _run(game, confirm=lambda t, b: True, res="1920x1080", fetch=lambda: None, steps=("uniws", "hrmenus", "laa")):
    logs = []
    ok = exe_setup.run(game, list(steps), res, INI, confirm=confirm, fetch_base=fetch,
                       log=lambda m, t: logs.append(m))
    return ok, logs


def test_declining_changes_nothing(game):
    before = (game / "swkotor.exe").read_bytes()
    ok, _ = _run(game, confirm=lambda t, b: False)
    assert not ok
    assert (game / "swkotor.exe").read_bytes() == before
    assert not (game / "swkotor.exe.bak").exists()


def test_original_is_kept_and_patches_can_be_redone_then_undone(game):
    original = (game / "swkotor.exe").read_bytes()
    assert _run(game)[0]
    assert (game / "swkotor.exe.bak").read_bytes() == original
    first = (game / "swkotor.exe").read_bytes()
    assert first != original
    assert _run(game, res="2560x1440")[0]                    # redo from the original
    assert (game / "swkotor.exe.bak").read_bytes() == original
    assert (game / "swkotor.exe").read_bytes() != first
    assert exe_setup.restore_original(game)
    assert (game / "swkotor.exe").read_bytes() == original
    assert not (game / "swkotor.exe.bak").exists()


def test_a_program_file_that_does_not_fit_is_left_alone(game):
    bad = bytearray(_fake_exe())
    bad[0x1000:0x1010] = bytes(16)                           # signature gone
    (game / "swkotor.exe").write_bytes(bytes(bad))
    ok, logs = _run(game)
    assert not ok
    assert (game / "swkotor.exe").read_bytes() == bytes(bad)
    assert not (game / "swkotor.exe.bak").exists()
    assert any("Nothing was changed" in m for m in logs)


def test_steam_program_file_needs_the_unprotected_one_and_asks_about_it(game, tmp_path):
    steam = bytes(_fake_exe(steam=True))
    (game / "swkotor.exe").write_bytes(steam)
    asked = []
    plain = tmp_path / "plain.exe"
    plain.write_bytes(bytes(_fake_exe()))
    ok, _ = _run(game, confirm=lambda t, b: asked.append(b) or True, fetch=lambda: plain)
    assert ok
    assert "copy protection" in asked[0]
    assert (game / "swkotor.exe.bak").read_bytes() == steam
    assert exe_setup.restore_original(game)
    assert (game / "swkotor.exe").read_bytes() == steam


def test_steam_without_a_download_is_left_alone(game):
    steam = bytes(_fake_exe(steam=True))
    (game / "swkotor.exe").write_bytes(steam)
    assert not _run(game)[0]
    assert (game / "swkotor.exe").read_bytes() == steam


def test_gui_set_is_the_closest_fit_and_replaced_files_are_saved(game, tmp_path):
    mod = tmp_path / "mod"
    for d in ("16-by-9/gui.1920x1080", "16-by-9/gui.3840x2160", "4-by-3/gui.1024x768"):
        (mod / d).mkdir(parents=True)
        (mod / d / "mainmenu.gui").write_text(d)
    assert exe_setup.pick_gui_set(mod, 3840, 2160).name == "gui.3840x2160"
    assert exe_setup.pick_gui_set(mod, 2560, 1440).name == "gui.1920x1080"
    (game / "Override").mkdir()
    (game / "Override" / "mainmenu.gui").write_text("old")
    assert exe_setup.copy_gui_set(mod, game, "3840x2160", "KOTOR1", lambda m, t: None)
    assert (game / "Override" / "mainmenu.gui").read_text() == "16-by-9/gui.3840x2160"
    assert (cfg.CONFIG_DIR / "exe_patch" / "KOTOR1-gui-backup" / "mainmenu.gui").read_text() == "old"


def test_confirm_waits_for_the_answer_and_never_assumes_yes(tmp_path):
    p = _pipeline(tmp_path, [_mod()])
    assert p.confirm("t", "b") == ""                          # nobody to ask
    asked = []
    p._on_confirm = lambda rid, t, b, o: asked.append(rid)
    out = []
    t = threading.Thread(target=lambda: out.append(p.confirm("t", "b")))
    t.start()
    while not asked:
        t.join(0.05)
    assert p.answer_confirm(asked[0], "continue")
    t.join(3)
    assert out == ["continue"]
    assert not p.answer_confirm(asked[0], "continue")         # already answered

    # The app always sends unattended=True; the question must still be shown.
    p._auto_unattended = True
    asked.clear()
    t = threading.Thread(target=lambda: out.append(p.confirm("t", "b")))
    t.start()
    while not asked:
        t.join(0.05)
    p.answer_confirm(asked[0], "skip")
    t.join(3)
    assert out[-1] == "skip"


def test_stopping_ends_a_question(tmp_path):
    p = _pipeline(tmp_path, [_mod()])
    p._on_confirm = lambda *a: None
    out = []
    t = threading.Thread(target=lambda: out.append(p.confirm("t", "b")))
    t.start()
    t.join(0.3)
    p._stop_event.set()
    t.join(3)
    assert out == [""]


def test_ini_screen_size_is_set_in_place_and_the_original_kept(tmp_path):
    from installer import game_settings
    ini = tmp_path / "swkotor.ini"
    ini.write_bytes(b"[Game Options]\r\nWidth=1\r\n[Graphics Options]\r\nFullScreen=1\r\nWidth=800\r\nheight=600\r\nVSync=0\r\n")
    assert game_settings.set_resolution(tmp_path, 3840, 2160) == ini
    assert ini.read_bytes() == (b"[Game Options]\r\nWidth=1\r\n[Graphics Options]\r\nFullScreen=1\r\n"
                                b"Width=3840\r\nHeight=2160\r\nVSync=0\r\n")
    assert (tmp_path / "swkotor.ini.orig").read_bytes().count(b"800") == 1
    ini.write_bytes(b"[Graphics Options]\nFullScreen=1\n")
    game_settings.set_resolution(tmp_path, 1920, 1080)
    assert b"Width=1920" in ini.read_bytes() and b"Height=1080" in ini.read_bytes()
    assert game_settings.set_resolution(tmp_path / "nowhere", 1, 1) is None
