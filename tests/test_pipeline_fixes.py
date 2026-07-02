"""
Offline regression tests for download/install pipeline fixes:

- cached-archive scanning must never mistake an extracted FOLDER for an
  archive (big NTFS directories have a non-zero st_size)
- the cache manifest makes multi-file downloads all-or-nothing on reuse and
  preserves page order
- stale percent-encoded cache filenames are migrated to decoded names
- bundled translation patches for other languages are filtered at download
  and skipped at install
- namespaces.ini files without IniName= are normalized for HoloPatcher
- a MANUAL sub-plan inside a MULTIPLE mod is skipped, not a hard failure
- self-extracting .exe archives use the full 7-Zip lookup (Program Files),
  not just PATH
- the compat-patch sweep never re-runs the patcher that just installed
  (wrapper-folder layout)
- a download that produces zero files is an error, not a silent "Installed"

Run:  python -m pytest tests/test_pipeline_fixes.py -q
"""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer.detector import InstallMethod, InstallPlan, detect
from installer.pipeline import ModStatus, Pipeline
from installer.patcher_strategy import _normalize_namespaces_ini
from scraper.build_scraper import BuildMod
from scraper.deadlystream import DeadlyStreamClient, is_other_language_file


def _mod(**kw) -> BuildMod:
    base = dict(
        install_order=1, file_id="42", slug="test-mod", name="Test Mod",
        url="https://deadlystream.com/files/file/42-test-mod/", game="KOTOR1",
        section="", category="", note="", option_hint="",
        install_method_hint="", build_key="k1_full",
    )
    base.update(kw)
    return BuildMod(**base)


def _pipeline(tmp_path: Path, mods=None, **kw) -> Pipeline:
    return Pipeline(
        mods or [],
        game_path=tmp_path / "game",
        download_dir=tmp_path / "dl",
        client=DeadlyStreamClient(),
        record_to_library=False,
        **kw,
    )


# ---------------------------------------------------------------------------
# Cache scanning
# ---------------------------------------------------------------------------

def test_cached_archives_ignores_directories(tmp_path):
    """An extracted folder next to the archive must not be treated as a
    cached archive (on NTFS a big directory can have st_size > 0)."""
    dest = tmp_path / "42_test-mod"
    dest.mkdir()
    (dest / "mod.zip").write_bytes(b"PK-data")
    (dest / "mod").mkdir()                       # previous extraction
    (dest / "mod" / "x.2da").write_bytes(b"d")
    (dest / "partial.zip.part").write_bytes(b"p")

    p = _pipeline(tmp_path)
    cached = p._cached_archives(dest)
    assert [c.name for c in cached] == ["mod.zip"]


def test_cache_manifest_requires_all_files(tmp_path):
    """With a manifest, a missing or empty file invalidates the whole cache
    so a half-finished multi-file download is re-fetched, not installed."""
    dest = tmp_path / "42_test-mod"
    dest.mkdir()
    (dest / "main.zip").write_bytes(b"PK-main")
    p = _pipeline(tmp_path)

    p._write_cache_manifest(dest, [dest / "main.zip", dest / "patch.zip"])
    assert p._cached_archives(dest) == []        # patch.zip never arrived

    (dest / "patch.zip").write_bytes(b"PK-patch")
    assert [c.name for c in p._cached_archives(dest)] == ["main.zip", "patch.zip"]


def test_cache_manifest_preserves_page_order(tmp_path):
    """Cached multi-file sets must come back in download (page) order, not
    alphabetical order - patches must overwrite the main files."""
    dest = tmp_path / "42_test-mod"
    dest.mkdir()
    for n in ("zz_main.zip", "aa_patch.zip"):
        (dest / n).write_bytes(b"PK")
    p = _pipeline(tmp_path)
    p._write_cache_manifest(dest, [dest / "zz_main.zip", dest / "aa_patch.zip"])
    assert [c.name for c in p._cached_archives(dest)] == ["zz_main.zip", "aa_patch.zip"]


