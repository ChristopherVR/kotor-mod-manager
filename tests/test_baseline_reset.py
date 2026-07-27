"""Clean-game snapshot and reset.

Patcher mods rewrite dialog.tlk and the .2da tables in place, so there is no
per-mod undo for them: uninstalling a build of 154 patcher mods removes exactly
nothing. Restoring a snapshot taken before the first install is the only way
back, which is why the app takes one automatically.
"""

import json

import pytest

from installer import mod_manager


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A fake game tree with an isolated config dir."""
    root = tmp_path / "swkotor"
    (root / "Override").mkdir(parents=True)
    (root / "Modules").mkdir()
    (root / "dialog.tlk").write_bytes(b"vanilla-tlk")
    (root / "chitin.key").write_bytes(b"vanilla-key")
    for n in ("danm13.mod", "tar_m02aa.mod"):
        (root / "Modules" / n).write_bytes(b"stock")

    cfgdir = tmp_path / "cfg"
    cfgdir.mkdir()
    monkeypatch.setattr(mod_manager.cfg, "CONFIG_DIR", cfgdir)
    return root


def _install_some_mods(root):
    """Simulate a build: new Override files, a new module, a rewritten tlk."""
    for n in ("n_carth.tga", "feat.2da", "appearance.2da"):
        (root / "Override" / n).write_bytes(b"modded")
    (root / "Modules" / "new_area.mod").write_bytes(b"added")
    (root / "dialog.tlk").write_bytes(b"patched-tlk-much-longer")


def test_capture_records_the_clean_state(game):
    r = mod_manager.capture_baseline("KOTOR1", game)
    assert r["ok"]
    assert r["override"] == 0
    assert r["modules"] == 2
    assert "dialog.tlk" in r["files"]
    assert mod_manager.has_baseline("KOTOR1")


def test_reset_removes_added_files_and_restores_rewritten_ones(game):
    mod_manager.capture_baseline("KOTOR1", game)
    _install_some_mods(game)
    assert (game / "dialog.tlk").read_bytes() != b"vanilla-tlk"

    result = mod_manager.reset_to_vanilla("KOTOR1", game)

    assert result["override_removed"] == 3
    assert result["modules_removed"] == 1
    assert list((game / "Override").iterdir()) == []
    assert sorted(f.name for f in (game / "Modules").iterdir()) == [
        "danm13.mod", "tar_m02aa.mod"]
    # The rewritten file is the whole point: nothing else can restore it.
    assert (game / "dialog.tlk").read_bytes() == b"vanilla-tlk"


def test_reset_empties_the_library(game):
    mod_manager.capture_baseline("KOTOR1", game)
    m = mod_manager.GameManifest(game="KOTOR1")
    m.mods.append(mod_manager.InstalledMod(
        id="x", name="Some Mod", game="KOTOR1", source_type="build",
        source_ref="1", install_method="TSLPATCHER",
        deploy_kind=mod_manager.DeployKind.BAKED.value, state="baked",
        enabled=True, load_order=0))
    mod_manager.save_manifest(m)

    mod_manager.reset_to_vanilla("KOTOR1", game)
    assert mod_manager.load_manifest("KOTOR1").mods == []


def test_reset_without_a_snapshot_explains_itself(game):
    with pytest.raises(mod_manager.ModManagerError, match="no clean snapshot|No clean snapshot"):
        mod_manager.reset_to_vanilla("KOTOR1", game)


def test_capture_refuses_to_overwrite_a_snapshot(game):
    """Recapturing over a modded install would save the mods as the clean
    reference, quietly destroying the only way back."""
    mod_manager.capture_baseline("KOTOR1", game)
    _install_some_mods(game)

    second = mod_manager.capture_baseline("KOTOR1", game)
    assert second["ok"] is False
    assert second["error"] == "baseline_exists"

    mod_manager.reset_to_vanilla("KOTOR1", game)
    assert (game / "dialog.tlk").read_bytes() == b"vanilla-tlk"


def test_forced_recapture_is_allowed(game):
    mod_manager.capture_baseline("KOTOR1", game)
    (game / "Override" / "extra.tga").write_bytes(b"x")
    r = mod_manager.capture_baseline("KOTOR1", game, force=True)
    assert r["ok"] and r["override"] == 1


def test_snapshot_records_where_it_came_from(game):
    mod_manager.capture_baseline("KOTOR1", game)
    data = json.loads(
        (mod_manager.cfg.CONFIG_DIR / "baseline" / "KOTOR1" / "manifest.json")
        .read_text(encoding="utf-8"))
    assert data["game_root"] == str(game)
    assert data["captured_at"] > 0
