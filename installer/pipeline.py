"""
Sequential mod installation pipeline.
For each mod in build order: download → extract → detect → install.

- Multi-file submissions are downloaded and installed in order.
- TSLPatcher mods go through the strategy cascade (headless HoloPatcher shim →
  Win32 automation → pywinauto → manual GUI) so almost nothing needs a click.
- Install-phase progress is reported so the UI can show live status.
"""
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

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
    ERROR            = "Error"


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
        auto_unattended: bool = False,
        game_key: str = "",
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
        # When True, never fall back to a manual GUI click (fully unattended).
        self._auto_unattended = auto_unattended
        # Mod-manager recording (e.g. "KOTOR1"); empty disables recording.
        self._game_key = game_key
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
        try:
            for pm in self._mods:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()
                if pm.status in (ModStatus.DONE, ModStatus.SKIPPED):
                    continue
                self._current = pm
                self._process_mod(pm)
        finally:
            self._running = False
            self._current = None

    def _process_mod(self, pm: PipelineMod) -> None:
        mod = pm.build_mod
        self._log(f"\n── [{mod.install_order:3d}] {mod.name}")

        # ---- Download (all files in the submission) ----
        try:
            self._set_status(pm, ModStatus.DOWNLOADING)
            dest_dir = self._download_dir / f"{mod.file_id}_{mod.slug[:30]}"
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

            archives = self._client.download_all_files(
                file_id=mod.file_id,
                slug=mod.slug,
                dest_dir=dest_dir,
                progress_callback=dl_progress,
                cancel_event=self._stop_event,
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
            return
        except Exception as e:
            self._set_status(pm, ModStatus.ERROR, str(e))
            self._log(f"  Unexpected download error: {e}", "error")
            pm.error = str(e)
            return

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

        self._set_status(pm, ModStatus.INSTALLING)
        total = len(pm.plans)
        try:
            for i, plan in enumerate(pm.plans, 1):
                if total > 1:
                    self._log(f"  Component {i}/{total}: {plan.method.name}", "muted")
                else:
                    self._log(f"  Method: {plan.method.name}", "muted")
                self._install_progress(pm, (i - 1) / total, f"{plan.method.name} ({i}/{total})")
                pre = self._pre_install_snapshot(plan)
                self._install_one(pm, plan)
                self._record_install(pm, plan, pre)
                self._install_progress(pm, i / total, "Done")

            self._set_status(pm, ModStatus.DONE)
            note = f" via {pm.strategy_used}" if pm.strategy_used else ""
            self._log(f"  Installed.{note}", "success")
        except InstallError as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:200])
            self._log(f"  Install error: {e}", "error")
            pm.error = str(e)
        except PatcherError as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:200])
            self._log(f"  Patcher error: {e}", "error")
            pm.error = str(e)
        except Exception as e:
            self._set_status(pm, ModStatus.ERROR, str(e)[:200])
            self._log(f"  Unexpected install error: {e}", "error")
            pm.error = str(e)

    def _install_one(self, pm: PipelineMod, plan: InstallPlan) -> None:
        game_path = self._game_path
        mod = pm.build_mod

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
            if plan.namespaces and mod.option_hint:
                hint = mod.option_hint.lower()
                for i, ns in enumerate(plan.namespaces):
                    if hint in ns.name.lower() or hint in ns.description.lower():
                        ns_index = i
                        break
            if plan.namespaces:
                self._log(f"    Namespace: {plan.namespaces[ns_index].name}", "muted")
            run_holopatcher(exe, game_path, tslpatchdata, ns_index, log_cb)
            pm.strategy_used = "holopatcher"

        # ---- TSLPatcher: strategy cascade (headless first) ----
        elif method == InstallMethod.TSLPATCHER:
            def on_waiting() -> None:
                self._set_status(pm, ModStatus.WAITING_PATCHER)
                self._log(
                    f"  [TSLPatcher] Manual step for: {mod.name}\n"
                    f"    Game path is on your clipboard — paste it, click Install, close the window.",
                    "warning"
                )

            result = run_tslpatcher_cascade(
                mod_root=plan.mod_root,
                exe=plan.tslpatcher_exe,
                game_dir=game_path,
                option_hint=mod.option_hint,
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
            if len(variants) > 1 and mod.option_hint:
                hint = mod.option_hint.replace("_", " ").lower()
                for label, path in variants:
                    if hint in label.lower():
                        chosen_label, chosen_path = label, path
                        break
            self._log(f"    TLK variant: {chosen_label}", "muted")

            def tlk_chooser(_variants):
                return (chosen_label, chosen_path)

            install(plan, game_path, log_cb, tlk_variant_chooser=tlk_chooser)
            pm.strategy_used = "tlk_copy"

        # ---- Override / Direct copy / Multiple ----
        elif method in (InstallMethod.OVERRIDE_COPY, InstallMethod.DIRECT_COPY, InstallMethod.MULTIPLE):
            install(plan, game_path, log_cb)
            pm.strategy_used = "file_copy"

        # ---- Manual ----
        elif method == InstallMethod.MANUAL:
            if plan.readme_text:
                self._log(
                    f"  [MANUAL] Requires manual installation. Readme in: {plan.mod_root}",
                    "warning"
                )
            raise InstallError(
                f"Manual install required for: {mod.name}\nMod files are at: {plan.mod_root}"
            )

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