def test_migrate_encoded_cache_names(tmp_path):
    """Percent-encoded leftovers from old downloads are renamed; when a
    decoded copy already exists the stale duplicate is removed."""
    dest = tmp_path / "42_test-mod"
    dest.mkdir()
    (dest / "HR%20Menu%20Patch.zip").write_bytes(b"PK-old")
    (dest / "JC%27s%20Fix.zip").write_bytes(b"PK-old2")
    (dest / "JC's Fix.zip").write_bytes(b"PK-new")   # decoded copy already there
    (dest / "plain.zip").write_bytes(b"PK")

    p = _pipeline(tmp_path)
    p._migrate_encoded_cache_names(dest)

    names = sorted(f.name for f in dest.iterdir())
    assert "HR Menu Patch.zip" in names
    assert "HR%20Menu%20Patch.zip" not in names
    assert "JC%27s%20Fix.zip" not in names
    assert (dest / "JC's Fix.zip").read_bytes() == b"PK-new"
    assert "plain.zip" in names


# ---------------------------------------------------------------------------
# Language-pack filtering
# ---------------------------------------------------------------------------

def test_other_language_detection():
    assert is_other_language_file("Patch_Deutsche_Übersetzung.zip", "en")
    assert is_other_language_file("Patch_Deutsche_%C3%9Cbersetzung.zip", "en")
    assert is_other_language_file("Manaan taxi (Español).zip", "en")
    assert is_other_language_file("Patch_Dlya_Russkogo_Perevoda.zip", "en")
    assert not is_other_language_file("Manaan taxi (English).zip", "en")
    assert not is_other_language_file("K1_Community_Patch_v1.10.0.zip", "en")
    # The player's own language is never filtered out.
    assert not is_other_language_file("Patch_Deutsche_Übersetzung.zip", "de")
    assert is_other_language_file("Patch_De_Traduction_Francais.zip", "de")


def _tiny_zip(path: Path, inner_name: str) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner_name, "2DA V2.0 data")
    return path


def test_install_skips_other_language_archives(tmp_path):
    """Stale caches can still hold translation patches; they must not be
    installed into a game of a different language."""
    game = tmp_path / "game"
    (game / "Override").mkdir(parents=True)
    dest = tmp_path / "dl" / "42_test-mod"
    dest.mkdir(parents=True)

    en = _tiny_zip(dest / "Main_Mod.zip", "english.2da")
    de = _tiny_zip(dest / "Patch_Deutsche_Übersetzung.zip", "german.2da")

    p = _pipeline(tmp_path, [_mod()], language="en")
    pm = p.mods[0]
    pm.archive_paths = [en, de]
    p._extract_and_install(pm)

    assert pm.status == ModStatus.DONE
    assert (game / "Override" / "english.2da").exists()
    assert not (game / "Override" / "german.2da").exists()


# ---------------------------------------------------------------------------
# Resolution-variant selection
# ---------------------------------------------------------------------------

def test_resolution_variant_selection():
    from scraper.deadlystream import select_resolution_records

    recs = [
        {"name": "k1rs_30fps_1920x1080.7z", "record_id": "1"},
        {"name": "k1rs_30fps_2560x1440.7z", "record_id": "2"},
        {"name": "k1rs_30fps_3840x2160.7z", "record_id": "3"},
        {"name": "readme_pack.zip", "record_id": "4"},
    ]
    picked = select_resolution_records(recs, "2560x1440")
    assert [r["record_id"] for r in picked] == ["2", "4"]

    # No exact match: nearest resolution wins.
    picked = select_resolution_records(recs, "1680x1050")
    assert picked[0]["record_id"] == "1"

    # Ties keep page order (guide-recommended option is listed first).
    fps = [
        {"name": "pack_30fps_1920x1080.7z", "record_id": "a"},
        {"name": "pack_60fps_1920x1080.7z", "record_id": "b"},
    ]
    assert select_resolution_records(fps, "1920x1080")[0]["record_id"] == "a"

    # A single resolution-tagged record is not a variant set.
    single = [{"name": "mod_1920x1080_edition.zip", "record_id": "x"},
              {"name": "patch.zip", "record_id": "y"}]
    assert select_resolution_records(single, "3840x2160") == single


# ---------------------------------------------------------------------------
# namespaces.ini normalization (HoloPatcher shim)
# ---------------------------------------------------------------------------

_NS_INI = """[Namespaces]
Namespace1=a_unmasked
Namespace2=b_masked

[a_unmasked]
DataPath=a_unmasked
Name=Option A: Unmasked
Description=Recolors [Class 9] armors.

[b_masked]
DataPath=b_masked
IniName=custom.ini
Name=Option B: Masked
"""


