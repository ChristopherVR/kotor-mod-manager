"""Users can add their own mod builds (guide pages) on top of the built-in ones."""
import config


def _fresh_config(tmp_path, monkeypatch):
    # Point config at a throwaway file so we don't touch the real user config.
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    return config


def test_add_list_remove_custom_build(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    assert cfg.get_custom_builds() == []

    b = cfg.add_custom_build("My K2 Build", "KOTOR2", "https://example.com/guide")
    assert b["key"].startswith("custom_")
    assert b["game"] == "KOTOR2"

    assert cfg.get_custom_build(b["key"]) == b
    assert len(cfg.get_custom_builds()) == 1

    assert cfg.remove_custom_build(b["key"]) is True
    assert cfg.get_custom_builds() == []
    assert cfg.remove_custom_build(b["key"]) is False   # already gone


def test_resolve_build_game_for_custom(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    import backend.server as server  # server reads the same patched config module

    b = cfg.add_custom_build("Custom", "KOTOR2", "https://example.com/g")
    assert server._resolve_build_game(b["key"]) == "KOTOR2"
    assert server._resolve_build_game("k1_full") == "KOTOR1"
    # Custom build appears alongside the built-ins.
    keys = [x["key"] for x in server._all_builds()]
    assert b["key"] in keys and "k1_full" in keys
