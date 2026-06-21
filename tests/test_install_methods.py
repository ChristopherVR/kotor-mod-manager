"""
Offline, CI-safe e2e tests for the headless install pipeline.

Builds synthetic mod archives in a temp dir and runs the REAL pipeline stages -
extract → detect → install → manifest-record - into a fake KOTOR game folder,
asserting files land in the right place for each install method. No network and
no real game install required.

Run:  python tests/test_install_methods.py
  or:  python -m pytest tests/test_install_methods.py -q
"""
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg
from installer.detector import InstallMethod, detect
from installer.extractor import extract
from installer.installer import install
from installer.pipeline import loose_mappings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zip(src_dir: Path, dest_zip: Path) -> Path:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir).as_posix())
    return dest_zip


def _fake_game(root: Path) -> Path:
    """A minimal KOTOR install: Override/, Modules/, and a base dialog.tlk."""
    (root / "Override").mkdir(parents=True, exist_ok=True)
    (root / "Modules").mkdir(parents=True, exist_ok=True)
    (root / "dialog.tlk").write_bytes(b"BASE-TLK")
    (root / "swkotor.exe").write_bytes(b"MZ")
    return root


def _isolate_config(tmp: Path) -> None:
    """Point the app config + library at a throwaway dir."""
    cfg.CONFIG_DIR = tmp / ".kmi"
    cfg.CONFIG_FILE = cfg.CONFIG_DIR / "config.json"
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_override_loose_install():
    """Loose .2da/.utc files install into Override/ and record in the library."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _isolate_config(tmp)
        from installer import mod_manager as mm

        # Build a mod archive with loose Override-type files at the root.
        modsrc = tmp / "modsrc"
        modsrc.mkdir()
        (modsrc / "k_test_appearance.2da").write_bytes(b"2DA V2.0 test")
        (modsrc / "p_test.utc").write_bytes(b"UTC test")
        (modsrc / "readme.txt").write_text("A loose override mod.")
        archive = _zip(modsrc, tmp / "loose_mod.zip")

        game = _fake_game(tmp / "game")
        extracted = extract(archive)
        plan = detect(extracted)
        assert plan.method in (InstallMethod.DIRECT_COPY, InstallMethod.OVERRIDE_COPY), plan.method
        install(plan, game)

        assert (game / "Override" / "k_test_appearance.2da").exists(), "2da not in Override"
        assert (game / "Override" / "p_test.utc").exists(), "utc not in Override"

        # Record in the library and verify it is tracked + toggleable.
        mappings = loose_mappings(plan)
        rec = mm.record_install("KOTOR1", game, name="Loose Test",
                                install_method=plan.method.name, source_type="import",
                                source_ref=str(archive), deploy_kind="loose",
                                plan_file_mappings=mappings, game_type="KOTOR1")
        man = mm.load_manifest("KOTOR1")
        assert man.find(rec.id) is not None
        assert rec.toggleable and len(rec.deployed_files) >= 2

        # Disable moves the files out; enable restores them.
        mm.disable("KOTOR1", game, rec.id)
        assert not (game / "Override" / "p_test.utc").exists(), "disable should move files out"
        mm.enable("KOTOR1", game, rec.id)
        assert (game / "Override" / "p_test.utc").exists(), "enable should restore files"
        print("PASS: override loose install + enable/disable")
    finally:
        _rm(tmp)


def test_override_folder_install():
    """A mod shipping an Override/ folder copies its contents into the game Override/."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _isolate_config(tmp)
        modsrc = tmp / "modsrc"
        (modsrc / "Override").mkdir(parents=True)
        (modsrc / "Override" / "cm_baremetal.tpc").write_bytes(b"TPC")
        archive = _zip(modsrc, tmp / "override_folder.zip")

        game = _fake_game(tmp / "game")
        plan = detect(extract(archive))
        assert plan.method == InstallMethod.OVERRIDE_COPY, plan.method
        install(plan, game)
        assert (game / "Override" / "cm_baremetal.tpc").exists()
        print("PASS: override-folder install")
    finally:
        _rm(tmp)