def test_normalize_namespaces_ini_adds_missing_ininame(tmp_path):
    td = tmp_path / "tslpatchdata"
    td.mkdir()
    (td / "namespaces.ini").write_text(_NS_INI, encoding="utf-8")

    _normalize_namespaces_ini(td)
    text = (td / "namespaces.ini").read_text(encoding="utf-8")

    a = text.split("[a_unmasked]")[1].split("[b_masked]")[0]
    assert "IniName=changes.ini" in a
    # HoloPatcher also requires InfoName (TSLPatcher defaults it to info.rtf).
    assert "InfoName=info.rtf" in a
    # Existing IniName is untouched (and not duplicated).
    b = text.split("[b_masked]")[1]
    assert "IniName=custom.ini" in b
    assert "IniName=changes.ini" not in b
    assert "InfoName=info.rtf" in b

    # Idempotent.
    _normalize_namespaces_ini(td)
    assert (td / "namespaces.ini").read_text(encoding="utf-8") == text


def test_normalize_namespaces_ini_noop_without_file(tmp_path):
    td = tmp_path / "tslpatchdata"
    td.mkdir()
    _normalize_namespaces_ini(td)          # must not raise
    assert not (td / "namespaces.ini").exists()


# ---------------------------------------------------------------------------
# Variant-family keep filtering (exact stem beats substring)
# ---------------------------------------------------------------------------

def test_keep_matches_prefers_exact_stems():
    from scraper.deadlystream import select_keep_matches

    family = ["HQSkyboxesII_K1.7z", "HQSkyboxesII_K1_1k.7z",
              "HQSkyboxesII_K1_1k_BOSSR.7z", "HQSkyboxesII_K1_Yavin4.7z"]
    assert select_keep_matches(family, ["HQSkyboxesII_K1.7z"]) == \
        ["HQSkyboxesII_K1.7z"]
    # No exact match: substring semantics still apply (never keep nothing).
    assert select_keep_matches(family, ["Yavin4"]) == ["HQSkyboxesII_K1_Yavin4.7z"]
    # Unmatchable filter returns [] so callers can fall back to everything.
    assert select_keep_matches(family, ["something-else.zip"]) == []


def test_cached_archives_respect_download_only(tmp_path):
    """Cache reuse must honour the guide's "download only X" filter - an old
    cache can hold every variant of a submission."""
    dest = tmp_path / "dl" / "723_test-mod"
    dest.mkdir(parents=True)
    for n in ("HQSkyboxesII_K1.7z", "HQSkyboxesII_K1_Yavin4.7z"):
        (dest / n).write_bytes(b"7Z")

    mod = _mod(
        file_id="723", slug="test-mod",
        instructions="Download Instructions simply download the "
                     "'HQSkyboxesII_K1.7z' file.",
    )
    p = _pipeline(tmp_path, [mod])
    pm = p.mods[0]
    p._download_mod(pm)
    assert [a.name for a in pm.archive_paths] == ["HQSkyboxesII_K1.7z"]


# ---------------------------------------------------------------------------
# Guide-driven two-step installs (main option, then add-on)
# ---------------------------------------------------------------------------

def test_holopatcher_multi_run_installs_main_first(tmp_path):
    """"Re-run the installer after installing the main option and also
    install the X option" must run the patcher twice: main then option."""
    import installer.pipeline as plmod
    from installer.detector import NamespaceOption

    root = tmp_path / "mod"
    td = root / "tslpatchdata"
    td.mkdir(parents=True)
    (root / "HoloPatcher.exe").write_bytes(b"MZ")

    plan = InstallPlan(
        method=InstallMethod.HOLOPATCHER,
        mod_root=root,
        holopatcher_exe=root / "HoloPatcher.exe",
        namespaces=[
            NamespaceOption("Main", "Main Installation", "", td / "changes.ini"),
            NamespaceOption("VisibleField", "OPTION: Add Visible Forcefield",
                            "", td / "changes.ini"),
        ],
    )

    mod = _mod(instructions=(
        "If you would like the forcefield for the hangar to be visible, "
        "re-run the installer after installing the main option and also "
        "install the visible forcefield option."))

    runs = []
    real = plmod.run_holopatcher
    plmod.run_holopatcher = \
        lambda exe, game, td_, idx, cb=None, **kw: runs.append(idx)
    try:
        p = _pipeline(tmp_path, [mod])
        p._install_one(p.mods[0], plan)
    finally:
        plmod.run_holopatcher = real

    assert runs == [0, 1], f"expected main install then option, got {runs}"


# ---------------------------------------------------------------------------
# MULTIPLE with a MANUAL sub-plan
# ---------------------------------------------------------------------------

