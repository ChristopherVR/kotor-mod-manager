"""Steam installs of KOTOR are found, including extra Steam libraries."""
import sys

import pytest

from installer import game_locator

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux Steam layout")


def _game(folder):
    folder.mkdir(parents=True)
    (folder / "chitin.key").write_bytes(b"KEY")
    return folder


def test_finds_games_in_main_and_extra_libraries(tmp_path, monkeypatch):
    home = tmp_path / "home"
    steam = home / ".local/share/Steam"
    k1 = _game(steam / "steamapps/common/swkotor")
    extra = tmp_path / "games" / "SteamLibrary"
    k2 = _game(extra / "SteamApps/Common/Knights of the Old Republic II")
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0"\n {\n  "path"\t\t"%s"\n }\n "1"\n {\n  "path"\t\t"%s"\n }\n}\n'
        % (steam, extra))
    monkeypatch.setattr(game_locator.Path, "home", classmethod(lambda cls: home))

    found = {(g["game"], g["path"]) for g in game_locator.find_game_installs()}
    assert found == {("KOTOR1", str(k1)), ("KOTOR2", str(k2))}


def test_ignores_empty_game_folder_and_missing_steam(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local/share/Steam/steamapps/common/swkotor").mkdir(parents=True)
    monkeypatch.setattr(game_locator.Path, "home", classmethod(lambda cls: home))
    assert game_locator.find_game_installs() == []
