"""A damaged settings file must not brick the app (issue #52).

If ~/.kotor_mod_installer/config.json ends up empty or half-written, every
settings action used to fail silently. Loading now falls back to defaults, and
saving is atomic so the file never gets truncated in the first place.
"""
import json

import config


def _fresh_config(tmp_path, monkeypatch):
    # Point config at a throwaway file so we don't touch the real user config.
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    return config


def _write_raw(cfg, content: bytes) -> None:
    cfg.CONFIG_FILE.write_bytes(content)


def test_empty_config_file_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b"")

    data = cfg.load()

    assert data["download_dir"] == config.DEFAULTS["download_dir"]
    # The file is rewritten with usable settings, so the next launch is fine too.
    assert json.loads(cfg.CONFIG_FILE.read_text(encoding="utf-8"))["language"] == "en"
    # The unreadable original is kept aside rather than thrown away.
    assert (tmp_path / "config.json.corrupt").exists()


def test_truncated_json_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b'{"language": "en", "kotor1_pa')

    data = cfg.load()

    assert data["language"] == "en"
    assert json.loads(cfg.CONFIG_FILE.read_text(encoding="utf-8"))
    assert (tmp_path / "config.json.corrupt").exists()


def test_non_utf8_config_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b"\xff\xfe\x00garbage")

    data = cfg.load()

    assert data["auto_install"] is False
    assert (tmp_path / "config.json.corrupt").exists()


def test_json_that_is_not_an_object_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b"[1, 2, 3]")

    data = cfg.load()

    assert isinstance(data, dict)
    assert data["language"] == "en"
    assert (tmp_path / "config.json.corrupt").exists()


def test_settings_still_save_after_corruption(tmp_path, monkeypatch):
    """The user-visible symptom: settings silently refusing to save."""
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b"")

    prof = cfg.add_profile("My KOTOR", "KOTOR1", r"C:\Games\KOTOR")

    assert cfg.get_profile(prof["id"])["name"] == "My KOTOR"
    assert cfg.load()["kotor1_path"] == r"C:\Games\KOTOR"

    assert cfg.set_active_profile(prof["id"]) is True
    assert cfg.load()["active_profile"] == prof["id"]

    build = cfg.add_custom_build("My Build", "KOTOR2", "https://example.com/g")
    assert cfg.get_custom_build(build["key"]) is not None


def test_recovering_does_not_contaminate_the_built_in_defaults(tmp_path, monkeypatch):
    """Settings handed back after a reset must be the user's own copy, or the
    next profile they add leaks into what every later reset starts from."""
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b"")

    cfg.add_profile("Mine", "KOTOR1", r"C:\Games\KOTOR")

    assert config.DEFAULTS["game_profiles"] == []
    assert config.DEFAULTS["custom_builds"] == []
    assert config.DEFAULTS["kotor1_path"] == ""


def test_settings_saved_by_an_older_version_do_not_contaminate_defaults(tmp_path, monkeypatch):
    """A config from before custom builds existed has no custom_builds key, so
    the merge with the defaults must not hand back the shared list."""
    cfg = _fresh_config(tmp_path, monkeypatch)
    _write_raw(cfg, b'{"language": "en", "game_profiles": [], "active_profile": ""}')

    cfg.add_custom_build("My Build", "KOTOR2", "https://example.com/g")

    assert config.DEFAULTS["custom_builds"] == []
    assert len(cfg.get_custom_builds()) == 1


def test_good_config_is_left_alone(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)
    cfg.save({**config.DEFAULTS, "language": "fr", "game_profiles": [
        {"id": "KOTOR1", "name": "KOTOR 1", "game": "KOTOR1", "path": ""},
    ]})

    data = cfg.load()

    assert data["language"] == "fr"
    assert not (tmp_path / "config.json.corrupt").exists()


def test_save_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    cfg = _fresh_config(tmp_path, monkeypatch)

    cfg.save(config.DEFAULTS.copy())

    assert cfg.CONFIG_FILE.exists()
    assert not (tmp_path / "config.json.tmp").exists()


def test_failed_save_keeps_the_previous_settings(tmp_path, monkeypatch):
    """A crash part-way through writing must not truncate config.json."""
    cfg = _fresh_config(tmp_path, monkeypatch)
    cfg.save({**config.DEFAULTS, "language": "de"})

    def boom(*args, **kwargs):
        raise KeyboardInterrupt("process died mid-write")

    # Scoped so only json.dump is restored afterwards, not the config paths.
    with monkeypatch.context() as m:
        m.setattr(config.json, "dump", boom)
        try:
            cfg.save({**config.DEFAULTS, "language": "es"})
        except KeyboardInterrupt:
            pass

    # The old settings survived intact - no 0-byte file, nothing to recover from.
    assert cfg.CONFIG_FILE.stat().st_size > 0
    assert cfg.load()["language"] == "de"
    assert not (tmp_path / "config.json.corrupt").exists()
    assert not (tmp_path / "config.json.tmp").exists()
