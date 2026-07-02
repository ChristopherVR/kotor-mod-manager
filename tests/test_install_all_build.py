r"""
Full-build install test: runs the REAL pipeline over every mod of a build
guide against a disposable copy of the game, using locally cached archives.
Verifies that every mod either installs cleanly or is correctly classified
as a manual install - no errors.

This needs a real (copied!) game folder and a populated download cache, so
it is opt-in, like the live test:

  set KMI_INSTALL_ALL=1
  set KMI_GAME_DIR=D:\kmi_test\game_run1        (a THROWAWAY copy - it gets modded)
  set KMI_DOWNLOAD_CACHE=D:\kmi_test\downloads  (defaults to the app's download dir)
  set KMI_BUILD_KEY=k1_full                     (optional)
  set KMI_BUILD_JSON=path\to\snapshot.json      (optional: offline scrape snapshot)
  set KMI_FAKE_GAME=1                           (optional: no real game needed - uses
                                                 a minimal fake game tree and DRY-RUNS
                                                 the patchers; loose-file mods still
                                                 copy for real. Verifies the whole
                                                 pipeline except binary patching.)
  set KMI_ALLOW_ERRORS=2097,...                 (optional: file_ids allowed to fail,
                                                 e.g. mods needing game folders your
                                                 copy of the game does not have)
  set KMI_EXCLUDE=2380,...                      (optional: file_ids to skip entirely,
                                                 e.g. multi-gigabyte movie packs)
  python -m pytest tests/test_install_all_build.py -q -s

Mods whose archives are not cached are reported and skipped (downloading the
whole build needs a signed-in DeadlyStream session; use the app for that).
The patcher cascade is restricted to the headless HoloPatcher shim so the
test never opens GUI windows, and standalone game-binary patchers
(GAME_PATCHER) are not launched - they count as manual installs.
"""
import copy as _copy
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = pytest.mark.skipif(
    not os.environ.get("KMI_INSTALL_ALL"),
    reason="opt-in: set KMI_INSTALL_ALL=1 (plus KMI_GAME_DIR) to run",
)


def _env_path(name: str, default: str = "") -> Path:
    return Path(os.environ.get(name) or default)


def _fake_game(root: Path) -> Path:
    """A minimal tree that passes KOTOR-install validation."""
    for d in ("Override", "modules", "streamwaves", "streammusic",
              "movies", "lips"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "dialog.tlk").write_bytes(b"BASE-TLK")
    (root / "chitin.key").write_bytes(b"KEY V1  ")
    (root / "swkotor.exe").write_bytes(b"MZ")
    return root


