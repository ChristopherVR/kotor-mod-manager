"""
Mod installation pipeline: parallel downloads, sequential installs.
For each mod in build order: download (up to 3 at once) → extract → detect → install.

- Up to 3 mods download concurrently; extraction and install stay sequential so
  patchers never clobber each other.
- Multi-file submissions are downloaded and installed in order.
- TSLPatcher mods go through the strategy cascade (headless HoloPatcher shim →
  Win32 automation → pywinauto → manual GUI) so almost nothing needs a click.
- Install-phase progress is reported so the UI can show live status.
"""
import copy
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from installer.build_directives import match_option_index
from installer.detector import InstallMethod, InstallPlan, ModFileMapping, detect
from installer.extractor import ExtractionError, extract
from installer.installer import InstallError, install
from installer.patcher_strategy import run_tslpatcher_cascade
from installer.runner import PatcherError, run_holopatcher
from scraper.build_scraper import BuildMod
from scraper.deadlystream import DeadlyStreamClient, DownloadError


class ModStatus(Enum):
    PENDING          = "Pending"
    DOWNLOADING      = "Downloading"
    EXTRACTING       = "Extracting"
    READY            = "Ready"
    INSTALLING       = "Installing"
    WAITING_PATCHER  = "Waiting for patcher..."
    DONE             = "Done"
    SKIPPED          = "Skipped"
    MANUAL           = "Manual install needed"
    ERROR            = "Error"


class ManualInstallRequired(Exception):
    """
    Raised when a mod can only be installed by hand (no recognised auto-install
    method). Not a failure - it carries the extracted folder and any readme so
    the UI can guide the player through finishing it.
    """
    def __init__(self, mod_root: Path, readme: str = ""):
        self.mod_root = mod_root
        self.readme = readme
        super().__init__(f"Manual install required: {mod_root}")


@dataclass
class PipelineMod:
    build_mod: BuildMod
    status: ModStatus = ModStatus.PENDING
    archive_paths: list[Path] = field(default_factory=list)
    extracted_paths: list[Path] = field(default_factory=list)
    plans: list[InstallPlan] = field(default_factory=list)
    error: str = ""
    download_progress: float = 0.0   # 0.0–1.0
    download_kb: int = 0
    download_total_kb: int = 0
    strategy_used: str = ""

    # Back-compat single-value accessors
    @property
    def archive_path(self) -> Optional[Path]:
        return self.archive_paths[0] if self.archive_paths else None

    @property
    def extracted_path(self) -> Optional[Path]:
        return self.extracted_paths[0] if self.extracted_paths else None

    @property
    def plan(self) -> Optional[InstallPlan]:
        return self.plans[0] if self.plans else None


# Callbacks
StatusCallback   = Callable[[str, ModStatus, str], None]  # (file_id, status, detail)
LogCallback      = Callable[[str, str], None]              # (message, tag)
ProgressCB       = Callable[[str, float, int, int], None]  # (file_id, pct, kb, total_kb)
InstallProgressCB = Callable[[str, float, str], None]      # (file_id, pct, label)
ManualCB         = Callable[[str, str, str, str], None]     # (file_id, name, folder, readme)


