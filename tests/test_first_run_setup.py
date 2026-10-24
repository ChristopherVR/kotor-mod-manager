"""The first-run setup shows once on a fresh install and never again.

Players who used the app before the setup existed already have their accounts
and games set up, so they must not be walked through it after an update.
"""
import config


def _fresh_config(tmp_path, monkeypatch):
    # Point config at a throwaway file so we don't touch the real user config.
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    return config


def test_fresh_install_shows_setup_until_it_is_finished(tmp_path, monkeypatch):
    _fresh_config(tmp_path, monkeypatch)
    from backend import server

    assert server.setup_state()["show"] is True
    server.setup_done()
    assert server.setup_state()["show"] is False


def test_finishing_setup_skips_the_release_notes_for_this_version(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    from backend import server

    server.setup_done()
    assert cfg.load()["last_seen_version"] == server.__version__
    assert server.whatsnew()["show"] is False


def test_existing_players_are_not_sent_through_setup(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    from backend import server

    conf = cfg.load()
    conf["last_seen_version"] = "0.19.10"
    cfg.save(conf)
    assert server.setup_state()["show"] is False
