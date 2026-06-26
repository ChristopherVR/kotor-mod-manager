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
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from installer.build_directives import match_option_index
from installer.detector import InstallMethod, InstallPlan, detect
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
                        f.result()
                        del futures[f]
                        fill_pool()

                    if self._stop_event.is_set() or pm.status == ModStatus.ERROR:
                        continue

                    self._pause_event.wait()
                    self._current = pm
                    self._extract_and_install(pm)
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
            if keep_names:
                self._log(
                    f"  Build guide: downloading only {', '.join(keep_names)} "
                    f"(ignoring the other files in this submission).")
            archives = self._client.download_all_files(
                file_id=mod.file_id,
                slug=mod.slug,
                dest_dir=dest_dir,
                progress_callback=dl_progress,
                cancel_event=self._stop_event,
                pause_event=self._pause_event,
                keep_names=keep_names,
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

        # ---- Extract each archive ----
        try:
            self._set_status(pm, ModStatus.EXTRACTING)
            for archive in pm.archive_paths:
                extracted = extract(archive)
                pm.extracted_paths.append(extracted)
                self._log(f"  Extracted: {extracted.name}")
        except ExtractionError as e:
            self._set_status(pm, ModStatus.ERROR, str(e))
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

        self._set_status(pm, ModStatus.INSTALLING)
        total = len(pm.plans)
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
                except ManualInstallRequired as m:
                    # Not a failure: this component needs hand-installing. Remember
                    # it, finish any other components, then flag the mod as manual.
                    manual = m
                    continue
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
            run_holopatcher(exe, game_path, tslpatchdata, ns_index, log_cb)
            pm.strategy_used = "holopatcher"

        # ---- TSLPatcher: strategy cascade (headless first) ----
        elif method == InstallMethod.TSLPATCHER:
            def on_waiting() -> None:
                self._set_status(pm, ModStatus.WAITING_PATCHER)
                self._log(
                    f"  [TSLPatcher] Manual step for: {mod.name}\n"
                    f"    Game path is on your clipboard - paste it, click Install, close the window.",
                    "warning"
                )

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
            # If we showed the waiting banner, return to INSTALLING for cleanliness
            if pm.status == ModStatus.WAITING_PATCHER:
                self._set_status(pm, ModStatus.INSTALLING)

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
            install(plan, game_path, log_cb)
            pm.strategy_used = "file_copy"

        # ---- Manual ----
        elif method == InstallMethod.MANUAL:
            raise ManualInstallRequired(plan.mod_root, plan.readme_text)

    @staticmethod
    def _is_patcher_plan(plan: InstallPlan) -> bool:
        return plan.method in (InstallMethod.TSLPATCHER, InstallMethod.HOLOPATCHER)

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
