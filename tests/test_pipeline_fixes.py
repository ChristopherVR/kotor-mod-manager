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


# ---------------------------------------------------------------------------
# Mods hosted off DeadlyStream are not sent to DeadlyStream
# ---------------------------------------------------------------------------

def test_unsupported_host_asks_for_the_file_then_errors_clearly(tmp_path, monkeypatch):
    import installer.pipeline as pl
    monkeypatch.setattr(pl, "_DROP_WAIT_SECONDS", 0.4)
    monkeypatch.setattr(pl, "_DROP_POLL_SECONDS", 0.05)
    mod = _mod()
    mod.source_host = "unknown"
    mod.url = "https://example.com/some-page"
    p = _pipeline(tmp_path, [mod])
    called = []
    p._client.download_all_files = lambda **kw: called.append(kw)
    p._download_mod(p.mods[0])
    assert not called
    assert p.mods[0].status.name == "ERROR"
    assert "example.com" in p.mods[0].error and str(tmp_path / "dl") in p.mods[0].error


def _nexus_mod():
    mod = _mod()
    mod.source_host = "nexus"
    mod.url = "https://www.nexusmods.com/kotor/mods/1234"
    return mod


def test_nexus_mod_downloads_through_nexus_not_deadlystream(tmp_path, monkeypatch):
    from scraper import nexus
    p = _pipeline(tmp_path, [_nexus_mod()])
    monkeypatch.setattr(nexus, "load_api_key", lambda fallback="": "KEY")
    monkeypatch.setattr(nexus, "list_files", lambda g, m, k: [
        {"file_id": 7, "file_name": "old.zip", "category_name": "OLD_VERSION",
         "uploaded_timestamp": 9},
        {"file_id": 8, "file_name": "main.zip", "category_name": "MAIN",
         "is_primary": True, "uploaded_timestamp": 5}])
    got = []

    def fake_download(game, mod_id, file_id, dest, key, **kw):
        got.append((game, mod_id, file_id, key))
        f = dest / "main.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return f

    monkeypatch.setattr(nexus, "download_file", fake_download)
    p._client.download_all_files = lambda **kw: (_ for _ in ()).throw(AssertionError("DeadlyStream used"))
    p._download_mod(p.mods[0])
    assert got == [(p.mods[0].build_mod.game, 1234, 8, "KEY")]
    assert [a.name for a in p.mods[0].archive_paths] == ["main.zip"]


def test_nexus_mod_without_api_key_says_what_to_do(tmp_path, monkeypatch):
    from scraper import nexus
    import config as cfg
    p = _pipeline(tmp_path, [_nexus_mod()])
    monkeypatch.setattr(nexus, "load_api_key", lambda fallback="": "")
    monkeypatch.setattr(cfg, "load", lambda: {})
    p._download_mod(p.mods[0])
    assert p.mods[0].status.name == "ERROR"
    assert "API key" in p.mods[0].error


def test_nexus_free_account_error_is_passed_on(tmp_path, monkeypatch):
    from scraper import nexus
    p = _pipeline(tmp_path, [_nexus_mod()])
    monkeypatch.setattr(nexus, "load_api_key", lambda fallback="": "KEY")
    monkeypatch.setattr(nexus, "list_files", lambda g, m, k: [
        {"file_id": 8, "file_name": "main.zip", "category_name": "MAIN", "is_primary": True}])

    def refuse(*a, **kw):
        raise nexus.NexusAuthError("Free accounts cannot download this way.")

    monkeypatch.setattr(nexus, "download_file", refuse)
    p._download_mod(p.mods[0])
    assert p.mods[0].status.name == "ERROR"
    assert "Free accounts" in p.mods[0].error


def test_nexus_pick_files_follows_build_guide_filters():
    from scraper import nexus
    files = [
        {"file_id": 1, "file_name": "Mod Main 1.0.zip", "category_name": "MAIN", "uploaded_timestamp": 1},
        {"file_id": 2, "file_name": "Mod Main 1.1.zip", "category_name": "MAIN", "uploaded_timestamp": 2},
        {"file_id": 3, "file_name": "Extra HD.zip", "category_name": "OPTIONAL", "uploaded_timestamp": 3},
        {"file_id": 4, "file_name": "gone.zip", "category_name": "ARCHIVED", "uploaded_timestamp": 4},
    ]
    assert [f["file_id"] for f in nexus.pick_files(files)] == [2]
    assert [f["file_id"] for f in nexus.pick_files(files, keep_names=["Extra HD"])] == [3]


# ---------------------------------------------------------------------------
# Downloads: one limit per site, installs still in build order
# ---------------------------------------------------------------------------