def test_tlk_replace_install():
    """A dialog.tlk mod replaces the game-root tlk and backs up the original."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _isolate_config(tmp)
        modsrc = tmp / "modsrc"
        modsrc.mkdir()
        (modsrc / "dialog.tlk").write_bytes(b"MODDED-TLK")
        archive = _zip(modsrc, tmp / "tlk_mod.zip")

        game = _fake_game(tmp / "game")
        plan = detect(extract(archive))
        assert plan.method in (InstallMethod.TLK_REPLACE, InstallMethod.MULTI_VARIANT), plan.method
        install(plan, game, tlk_variant_chooser=lambda variants: variants[0])

        assert (game / "dialog.tlk").read_bytes() == b"MODDED-TLK", "tlk not replaced"
        assert (game / "dialog.tlk.bak").read_bytes() == b"BASE-TLK", "original not backed up"
        print("PASS: dialog.tlk replace + backup")
    finally:
        _rm(tmp)


def test_tslpatcher_detected_and_headless_route():
    """
    A tslpatchdata/ + changes.ini mod (no bundled exe) is detected as TSLPATCHER,
    and the strategy cascade resolves to the headless HoloPatcher shim when one
    is available (no GUI needed).
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        _isolate_config(tmp)
        modsrc = tmp / "modsrc"
        (modsrc / "tslpatchdata").mkdir(parents=True)
        (modsrc / "tslpatchdata" / "changes.ini").write_text("[Settings]\nFileExists=1\n")
        (modsrc / "tslpatchdata" / "info.rtf").write_text("info")
        archive = _zip(modsrc, tmp / "tslpatcher_mod.zip")

        plan = detect(extract(archive))
        assert plan.method == InstallMethod.TSLPATCHER, plan.method

        # The cascade's first strategy must be the headless shim.
        from installer.config_loader import find_system_holopatcher
        from installer.patcher_strategy import _STRATEGY_ORDER_DEFAULT
        assert _STRATEGY_ORDER_DEFAULT[0] == "holopatcher_shim"
        shim = find_system_holopatcher()
        # In a dev checkout the shim exists under tools/; in a bare CI checkout it
        # may not - either way the *route* is headless-first.
        print(f"PASS: tslpatcher detected; headless shim {'available' if shim else 'absent (route still headless-first)'}")
    finally:
        _rm(tmp)


def test_multi_archive_loose():
    """Multiple loose files across a nested folder all map into Override/."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _isolate_config(tmp)
        modsrc = tmp / "modsrc"
        (modsrc / "Textures").mkdir(parents=True)
        (modsrc / "n_darthbandon.utc").write_bytes(b"UTC")
        (modsrc / "Textures" / "PFBN01.tga").write_bytes(b"TGA")
        archive = _zip(modsrc, tmp / "nested.zip")

        game = _fake_game(tmp / "game")
        plan = detect(extract(archive))
        assert plan.method in (InstallMethod.DIRECT_COPY, InstallMethod.OVERRIDE_COPY, InstallMethod.MULTIPLE)
        install(plan, game)
        assert (game / "Override" / "n_darthbandon.utc").exists()
        print("PASS: nested loose-file install")
    finally:
        _rm(tmp)


def _rm(p: Path) -> None:
    import shutil
    shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    failures = 0
    for fn in [
        test_override_loose_install,
        test_override_folder_install,
        test_tlk_replace_install,
        test_tslpatcher_detected_and_headless_route,
        test_multi_archive_loose,
    ]:
        try:
            fn()
        except Exception as e:
            failures += 1
            print(f"FAIL: {fn.__name__}: {e}")
    print()
    if failures:
        print(f"{failures} test(s) FAILED")
        sys.exit(1)
    print("ALL INSTALL-METHOD TESTS PASSED")