def test_multiple_skips_manual_subfolder(tmp_path):
    """A docs/screenshots-only sub-plan must not fail the whole mod after
    the real components installed."""
    from installer.detector import ModFileMapping
    from installer.installer import install

    root = tmp_path / "mod"
    (root / "Textures").mkdir(parents=True)
    (root / "Textures" / "cool.tga").write_bytes(b"TGA")
    (root / "Screenshots").mkdir()
    (root / "Screenshots" / "preview.jpg").write_bytes(b"JPG")

    game = tmp_path / "game"
    (game / "Override").mkdir(parents=True)

    plan = InstallPlan(
        method=InstallMethod.MULTIPLE,
        mod_root=root,
        sub_plans=[
            InstallPlan(
                method=InstallMethod.DIRECT_COPY,
                mod_root=root / "Textures",
                file_mappings=[ModFileMapping(
                    source=root / "Textures" / "cool.tga",
                    dest_relative="Override/cool.tga")],
            ),
            InstallPlan(
                method=InstallMethod.MANUAL,
                mod_root=root / "Screenshots",
                readme_text="just screenshots",
            ),
        ],
    )

    install(plan, game)                     # must not raise
    assert (game / "Override" / "cool.tga").exists()


# ---------------------------------------------------------------------------
# Self-extracting exe uses the full 7z lookup
# ---------------------------------------------------------------------------

def test_sfx_exe_uses_find_7z(monkeypatch, tmp_path):
    from installer import extractor

    calls = []

    def fake_run(cmd, capture_output=True, **kw):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(extractor, "_find_7z", lambda: r"C:\Program Files\7-Zip\7z.exe")
    monkeypatch.setattr(extractor.subprocess, "run", fake_run)

    exe = tmp_path / "mod_installer.exe"
    exe.write_bytes(b"MZ fake sfx")
    extractor._extract_self_extracting_exe(exe, tmp_path / "out")

    assert calls and calls[0][0] == r"C:\Program Files\7-Zip\7z.exe"


# ---------------------------------------------------------------------------
# Compat sweep must not re-run the installer's own wrapper folder
# ---------------------------------------------------------------------------

def test_compat_sweep_skips_own_wrapper(tmp_path):
    """Archive layout ModName/tslpatchdata/: the wrapper folder is the mod
    that just installed, not a compat patch - running it again would apply
    the same 2DA/TLK changes twice."""
    root = tmp_path / "extracted"
    wrapper = root / "Cool Mod"
    td = wrapper / "tslpatchdata"
    td.mkdir(parents=True)
    (td / "changes.ini").write_text("[Settings]\n")
    (wrapper / "TSLPatcher.exe").write_bytes(b"MZ")

    compat = root / "K1CP Compatibility Patch"
    ctd = compat / "tslpatchdata"
    ctd.mkdir(parents=True)
    (ctd / "changes.ini").write_text("[Settings]\n")
    (compat / "TSLPatcher.exe").write_bytes(b"MZ")

    plan = InstallPlan(
        method=InstallMethod.TSLPATCHER,
        mod_root=root,
        tslpatcher_exe=wrapper / "TSLPatcher.exe",
        tslpatcher_ini=td / "changes.ini",
    )

    # Folders the sweep must never install: script sources and other-language
    # variants.
    src = root / "Source"
    src.mkdir()
    (src / "k_script.nss").write_text("// source")
    de = root / "Deutsch"
    de.mkdir()
    (de / "german.2da").write_bytes(b"2DA")

    p = _pipeline(tmp_path, [_mod()])
    ran = []
    p._install_sub_plan = lambda pm, sp: ran.append(sp.mod_root.name)
    p._apply_compat_patches(p.mods[0], plan)

    assert "Cool Mod" not in ran
    assert "Source" not in ran
    assert "Deutsch" not in ran
    assert "K1CP Compatibility Patch" in ran


# ---------------------------------------------------------------------------
# Zero downloaded files is an error, not a silent success
# ---------------------------------------------------------------------------

def test_empty_download_is_error(tmp_path):
    class NullClient:
        def download_all_files(self, **kw):
            return []

    p = Pipeline(
        [_mod()],
        game_path=tmp_path / "game",
        download_dir=tmp_path / "dl",
        client=NullClient(),
        record_to_library=False,
    )
    p._download_mod(p.mods[0])
    assert p.mods[0].status == ModStatus.ERROR
    assert "downloaded" in p.mods[0].error.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