def _run_scheduler(tmp_path, hosts, hold=0.15):
    """Run the pipeline loop with fake downloads; return (max running per host,
    max running overall, install order)."""
    import threading
    import time
    mods = []
    for i, host in enumerate(hosts):
        m = _mod()
        m.file_id = f"f{i}"
        m.source_host = host
        mods.append(m)
    p = _pipeline(tmp_path, mods)
    lock = threading.Lock()
    running, peak, total_peak, installed = {}, {}, [0], []

    def fake_download(pm):
        host = pm.build_mod.source_host
        with lock:
            running[host] = running.get(host, 0) + 1
            peak[host] = max(peak.get(host, 0), running[host])
            total_peak[0] = max(total_peak[0], sum(running.values()))
        time.sleep(hold)
        with lock:
            running[host] -= 1

    p._download_mod = fake_download
    p._extract_and_install = lambda pm: installed.append(pm.build_mod.file_id)
    p._capture_baseline_once = lambda: None
    p._apply_layer_order = lambda: None
    p._resolve_skip_constraints = lambda: None
    p._check_dependencies = lambda: None
    p._log_overlap_summary = lambda: None
    p._run()
    return peak, total_peak[0], installed


def test_each_site_has_its_own_download_limit(tmp_path):
    hosts = ["nexus", "nexus", "nexus", "deadlystream", "deadlystream", "mega", "mega"]
    peak, _total, _order = _run_scheduler(tmp_path, hosts)
    assert peak["nexus"] == 1
    assert peak["mega"] == 1
    assert 1 < peak["deadlystream"] <= 3


def test_other_sites_download_while_nexus_waits(tmp_path):
    """Two Nexus mods first in line must not hold up the DeadlyStream ones."""
    hosts = ["nexus", "nexus", "deadlystream", "deadlystream", "mega"]
    _peak, total_peak, _order = _run_scheduler(tmp_path, hosts)
    assert total_peak >= 3  # one per site at the same time


def test_installs_stay_in_build_order_whatever_finishes_first(tmp_path):
    hosts = ["nexus", "deadlystream", "mega", "nexus", "deadlystream", "github"]
    _peak, _total, order = _run_scheduler(tmp_path, hosts)
    assert order == [f"f{i}" for i in range(len(hosts))]


def test_a_stopped_run_does_not_hang(tmp_path):
    import threading
    m = _mod()
    m.source_host = "nexus"
    p = _pipeline(tmp_path, [m])
    started = threading.Event()

    def blocked(pm):
        started.set()
        p._stop_event.wait(5)

    p._download_mod = blocked
    p._capture_baseline_once = lambda: None
    p._apply_layer_order = lambda: None
    p._resolve_skip_constraints = lambda: None
    p._check_dependencies = lambda: None
    p._log_overlap_summary = lambda: None
    t = threading.Thread(target=p._run)
    t.start()
    assert started.wait(3)
    p._stop_event.set()
    t.join(5)
    assert not t.is_alive()


def test_finished_download_reads_ready_not_downloading(tmp_path, monkeypatch):
    from scraper import nexus
    seen = []
    p = _pipeline(tmp_path, [_nexus_mod()],
                  on_status=lambda fid, st, detail: seen.append((st.name, detail)))
    monkeypatch.setattr(nexus, "load_api_key", lambda fallback="": "KEY")
    monkeypatch.setattr(nexus, "list_files", lambda g, m, k: [
        {"file_id": 8, "file_name": "main.zip", "category_name": "MAIN", "is_primary": True}])

    def fake_download(game, mod_id, file_id, dest, key, **kw):
        f = dest / "main.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return f

    monkeypatch.setattr(nexus, "download_file", fake_download)
    p._download_mod(p.mods[0])
    assert p.mods[0].status.name == "READY"
    assert seen[-1][0] == "READY"


def test_waiting_for_the_nexus_click_is_shown_on_the_badge(tmp_path, monkeypatch):
    from scraper import nexus
    seen = []
    p = _pipeline(tmp_path, [_nexus_mod()],
                  on_status=lambda fid, st, detail: seen.append((st.name, detail)))
    monkeypatch.setattr(nexus.NXM, "wait", lambda *a, **k: None)
    p._await_nxm_click(p.mods[0], p.mods[0].build_mod, 1, 2)
    assert seen[0] == ("DOWNLOADING", "Waiting for your click on Nexus")