def test_install_entire_build():
    import config as cfg
    import installer.config_loader as cl
    from installer.pipeline import ModStatus, Pipeline
    from scraper.build_scraper import BuildMod, scrape_build
    from scraper.deadlystream import DeadlyStreamClient

    build_key = os.environ.get("KMI_BUILD_KEY", "k1_full")
    fake = bool(os.environ.get("KMI_FAKE_GAME"))
    if fake:
        import tempfile
        game_dir = _fake_game(Path(tempfile.mkdtemp(prefix="kmi_fake_game_")))
    else:
        game_dir = _env_path("KMI_GAME_DIR")
        assert game_dir.is_dir(), \
            "KMI_GAME_DIR must point at a disposable game copy (or set KMI_FAKE_GAME=1)"
    dl_dir = _env_path("KMI_DOWNLOAD_CACHE", cfg.download_dir())
    assert dl_dir.is_dir(), "KMI_DOWNLOAD_CACHE must point at the archive cache"

    # ---- Mod list: live scrape, or an offline snapshot for reproducibility ----
    snapshot = os.environ.get("KMI_BUILD_JSON")
    if snapshot:
        data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        mods = [BuildMod(**m) for m in data[build_key]]
    else:
        mods = scrape_build(build_key)
    assert mods, f"no mods scraped for {build_key}"

    exclude = {x.strip() for x in os.environ.get("KMI_EXCLUDE", "").split(",")
               if x.strip()}
    if exclude:
        mods = [m for m in mods if m.file_id not in exclude]

    # ---- Only mods with cached archives; the rest are reported, not failed ----
    cached_mods, uncached = [], []
    for m in mods:
        d = dl_dir / f"{m.file_id}_{m.slug[:30]}"
        if d.is_dir() and any(f.is_file() and not f.name.endswith(".part")
                              for f in d.iterdir()):
            cached_mods.append(m)
        else:
            uncached.append(m)
    if uncached:
        print(f"\n[install-all] {len(uncached)} mod(s) not cached, skipped: "
              + ", ".join(f"{m.file_id}({m.name[:30]})" for m in uncached[:10])
              + ("..." if len(uncached) > 10 else ""))
    assert cached_mods, "no cached archives found - run the app's downloads first"

    # ---- Headless-only cascade: never pop TSLPatcher GUI windows in a test ----
    base_cfg = _copy.deepcopy(cl.load_config())
    base_cfg["installer_types"]["tslpatcher"]["execution"]["strategies"] = \
        ["holopatcher_shim"]
    cl.load_config.cache_clear()
    original_load = cl.load_config
    cl.load_config = lambda: base_cfg

    # ---- Never launch standalone game-patcher GUIs from a test run ----
    real_popen = subprocess.Popen

    class _Dummy:
        pid, returncode = -1, 0
        def poll(self): return 0
        def wait(self, timeout=None): return 0
        def kill(self): pass
        def terminate(self): pass

    def safe_popen(args, *a, **kw):
        exe = str(args[0]) if isinstance(args, (list, tuple)) else str(args)
        bare = not isinstance(args, (list, tuple)) or len(args) == 1
        try:
            if bare and Path(exe).resolve().is_relative_to(dl_dir.resolve()):
                return _Dummy()
        except (OSError, ValueError):
            pass
        return real_popen(args, *a, **kw)

    subprocess.Popen = safe_popen

    # ---- Fake-game mode: dry-run the patchers. Everything up to the actual
    # binary patching still runs for real: cache reuse/migration, extraction,
    # detection, directive handling, tslpatchdata lookup, namespaces.ini
    # normalization and namespace resolution.
    import installer.pipeline as plmod
    real_cascade = plmod.run_tslpatcher_cascade
    real_holo = plmod.run_holopatcher
    dry_runs: list[str] = []
    if fake:
        from installer.patcher_strategy import (_find_tslpatchdata,
                                                _normalize_namespaces_ini,
                                                resolve_namespace_index)

        class _DryResult:
            strategy = "dry_run"

        def _dry_cascade(mod_root=None, exe=None, game_dir=None,
                         option_hint="", directives=None, cb=None,
                         on_waiting=None, allow_manual=True, **kw):
            td = _find_tslpatchdata(mod_root, exe)
            if td is None:
                raise AssertionError(f"no tslpatchdata under {mod_root}")
            _normalize_namespaces_ini(td, cb)
            resolve_namespace_index(td, option_hint, cb, directives)
            dry_runs.append(str(td))
            return _DryResult()

        def _dry_holo(exe, game_dir_, tslpatchdata, ns_index=0, cb=None, **kw):
            dry_runs.append(str(tslpatchdata))

        plmod.run_tslpatcher_cascade = _dry_cascade
        plmod.run_holopatcher = _dry_holo

    logs: list[str] = []
    try:
        pipe = Pipeline(
            cached_mods,
            game_path=game_dir,
            download_dir=dl_dir,
            client=DeadlyStreamClient(),
            on_log=lambda m, t="": logs.append(f"[{t or 'info'}] {m}"),
            auto_unattended=True,
            record_to_library=False,
        )
        t0 = time.time()
        pipe.start()
        while pipe.is_running:
            time.sleep(2)
    finally:
        subprocess.Popen = real_popen
        cl.load_config = original_load
        plmod.run_tslpatcher_cascade = real_cascade
        plmod.run_holopatcher = real_holo

    # ---- Assess ----
    allow = {x.strip() for x in os.environ.get("KMI_ALLOW_ERRORS", "").split(",")
             if x.strip()}
    done = [pm for pm in pipe.mods if pm.status == ModStatus.DONE]
    manual = [pm for pm in pipe.mods if pm.status == ModStatus.MANUAL]
    errors = [pm for pm in pipe.mods
              if pm.status == ModStatus.ERROR
              and pm.build_mod.file_id not in allow]
    allowed_errors = [pm for pm in pipe.mods
                      if pm.status == ModStatus.ERROR
                      and pm.build_mod.file_id in allow]

    mode = " (fake game, patchers dry-run)" if fake else ""
    print(f"\n[install-all]{mode} {build_key}: {len(done)} installed, "
          f"{len(manual)} manual, {len(errors)} errors, "
          f"{len(allowed_errors)} allowed errors "
          f"in {time.time() - t0:.0f}s"
          + (f", {len(dry_runs)} patcher dry-runs" if fake else ""))
    for pm in manual:
        print(f"  MANUAL [{pm.build_mod.install_order:3d}] {pm.build_mod.name}")

    # Stale percent-encoded cache names must have been migrated on reuse.
    encoded = [f.name for pm in pipe.mods for f in pm.archive_paths
               if "%" in f.name]
    assert not encoded, f"cache still holds percent-encoded names: {encoded[:5]}"

    assert not errors, "mods failed to install:\n" + "\n".join(
        f"  [{pm.build_mod.install_order:3d}] {pm.build_mod.name} "
        f"({pm.build_mod.file_id}): {pm.error[:300]}"
        for pm in errors
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-s"]))