class Pipeline:
    def __init__(
        self,
        mods: list[BuildMod],
        game_path: Path,
        download_dir: Path,
        client: DeadlyStreamClient,
        on_status: Optional[StatusCallback] = None,
        on_log: Optional[LogCallback] = None,
        on_progress: Optional[ProgressCB] = None,
        on_install_progress: Optional[InstallProgressCB] = None,
        on_manual: Optional[ManualCB] = None,
        auto_unattended: bool = False,
        game_key: str = "",
        game_type: str = "",
        record_to_library: bool = True,
    ):
        self._mods = [PipelineMod(m) for m in mods]
        self._game_path = game_path
        self._download_dir = download_dir
        self._client = client
        self._on_status = on_status
        self._on_log = on_log
        self._on_progress = on_progress
        self._on_install_progress = on_install_progress
        self._on_manual = on_manual
        # When True, never fall back to a manual GUI click (fully unattended).
        self._auto_unattended = auto_unattended
        # Mod-manager recording. game_key is the manifest scope (profile id or
        # game); game_type is the actual game ("KOTOR1"/"KOTOR2"). Empty key
        # disables recording.
        self._game_key = game_key
        self._game_type = game_type or game_key
        self._record_to_library = record_to_library and bool(game_key)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._current: Optional[PipelineMod] = None

    @property
    def mods(self) -> list[PipelineMod]:
        return self._mods

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def retry_failed(self) -> None:
        """Reset errored mods to pending so a fresh start() re-attempts them."""
        for pm in self._mods:
            if pm.status == ModStatus.ERROR:
                pm.status = ModStatus.PENDING
                pm.error = ""

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------

    def _set_status(self, mod: PipelineMod, status: ModStatus, detail: str = "") -> None:
        mod.status = status
        if self._on_status:
            self._on_status(mod.build_mod.file_id, status, detail)

    def _log(self, msg: str, tag: str = "") -> None:
        if self._on_log:
            self._on_log(msg, tag)

    def _install_progress(self, mod: PipelineMod, pct: float, label: str) -> None:
        if self._on_install_progress:
            self._on_install_progress(mod.build_mod.file_id, pct, label)

    def _run(self) -> None:
        pending = [pm for pm in self._mods if pm.status not in (ModStatus.DONE, ModStatus.SKIPPED)]
        self._resolve_skip_constraints()
        self._check_dependencies()
        try:
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="mod-dl") as pool:
                futures: dict = {}  # Future -> PipelineMod
                queue = list(pending)

                def fill_pool() -> None:
                    while queue and len(futures) < 3 and not self._stop_event.is_set():
                        pm = queue.pop(0)
                        futures[pool.submit(self._download_mod, pm)] = pm

                fill_pool()

                for pm in pending:
                    if self._stop_event.is_set():
                        break

                    # Wait for this mod's download future (already in-flight or
                    # about to be submitted). _download_mod never raises; errors
                    # are stored on pm.status / pm.error instead.
                    f = next((k for k, v in futures.items() if v is pm), None)
                    if f is not None:
                        try:
                            f.result()
                        except Exception as e:
                            self._log(f"  Unexpected pipeline error: {e}", "error")
                            pm.status = ModStatus.ERROR
                            pm.error = str(e)
                        del futures[f]
                        fill_pool()

                    if self._stop_event.is_set() or pm.status == ModStatus.ERROR:
                        continue

                    self._pause_event.wait()
                    self._current = pm
                    self._extract_and_install(pm)
        except Exception as e:
            self._log(f"Pipeline crashed unexpectedly: {e}", "error")
        finally:
            self._running = False
            self._current = None

    def _download_mod(self, pm: PipelineMod) -> None:
        """Download all files for a mod. Called concurrently; never raises."""
        if self._stop_event.is_set():
            return

        mod = pm.build_mod
        self._log(f"\n── [{mod.install_order:3d}] {mod.name}")

        try:
            dest_dir = self._download_dir / f"{mod.file_id}_{mod.slug[:30]}"

            # If complete archives are already on disk, skip re-downloading.
            # This makes pressing Install again (or Retry) resumable without
            # restarting every download from zero.
            if dest_dir.exists():
                cached = sorted(
                    [f for f in dest_dir.iterdir()
                     if not f.name.endswith(".part") and f.stat().st_size > 0],
                    key=lambda f: f.name,
                )
                if cached:
                    pm.archive_paths = cached
                    total_kb = sum(f.stat().st_size for f in cached) // 1024
                    for a in cached:
                        self._log(f"  Cached: {a.name} ({a.stat().st_size // 1024} KB)")
                    if self._on_progress:
                        self._on_progress(mod.file_id, 1.0, total_kb, total_kb)
                    return

            self._set_status(pm, ModStatus.DOWNLOADING)
            dest_dir.mkdir(parents=True, exist_ok=True)

            def dl_progress(downloaded: int, total: int, filename: str) -> None:
                kb = downloaded // 1024
                total_kb = total // 1024 if total else 0
                pct = downloaded / total if total else 0
                pm.download_kb = kb
                pm.download_total_kb = total_kb
                pm.download_progress = pct
                if self._on_progress:
                    self._on_progress(mod.file_id, pct, kb, total_kb)

            keep_names = mod.directives.download_only
            ignore_names = mod.directives.download_ignore
            if keep_names:
                self._log(
                    f"  Build guide: downloading only {', '.join(keep_names)} "
                    f"(ignoring the other files in this submission).")
            if ignore_names:
                self._log(
                    f"  Build guide: skipping download of {', '.join(ignore_names)}.")
            archives = self._client.download_all_files(
                file_id=mod.file_id,
                slug=mod.slug,
                dest_dir=dest_dir,
                progress_callback=dl_progress,
                cancel_event=self._stop_event,
                pause_event=self._pause_event,
                keep_names=keep_names,
                ignore_names=ignore_names,
            )
            pm.archive_paths = archives
            if len(archives) > 1:
                self._log(f"  Downloaded {len(archives)} files.")
            for a in archives:
                self._log(f"  Downloaded: {a.name} ({a.stat().st_size // 1024} KB)")

        except DownloadError as e:
            self._set_status(pm, ModStatus.ERROR, str(e))
            self._log(f"  Download failed: {e}", "error")
            pm.error = str(e)
        except Exception as e:
            self._set_status(pm, ModStatus.ERROR, str(e))
            self._log(f"  Unexpected download error: {e}", "error")
            pm.error = str(e)

    def _extract_and_install(self, pm: PipelineMod) -> None:
        """Extract downloaded archives then detect and install the mod. Called sequentially."""
        if self._stop_event.is_set():
            return

        # ---- Extract archives; treat loose mod files (e.g. .tga) as direct copies ----
        _ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".exe"}
        try:
            self._set_status(pm, ModStatus.EXTRACTING)
            loose_files: list[Path] = []
            for archive in pm.archive_paths:
                if archive.suffix.lower() in _ARCHIVE_SUFFIXES:
                    extracted = extract(archive)
                    pm.extracted_paths.append(extracted)
                    self._log(f"  Extracted: {extracted.name}")
                else:
                    # Loose mod file distributed without an archive wrapper (e.g. a
                    # .tga texture). Queue it for direct copy rather than extraction.
                    loose_files.append(archive)

            if loose_files:
                loose_dir = pm.archive_paths[0].parent / "_loose"
                loose_dir.mkdir(exist_ok=True)
                for f in loose_files:
                    shutil.copy2(f, loose_dir / f.name)
                pm.extracted_paths.append(loose_dir)
                self._log(f"  Loose files: {', '.join(f.name for f in loose_files)}")
        except ExtractionError as e:
            self._set_status(pm, ModStatus.ERROR, str(e))
            self._log(f"  Extraction failed: {e}", "error")
            pm.error = str(e)
            return
        except Exception as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:1500])
            self._log(f"  Extraction failed: {e}", "error")
            pm.error = str(e)
            return

        if self._stop_event.is_set():
            return

        # ---- Detect + install each extracted payload ----
        for ep in pm.extracted_paths:
            plan = detect(ep)
            pm.plans.append(plan)

        # Honour build-guide nuance: re-order so a "run the patch first" mod
        # applies its patcher before its loose files, and surface the steps we
        # can't safely automate (multi-run, required external patches).
        dirs = pm.build_mod.directives
        self._apply_build_guide_order(pm, dirs)
        self._log_build_guide_notes(pm, dirs)
        self._apply_pre_delete(pm, dirs)

        self._set_status(pm, ModStatus.INSTALLING)
        total = len(pm.plans)
        any_succeeded = False
        manual: Optional[ManualInstallRequired] = None
        try:
            for i, plan in enumerate(pm.plans, 1):
                if total > 1:
                    self._log(f"  Component {i}/{total}: {plan.method.name}", "muted")
                else:
                    self._log(f"  Method: {plan.method.name}", "muted")
                self._install_progress(pm, (i - 1) / total, f"{plan.method.name} ({i}/{total})")
                pre = self._pre_install_snapshot(plan)
                try:
                    self._install_one(pm, plan)
                    any_succeeded = True
                except ManualInstallRequired as m:
                    if any_succeeded:
                        # Core mod already installed. This is a supplementary component
                        # (e.g. an optional language pack) - log a note but don't block.
                        name = plan.mod_root.name if plan.mod_root else f"component {i}"
                        self._log(
                            f"  Optional component '{name}' needs a manual step "
                            f"- skip it if it is a language pack or variant you do not need.",
                            "muted",
                        )
                    else:
                        manual = m
                    continue
                self._apply_post_delete(dirs)
                self._record_install(pm, plan, pre)
                self._install_progress(pm, i / total, "Done")

            if manual is not None:
                self._flag_manual(pm, manual)
            else:
                self._set_status(pm, ModStatus.DONE)
                note = f" via {pm.strategy_used}" if pm.strategy_used else ""
                self._log(f"  Installed.{note}", "success")
        except InstallError as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:1500])
            self._log(f"  Install error: {e}", "error")
            pm.error = str(e)
        except PatcherError as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:1500])
            self._log(f"  Patcher error: {e}", "error")
            pm.error = str(e)
        except Exception as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:1500])
            self._log(f"  Unexpected install error: {e}", "error")
            pm.error = str(e)

    def _flag_manual(self, pm: PipelineMod, manual: ManualInstallRequired) -> None:
        """Mark a mod as needing a manual install and hand the UI the details."""
        mod = pm.build_mod
        folder = str(manual.mod_root) if manual.mod_root else ""
        self._set_status(pm, ModStatus.MANUAL, folder)
        self._log(
            f"  This mod can't be installed automatically - it needs a few manual "
            f"steps. Its files are ready in: {folder}", "warning")
        if manual.readme:
            self._log("  Follow the mod's own instructions (readme shown in the app).", "muted")
        if self._on_manual:
            self._on_manual(mod.file_id, mod.name, folder, manual.readme or "")

    def _install_one(self, pm: PipelineMod, plan: InstallPlan) -> None:
        game_path = self._game_path
        mod = pm.build_mod
        # Actionable directives parsed from the build guide (which option to
        # pick, which files to copy, etc.). See installer/build_directives.py.
        dirs = mod.directives

        def log_cb(msg: str) -> None:
            self._log(f"    {msg}", "muted")

        method = plan.method

        # ---- HoloPatcher: fully headless ----
        if method == InstallMethod.HOLOPATCHER:
            exe = plan.holopatcher_exe
            tslpatchdata = exe.parent / "tslpatchdata" if exe else None
            if not tslpatchdata or not tslpatchdata.exists():
                if exe:
                    for candidate in exe.parent.rglob("tslpatchdata"):
                        if candidate.is_dir():
                            tslpatchdata = candidate
                            break
            if not exe or not tslpatchdata:
                raise PatcherError("Cannot find HoloPatcher.exe or tslpatchdata/")

            ns_index = 0
            if plan.namespaces:
                names = [f"{ns.name} {ns.description}" for ns in plan.namespaces]
                matched = match_option_index(names, dirs, mod.option_hint)
                if matched is not None:
                    ns_index = matched
                    self._log(
                        f"    Namespace: {plan.namespaces[ns_index].name} "
                        f"(matched build-guide instructions)", "muted")
                else:
                    self._log(
                        f"    Namespace: {plan.namespaces[ns_index].name} "
                        f"(default of {len(plan.namespaces)})", "muted")
            run_holopatcher(exe, game_path, tslpatchdata, ns_index, log_cb,
                            stop_event=self._stop_event)
            pm.strategy_used = "holopatcher"
            self._apply_compat_patches(pm, plan)

        # ---- TSLPatcher: strategy cascade (headless first) ----
        elif method == InstallMethod.TSLPATCHER:
            def on_waiting() -> None:
                self._set_status(pm, ModStatus.WAITING_PATCHER)
                self._log(
                    f"  [TSLPatcher] Manual step for: {mod.name}\n"
                    f"    Game path is on your clipboard - paste it, click Install, close the window.",
                    "warning"
                )

            if dirs.multi_run_options:
                # Run the patcher once per named option in the order the build
                # guide specifies (e.g. TSLRCM Tweak Pack's 6 separate options).
                strategies: list[str] = []
                for i, opt in enumerate(dirs.multi_run_options, 1):
                    label = opt if opt else "main (default)"
                    self._log(
                        f"    Run {i}/{len(dirs.multi_run_options)}: {label}", "muted")
                    run_dirs = copy.copy(dirs)
                    # Empty string = install the default/main option; non-empty = named option.
                    if opt:
                        run_dirs.namespace_preferences = [opt]
                        run_dirs.prefer_compatible = False
                    else:
                        run_dirs.namespace_preferences = []
                        run_dirs.prefer_compatible = False
                    run_dirs.multi_run = False
                    run_dirs.multi_run_options = []
                    result = run_tslpatcher_cascade(
                        mod_root=plan.mod_root,
                        exe=plan.tslpatcher_exe,
                        game_dir=game_path,
                        option_hint=opt,
                        directives=run_dirs,
                        cb=log_cb,
                        on_waiting=on_waiting,
                        allow_manual=not self._auto_unattended,
                    )
                    strategies.append(result.strategy)
                    if pm.status == ModStatus.WAITING_PATCHER:
                        self._set_status(pm, ModStatus.INSTALLING)
                pm.strategy_used = f"{strategies[0]}x{len(strategies)}"
            else:
                result = run_tslpatcher_cascade(
                    mod_root=plan.mod_root,
                    exe=plan.tslpatcher_exe,
                    game_dir=game_path,
                    option_hint=mod.option_hint,
                    directives=dirs,
                    cb=log_cb,
                    on_waiting=on_waiting,
                    allow_manual=not self._auto_unattended,
                )
                pm.strategy_used = result.strategy
                if pm.status == ModStatus.WAITING_PATCHER:
                    self._set_status(pm, ModStatus.INSTALLING)

            self._apply_compat_patches(pm, plan)

        # ---- TLK replacement / multi-variant ----
        elif method in (InstallMethod.TLK_REPLACE, InstallMethod.MULTI_VARIANT):
            variants = plan.tlk_variants
            chosen_label, chosen_path = variants[0]
            if len(variants) > 1:
                matched = match_option_index(
                    [lbl for lbl, _ in variants], dirs, mod.option_hint)
                if matched is not None:
                    chosen_label, chosen_path = variants[matched]
            self._log(f"    TLK variant: {chosen_label}", "muted")

            def tlk_chooser(_variants):
                return (chosen_label, chosen_path)

            install(plan, game_path, log_cb, tlk_variant_chooser=tlk_chooser)
            pm.strategy_used = "tlk_copy"

        # ---- Override / Direct copy / Multiple ----
        elif method in (InstallMethod.OVERRIDE_COPY, InstallMethod.DIRECT_COPY, InstallMethod.MULTIPLE):
            self._apply_file_selection(plan, dirs)
            self._apply_renames(plan, dirs)
            install(plan, game_path, log_cb)
            self._remove_dds_conflicts(plan)
            # Apply any patcher-based compat patches in subfolders (e.g. Ebon Hawk K1
            # "Compatibility Patches" folder). Loose-file subfolders are already
            # included by _collect_loose_files and don't need a separate pass.
            self._apply_compat_patches(pm, plan, patcher_only=True)
            pm.strategy_used = "file_copy"

        # ---- Standalone game-binary patcher (e.g. 3C-FD Patcher, fog fixes) ----
        elif method == InstallMethod.GAME_PATCHER:
            import subprocess
            exe = plan.tslpatcher_exe
            if not exe or not exe.exists():
                raise ManualInstallRequired(plan.mod_root, plan.readme_text)
            # Put game folder on clipboard so user can paste it when prompted.
            try:
                subprocess.run(
                    ["clip"], input=str(self._game_path),
                    text=True, check=False, capture_output=True,
                )
            except Exception:
                pass
            self._set_status(pm, ModStatus.WAITING_PATCHER)
            self._log(
                f"  [Game Patcher] Opening {exe.name} to apply game-level patches.\n"
                f"    Your game folder is on the clipboard: {self._game_path}\n"
                f"    Select your game executable in the patcher window and apply the patches.",
                "warning",
            )
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            raise ManualInstallRequired(plan.mod_root, plan.readme_text)

        # ---- Manual ----
        elif method == InstallMethod.MANUAL:
            raise ManualInstallRequired(plan.mod_root, plan.readme_text)

    @staticmethod
    def _is_patcher_plan(plan: InstallPlan) -> bool:
        return plan.method in (InstallMethod.TSLPATCHER, InstallMethod.HOLOPATCHER)

    # ------------------------------------------------------------------
    # Compat-patch subfolder handling
    # ------------------------------------------------------------------

    def _compat_folder_matches_batch(self, folder_name: str) -> str:
        """
        Returns the name of the first mod in the batch whose name/slug contains
        all significant keywords from the folder name. Used for log context only;
        compat patches are applied regardless of match result.
        """
        _SKIP = {"patch", "compat", "compatibility", "fix", "fixes", "for", "and",
                 "with", "the", "install", "mod", "option", "ver", "version"}
        tokens = [w for w in re.findall(r'[a-z0-9]{2,}', folder_name.lower())
                  if w not in _SKIP]
        if not tokens:
            return ""
        for pm_check in self._mods:
            nm = pm_check.build_mod.name.lower()
            sl = (pm_check.build_mod.slug or "").lower()
            haystack = f"{nm} {sl}"
            if all(t in haystack for t in tokens):
                return pm_check.build_mod.name
        return ""

    def _install_sub_plan(self, pm: PipelineMod, sub_plan: InstallPlan) -> None:
        """Execute a single compat-patch sub-plan without full directive processing."""
        game_path = self._game_path
        mod = pm.build_mod
        method = sub_plan.method

        def log_cb(msg: str) -> None:
            self._log(f"      {msg}", "muted")

        if method == InstallMethod.HOLOPATCHER:
            exe = sub_plan.holopatcher_exe
            tslpatchdata = exe.parent / "tslpatchdata" if exe else None
            if exe and (not tslpatchdata or not tslpatchdata.exists()):
                for candidate in exe.parent.rglob("tslpatchdata"):
                    if candidate.is_dir():
                        tslpatchdata = candidate
                        break
            if exe and tslpatchdata:
                run_holopatcher(exe, game_path, tslpatchdata, 0, log_cb,
                                stop_event=self._stop_event)

        elif method == InstallMethod.TSLPATCHER:
            def on_waiting_sub() -> None:
                self._set_status(pm, ModStatus.WAITING_PATCHER)

            run_tslpatcher_cascade(
                mod_root=sub_plan.mod_root,
                exe=sub_plan.tslpatcher_exe,
                game_dir=game_path,
                option_hint=mod.option_hint,
                directives=mod.directives,
                cb=log_cb,
                on_waiting=on_waiting_sub,
                allow_manual=not self._auto_unattended,
            )
            if pm.status == ModStatus.WAITING_PATCHER:
                self._set_status(pm, ModStatus.INSTALLING)

        elif method == InstallMethod.MULTIPLE:
            # Recursively handle each sub-plan, respecting file_except exclusions.
            dirs = pm.build_mod.directives
            for sp in sub_plan.sub_plans:
                sp_name = sp.mod_root.name if sp.mod_root else ""
                if dirs.file_except and sp_name and any(
                    e.lower().strip() in sp_name.lower() for e in dirs.file_except
                ):
                    self._log(f"      Skipped: {sp_name} (excluded by build guide)", "muted")
                    continue
                self._install_sub_plan(pm, sp)

        elif method in (InstallMethod.OVERRIDE_COPY, InstallMethod.DIRECT_COPY):
            install(sub_plan, game_path, log_cb)

    def _apply_compat_patches(self, pm: PipelineMod, plan: InstallPlan,
                              patcher_only: bool = False) -> None:
        """
        After an install, scan for compat-patch subfolders and apply them.
        In a curated build every bundled compat patch is intentional, so we apply
        all of them except those explicitly excluded by file_except.

        patcher_only: when True (used after DIRECT_COPY/OVERRIDE_COPY installs),
        only run patcher-based sub-plans - loose-file subfolders are already
        included by _collect_loose_files and do not need a second pass.
        """
        dirs = pm.build_mod.directives
        _SKIP_NAMES = {"tslpatchdata", "backup", "__macosx", ".ds_store",
                       "data", "docs", "documentation", "readme"}
        _PATCHER_METHODS = {InstallMethod.TSLPATCHER, InstallMethod.HOLOPATCHER,
                            InstallMethod.MULTIPLE}
        try:
            subdirs = sorted(
                [d for d in plan.mod_root.iterdir()
                 if d.is_dir() and d.name.lower() not in _SKIP_NAMES],
                key=lambda d: d.name.lower(),
            )
        except OSError:
            return

        if not subdirs:
            return

        applied = 0
        for sub_dir in subdirs:
            folder_name = sub_dir.name
            folder_low = folder_name.lower()

            # Respect explicit build-guide exclusions.
            if dirs.file_except and any(
                e.lower().strip() == folder_low or e.lower().strip() in folder_low
                for e in dirs.file_except
            ):
                self._log(
                    f"    Compat skipped: {folder_name} (excluded by build guide)", "muted")
                continue

            sub_plan = detect(sub_dir)
            if sub_plan.method in (InstallMethod.MANUAL, InstallMethod.GAME_PATCHER):
                continue
            if patcher_only and sub_plan.method not in _PATCHER_METHODS:
                continue

            matched = self._compat_folder_matches_batch(folder_name)
            if matched:
                self._log(f"    Compat: {folder_name} (for {matched})", "muted")
            else:
                self._log(f"    Compat: {folder_name}", "muted")

            try:
                self._install_sub_plan(pm, sub_plan)
                applied += 1
            except ManualInstallRequired:
                self._log(f"    Compat {folder_name}: needs manual step", "warning")
            except (PatcherError, InstallError) as e:
                self._log(f"    Compat {folder_name} failed: {e}", "warning")
            except Exception as e:
                self._log(f"    Compat {folder_name} failed: {e}", "warning")
            if self._stop_event.is_set():
                break

        if applied:
            self._log(f"    Applied {applied} compat patch(es).", "muted")

    # ------------------------------------------------------------------
    # Post-install cleanup
    # ------------------------------------------------------------------

    def _remove_dds_conflicts(self, plan: InstallPlan) -> None:
        """
        Remove .tpc / .tga files from Override when a .dds with the same stem was
        just installed. Some engine versions prefer .tpc over .dds, so the old
        files must be gone for HD textures to take effect.
        """
        override_dir = self._game_path / "Override"
        if not override_dir.exists():
            return
        dds_stems = {
            fm.source.stem.lower()
            for fm in plan.file_mappings
            if fm.source.suffix.lower() == ".dds"
            and fm.dest_relative.lower().startswith("override/")
        }
        if not dds_stems:
            return
        removed: list[str] = []
        for stem in dds_stems:
            for ext in (".tpc", ".tga"):
                conflict = override_dir / f"{stem}{ext}"
                if not conflict.exists():
                    # Case-insensitive fallback for mounted game dirs on Linux/Mac.
                    for f in override_dir.iterdir():
                        if f.name.lower() == f"{stem}{ext}":
                            conflict = f
                            break
                if conflict.exists():
                    try:
                        conflict.unlink()
                        removed.append(conflict.name)
                    except OSError as e:
                        self._log(f"    Could not remove {conflict.name}: {e}", "warning")
        if removed:
            n = len(removed)
            listed = ", ".join(removed[:5])
            extra = f" +{n - 5} more" if n > 5 else ""
            self._log(f"    Removed {n} outdated file(s): {listed}{extra}", "muted")

    @staticmethod
    def _safe_delete_target(game_path: Path, subdir: str, fn: str) -> "Path | None":
        """Return a validated path for a build-guide delete directive, or None if unsafe.

        Rejects filenames containing path separators or '..' components so a
        crafted build guide cannot traverse outside the intended subdirectory.
        """
        p = Path(fn)
        # Reject multi-component paths and any '..' traversal attempt.
        if len(p.parts) != 1 or ".." in p.parts:
            return None
        # Also reject embedded separators that Path() might not split on Windows.
        if "/" in fn or "\\" in fn:
            return None
        target = game_path / subdir / fn
        allowed_root = (game_path / subdir).resolve()
        try:
            if not target.resolve().is_relative_to(allowed_root):
                return None
        except (OSError, ValueError):
            return None
        return target

    def _apply_post_delete(self, dirs) -> None:
        """Delete files from Override per explicit build-guide post-install directives."""
        filenames = getattr(dirs, "post_install_delete", [])
        if not filenames:
            return
        for fn in filenames:
            for subdir in ("Override", "Modules"):
                target = self._safe_delete_target(self._game_path, subdir, fn)
                if target and target.exists():
                    try:
                        target.unlink()
                        self._log(
                            f"    Cleaned up {subdir}/{fn} (per build guide)", "muted")
                    except OSError as e:
                        self._log(f"    Could not clean up {fn}: {e}", "warning")

    def _apply_pre_delete(self, pm: PipelineMod, dirs) -> None:
        """Delete stale files from Override/Modules before installing this mod.

        Build guides say "delete X before install" to clear old texture versions
        that would otherwise shadow the replacement from this mod.
        """
        filenames = getattr(dirs, "pre_install_delete", [])
        if not filenames:
            return
        deleted: list[str] = []
        for fn in filenames:
            for subdir in ("Override", "Modules"):
                target = self._safe_delete_target(self._game_path, subdir, fn)
                if target is None:
                    continue
                if not target.exists():
                    parent = self._game_path / subdir
                    if parent.is_dir():
                        for f in parent.iterdir():
                            if f.name.lower() == fn.lower():
                                target = f
                                break
                if target.exists():
                    try:
                        target.unlink()
                        deleted.append(f"{subdir}/{fn}")
                    except OSError as e:
                        self._log(f"    Could not remove {subdir}/{fn}: {e}", "warning")
        if deleted:
            n = len(deleted)
            listed = ", ".join(deleted[:5])
            extra = f" +{n - 5} more" if n > 5 else ""
            self._log(f"  Pre-install: removed {n} outdated file(s): {listed}{extra}", "muted")

    def _resolve_skip_constraints(self) -> None:
        """Mark mods as SKIPPED when a mutex alternative is in the same batch.

        Handles build-guide notes like 'skip if using 3C-FD Patcher' so the
        pipeline never installs two mutually-exclusive mods at once.
        """
        batch = [
            (pm.build_mod.name.lower(), (pm.build_mod.slug or "").lower())
            for pm in self._mods
        ]
        for pm in self._mods:
            if pm.status != ModStatus.PENDING:
                continue
            skip_if = getattr(pm.build_mod.directives, "skip_if", [])
            for skip_name in skip_if:
                sn = skip_name.lower().strip()
                if len(sn) < 3:
                    continue
                for name, slug in batch:
                    if name == pm.build_mod.name.lower():
                        continue
                    if sn in name or sn in slug:
                        self._set_status(pm, ModStatus.SKIPPED)
                        self._log(
                            f"  [{pm.build_mod.name}] Skipped - not needed "
                            f"when '{skip_name}' is also being installed.",
                            "muted",
                        )
                        break
                if pm.status == ModStatus.SKIPPED:
                    break

    def _check_dependencies(self) -> None:
        """Warn when mods that need a community patch don't have it in the batch."""
        pending = [pm for pm in self._mods if pm.status == ModStatus.PENDING]
        if not pending:
            return
        compat_needers = [
            pm for pm in pending
            if getattr(pm.build_mod.directives, "prefer_compatible", False)
        ]
        if not compat_needers:
            return
        haystack = " ".join(
            f"{pm.build_mod.name.lower()} {(pm.build_mod.slug or '').lower()}"
            for pm in pending
        )
        # The community patch is often installed in an earlier run and deselected
        # this time round. Count anything already recorded in the library as
        # present so we don't warn about a patch the player already has.
        if self._game_type:
            try:
                from installer.mod_manager import load_manifest
                for im in load_manifest(self._game_type).mods:
                    haystack += f" {im.name.lower()} {(im.source_slug or '').lower()}"
            except Exception:
                pass
        _CP_TOKENS = [
            "k1cp", "k2cp", "tslrcm", "community patch",
            "kotor-1-community-patch", "kotor-2-community-patch",
            "tsl-restored", "sith-lords-restored",
        ]
        if any(tok in haystack for tok in _CP_TOKENS):
            return
        names = ", ".join(f"'{pm.build_mod.name}'" for pm in compat_needers[:3])
        extra = f" and {len(compat_needers) - 3} more" if len(compat_needers) > 3 else ""
        self._log(
            f"Warning: {names}{extra} need a community patch (K1CP / TSLRCM / K2CP) "
            f"that isn't in the selected mods. They may not install correctly without it.",
            "warning",
        )

    def _apply_build_guide_order(self, pm: PipelineMod, dirs) -> None:
        """
        For a "the patch is run first" mod, make the patcher run before the
        loose-file copy (the opposite of our default). Applies both across this
        mod's components and within a MULTIPLE plan's sub-plans.
        """
        if not dirs.patch_first:
            return
        before = [p.method.name for p in pm.plans]
        pm.plans.sort(key=lambda p: 0 if self._is_patcher_plan(p) else 1)
        for p in pm.plans:
            if p.sub_plans:
                p.sub_plans.sort(key=lambda sp: 0 if self._is_patcher_plan(sp) else 1)
        after = [p.method.name for p in pm.plans]
        if before != after:
            self._log("  Build guide: applying the patch first, as instructed.", "muted")

    def _log_build_guide_notes(self, pm: PipelineMod, dirs) -> None:
        """
        Surface the build-guide steps we deliberately do NOT guess at - extra
        patcher runs and required external patches - so the player can finish
        them. Guessing which optional re-runs to apply could change the game
        beyond the build's baseline, so we tell the user instead.
        """
        mod = pm.build_mod
        if dirs.requires_patch:
            self._log(
                f"  Heads up for '{mod.name}': the build guide says a patch must be "
                f"installed for this mod. If it was bundled it has been applied; if it "
                f"links an external patch, install that too.", "warning")
        if dirs.multi_run:
            if dirs.multi_run_options:
                opts_list = ", ".join(f'"{o or "main (default)"}"' for o in dirs.multi_run_options)
                self._log(
                    f"  '{mod.name}': running the patcher {len(dirs.multi_run_options)} times "
                    f"in order: {opts_list}.",
                    "muted")
            else:
                self._log(
                    f"  Heads up for '{mod.name}': this mod's guide asks for the patcher to "
                    f"be run more than once (e.g. a compatibility or optional component). "
                    f"The main option was installed; re-run it for any extra options you want.",
                    "warning")
            if mod.instructions:
                self._log(f"    Guide: {mod.instructions[:400]}", "muted")
        for note in dirs.manual_notes[:3]:
            self._log(f"  Note for '{mod.name}': {note}", "warning")

    def _apply_file_selection(self, plan: InstallPlan, dirs) -> None:
        """
        Drop or keep loose files per the build guide's "only move X" / "move all
        EXCEPT Y" / "ignore the Z folder" instructions, so we don't copy files
        the guide says to leave out (which would create conflicts a later mod
        handles). Applied to the plan and any sub-plans (MULTIPLE).
        """
        from installer.build_directives import select_paths

        if not dirs.file_only and not dirs.file_except:
            return
        for p in [plan, *plan.sub_plans]:
            if not p.file_mappings:
                continue
            rels = []
            for m in p.file_mappings:
                try:
                    rels.append(str(m.source.relative_to(p.mod_root)).replace("\\", "/"))
                except ValueError:
                    rels.append(m.source.name)
            kept, dropped = select_paths(rels, dirs)
            if not dropped:
                continue
            keptset = set(kept)
            p.file_mappings = [m for m, r in zip(p.file_mappings, rels) if r in keptset]
            self._log(
                f"    Build guide: copying {len(p.file_mappings)} of {len(rels)} "
                f"file(s); skipped {len(dropped)} per the install instructions.",
                "muted",
            )
            for d in dropped[:6]:
                self._log(f"      skipped: {d}", "muted")

    def _apply_renames(self, plan: InstallPlan, dirs) -> None:
        """Add copy-under-new-name mappings from the build guide's rename directives."""
        rename_copies = getattr(dirs, "rename_copies", [])
        rename_base = getattr(dirs, "rename_base_copies", "")
        if not rename_copies and not rename_base:
            return

        new_mappings: list[ModFileMapping] = []

        for src_name, dst_name in rename_copies:
            src_low = src_name.lower()
            src_stem = src_low.rsplit(".", 1)[0] if "." in src_low else src_low
            for fm in plan.file_mappings:
                fn_low = fm.source.name.lower()
                # Match exact filename or stem-only (source name lacks extension).
                if fn_low == src_low or ("." not in src_low and fn_low.startswith(src_stem + ".")):
                    parts = fm.dest_relative.rsplit("/", 1)
                    dst_rel = f"{parts[0]}/{dst_name}" if len(parts) > 1 else dst_name
                    new_mappings.append(ModFileMapping(source=fm.source, dest_relative=dst_rel))
                    self._log(f"    Rename copy: {fm.source.name} -> {dst_name}", "muted")
                    break

        if rename_base:
            for fm in plan.file_mappings:
                suffix = fm.source.suffix.lower()
                dst_name = f"{rename_base}{suffix}"
                parts = fm.dest_relative.rsplit("/", 1)
                dst_rel = f"{parts[0]}/{dst_name}" if len(parts) > 1 else dst_name
                if dst_rel != fm.dest_relative:
                    new_mappings.append(ModFileMapping(source=fm.source, dest_relative=dst_rel))
                    self._log(f"    Rename copy: {fm.source.name} -> {dst_name}", "muted")

        if new_mappings:
            plan.file_mappings.extend(new_mappings)

    # ------------------------------------------------------------------
    # Mod-manager recording
    # ------------------------------------------------------------------

    @staticmethod
    def _is_baked(plan: InstallPlan) -> bool:
        return plan.method in (InstallMethod.TSLPATCHER, InstallMethod.HOLOPATCHER)

    def _pre_install_snapshot(self, plan: InstallPlan) -> dict:
        """Capture pre-install state needed to record this plan after success."""
        if not self._record_to_library:
            return {}
        from installer import mod_manager
        if self._is_baked(plan):
            return {"baked": True, "before": mod_manager.snapshot_targets(self._game_path)}
        mappings = loose_mappings(plan)
        pre_existing = {
            rel for (rel, _src) in mappings
            if (self._game_path / rel).exists()
        }
        return {"baked": False, "mappings": mappings, "pre_existing": pre_existing}

    def _record_install(self, pm: PipelineMod, plan: InstallPlan, pre: dict) -> None:
        if not self._record_to_library or not pre:
            return
        from installer import mod_manager
        mod = pm.build_mod
        try:
            if pre.get("baked"):
                after = mod_manager.snapshot_targets(self._game_path)
                mod_manager.record_install(
                    self._game_key, self._game_path,
                    name=mod.name, install_method=plan.method.name,
                    source_type="build", source_ref=mod.file_id,
                    deploy_kind=mod_manager.DeployKind.BAKED.value,
                    snapshot_before=pre.get("before"), snapshot_after=after,
                    build_key=mod.build_key, option_hint=mod.option_hint,
                    readme_text=plan.readme_text, game_type=self._game_type,
                    source_slug=mod.slug, category=getattr(mod, "category", "") or "",
                )
            else:
                mod_manager.record_install(
                    self._game_key, self._game_path,
                    name=mod.name, install_method=plan.method.name,
                    source_type="build", source_ref=mod.file_id,
                    deploy_kind=mod_manager.DeployKind.LOOSE.value,
                    plan_file_mappings=pre.get("mappings"),
                    pre_existing=pre.get("pre_existing"),
                    build_key=mod.build_key, option_hint=mod.option_hint,
                    readme_text=plan.readme_text, game_type=self._game_type,
                    source_slug=mod.slug, category=getattr(mod, "category", "") or "",
                )
        except Exception as e:  # recording must never fail an install
            self._log(f"    (library record skipped: {e})", "muted")


def loose_mappings(plan: InstallPlan) -> list[tuple[str, "Path | None"]]:
    """
    Collect (dest_relative, source) for a loose plan, recursing into sub-plans.
    TLK plans deploy dialog.tlk at game root.
    """
    out: list[tuple[str, "Path | None"]] = []
    for fm in plan.file_mappings:
        out.append((fm.dest_relative, fm.source))
    for sub in plan.sub_plans:
        out.extend(loose_mappings(sub))
    if plan.method in (InstallMethod.TLK_REPLACE, InstallMethod.MULTI_VARIANT):
        if not any(rel.lower() == "dialog.tlk" for rel, _ in out):
            out.append(("dialog.tlk", None))
    return out