def test_a_slow_early_mod_does_not_hold_up_later_downloads(tmp_path):
    """A Nexus mod first in line (waiting for a click) must not stop the
    DeadlyStream mods behind it from downloading, however many there are."""
    import threading
    import time
    hosts = ["nexus"] + ["deadlystream"] * 14
    mods = []
    for i, host in enumerate(hosts):
        m = _mod()
        m.file_id, m.source_host = f"f{i}", host
        mods.append(m)
    p = _pipeline(tmp_path, mods)
    release = threading.Event()
    done_ds = []

    def fake_download(pm):
        if pm.build_mod.source_host == "nexus":
            release.wait(10)                 # stuck waiting for its click
        else:
            time.sleep(0.05)
            done_ds.append(pm.build_mod.file_id)

    p._download_mod = fake_download
    p._extract_and_install = lambda pm: None
    p._capture_baseline_once = lambda: None
    p._apply_layer_order = lambda: None
    p._resolve_skip_constraints = lambda: None
    p._check_dependencies = lambda: None
    p._log_overlap_summary = lambda: None
    t = threading.Thread(target=p._run)
    t.start()
    deadline = time.time() + 8
    while len(done_ds) < 14 and time.time() < deadline:
        time.sleep(0.05)
    finished_while_blocked = len(done_ds)
    release.set()
    t.join(10)
    assert finished_while_blocked == 14      # all of them, with the Nexus mod still stuck
    assert not t.is_alive()


# ---------------------------------------------------------------------------
# DeadlyStream refusals: the whole mod is retried before it counts as failed
# ---------------------------------------------------------------------------

def _refused(code=403):
    import requests
    r = requests.Response()
    r.status_code = code
    return requests.HTTPError(f"{code} Client Error: Forbidden", response=r)


def test_a_mod_that_deadlystream_refuses_twice_is_retried_and_succeeds(tmp_path, monkeypatch):
    import installer.pipeline as pl
    monkeypatch.setattr(pl, "_MOD_RETRY_WAITS", (0.05, 0.05))
    p = _pipeline(tmp_path, [_mod()])
    calls = []

    def flaky(**kw):
        calls.append(1)
        if len(calls) < 3:
            raise _refused()
        f = kw["dest_dir"] / "m.zip"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK")
        return [f]

    p._client.download_all_files = flaky
    p._download_mod(p.mods[0])
    assert len(calls) == 3
    assert p.mods[0].status.name == "READY"


def test_a_mod_that_keeps_being_refused_fails_after_the_retries(tmp_path, monkeypatch):
    import installer.pipeline as pl
    monkeypatch.setattr(pl, "_MOD_RETRY_WAITS", (0.05, 0.05))
    p = _pipeline(tmp_path, [_mod()])
    calls = []

    def refused(**kw):
        calls.append(1)
        raise _refused()

    p._client.download_all_files = refused
    p._download_mod(p.mods[0])
    assert len(calls) == 3
    assert p.mods[0].status.name == "ERROR" and "403" in p.mods[0].error


def test_other_errors_are_not_retried(tmp_path, monkeypatch):
    import installer.pipeline as pl
    monkeypatch.setattr(pl, "_MOD_RETRY_WAITS", (0.05, 0.05))
    p = _pipeline(tmp_path, [_mod()])
    calls = []

    def missing(**kw):
        calls.append(1)
        raise _refused(404)

    p._client.download_all_files = missing
    p._download_mod(p.mods[0])
    assert len(calls) == 1
    assert p.mods[0].status.name == "ERROR"


def test_downloads_keep_starting_while_a_long_install_runs(tmp_path):
    """The thread that installs mods can be busy for minutes (a patcher, a large
    extraction). New downloads must not wait for it to come back."""
    import threading
    import time
    mods = []
    for i in range(12):
        m = _mod()
        m.file_id = f"f{i}"
        mods.append(m)
    p = _pipeline(tmp_path, mods)
    downloaded = []
    installing = threading.Event()
    release = threading.Event()

    def fake_download(pm):
        time.sleep(0.05)
        downloaded.append(pm.build_mod.file_id)

    def slow_install(pm):
        installing.set()
        release.wait(10)                      # a patcher that runs for a long time

    p._download_mod = fake_download
    p._extract_and_install = slow_install
    p._capture_baseline_once = lambda: None
    p._apply_layer_order = lambda: None
    p._resolve_skip_constraints = lambda: None
    p._check_dependencies = lambda: None
    p._log_overlap_summary = lambda: None
    t = threading.Thread(target=p._run)
    t.start()
    assert installing.wait(5)
    deadline = time.time() + 8
    while len(downloaded) < 12 and time.time() < deadline:
        time.sleep(0.05)
    still_installing = not release.is_set()
    release.set()
    t.join(15)
    assert still_installing and len(downloaded) == 12   # all fetched during one install
    assert not t.is_alive()
