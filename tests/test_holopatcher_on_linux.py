"""A mod's bundled HoloPatcher.exe is a Windows program. On Linux the app runs
its own HoloPatcher instead of trying to start the mod's copy."""
import os
import stat
import sys

import pytest

from installer import runner
from installer.runner import PatcherError, run_holopatcher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux and macOS only")


def _mod_with_windows_holopatcher(tmp_path):
    mod = tmp_path / "Kebla Yurt Revamp"
    (mod / "tslpatchdata").mkdir(parents=True)
    exe = mod / "HoloPatcher.exe"
    exe.write_bytes(b"MZ not runnable here")          # no execute permission, like a download
    return exe, mod / "tslpatchdata"


def _fake_shim(tmp_path):
    shim = tmp_path / "bundled" / "HoloPatcher"
    shim.parent.mkdir()
    shim.write_text('#!/bin/sh\necho "ran with: $@"\nexit 0\n')
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return shim


def test_the_apps_own_holopatcher_runs_instead_of_the_mods_exe(tmp_path, monkeypatch):
    exe, td = _mod_with_windows_holopatcher(tmp_path)
    shim = _fake_shim(tmp_path)
    monkeypatch.setattr("installer.config_loader.find_system_holopatcher", lambda: shim)
    lines = []
    run_holopatcher(exe, tmp_path / "game", td, 0, cb=lines.append)
    text = "\n".join(lines)
    assert "using the app's own HoloPatcher" in text
    assert "--game-dir" in text and "--tslpatchdata" in text and "--install" in text


def test_namespace_options_are_passed_on_to_the_apps_holopatcher(tmp_path, monkeypatch):
    exe, td = _mod_with_windows_holopatcher(tmp_path)
    shim = _fake_shim(tmp_path)
    monkeypatch.setattr("installer.config_loader.find_system_holopatcher", lambda: shim)
    lines = []
    run_holopatcher(exe, tmp_path / "game", td, 2, cb=lines.append)
    assert "--namespace-option-index 2" in "\n".join(lines)


def test_without_the_apps_own_holopatcher_the_error_says_why(tmp_path, monkeypatch):
    exe, td = _mod_with_windows_holopatcher(tmp_path)
    monkeypatch.setattr("installer.config_loader.find_system_holopatcher", lambda: None)
    with pytest.raises(PatcherError, match="Windows program"):
        run_holopatcher(exe, tmp_path / "game", td, 0)


def test_a_mod_without_info_rtf_gets_a_blank_one_so_the_patcher_does_not_wait(tmp_path, monkeypatch):
    exe, td = _mod_with_windows_holopatcher(tmp_path)
    shim = tmp_path / "bundled" / "HoloPatcher"
    shim.parent.mkdir()
    shim.write_text('#!/bin/sh\nls "$4"\nexit 0\n')        # $4 is the tslpatchdata folder
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr("installer.config_loader.find_system_holopatcher", lambda: shim)
    lines = []
    run_holopatcher(exe, tmp_path / "game", td, 0, cb=lines.append)
    assert "info.rtf" in "\n".join(lines)
    assert (td / "info.rtf").read_text() == "{\\rtf1\\ansi }"


def test_an_existing_info_rtf_is_left_alone_whatever_its_case(tmp_path, monkeypatch):
    exe, td = _mod_with_windows_holopatcher(tmp_path)
    (td / "Info.RTF").write_text("the author's notes")
    monkeypatch.setattr("installer.config_loader.find_system_holopatcher",
                        lambda: _fake_shim(tmp_path))
    run_holopatcher(exe, tmp_path / "game", td, 0)
    assert [p.name for p in td.iterdir()] == ["Info.RTF"]
    assert (td / "Info.RTF").read_text() == "the author's notes"
