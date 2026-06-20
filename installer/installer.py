"""Execute install plans for KOTOR mods."""

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from installer.detector import InstallMethod, InstallPlan, NamespaceOption


class InstallError(Exception):
    pass


ProgressCallback = Callable[[str], None]
NamespaceChooser = Callable[[list[NamespaceOption]], Optional[NamespaceOption]]
TlkVariantChooser = Callable[[list[tuple[str, Path]]], Optional[tuple[str, Path]]]


def _log(msg: str, cb: Optional[ProgressCallback]) -> None:
    if cb:
        cb(msg)
    else:
        print(msg)


def _copy_files(plan: InstallPlan, game_path: Path, cb: Optional[ProgressCallback]) -> None:
    for mapping in plan.file_mappings:
        dest = game_path / mapping.dest_relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        _log(f"  {'[overwrite]' if dest.exists() else '[copy]':12s} {mapping.dest_relative}", cb)
        shutil.copy2(mapping.source, dest)


def _run_patcher(
    exe: Path,
    cb: Optional[ProgressCallback],
    game_path: Optional[Path] = None,
) -> None:
    """Launch a patcher executable (TSLPatcher or HoloPatcher) and wait for it."""
    if not exe or not exe.exists():
        raise InstallError(f"Patcher not found: {exe}")

    _log(f"  Launching: {exe.name}", cb)
    if game_path:
        _log(f"  When prompted for game folder, enter:\n    {game_path}", cb)

    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    _log(f"  PID {proc.pid} — complete the GUI prompts, then close the patcher.", cb)
    proc.wait()
    _log(f"  Patcher exited.", cb)


def install(
    plan: InstallPlan,
    game_path: Path,
    cb: Optional[ProgressCallback] = None,
    namespace_chooser: Optional[NamespaceChooser] = None,
    tlk_variant_chooser: Optional[TlkVariantChooser] = None,
) -> None:
    """
    Execute an install plan.

    game_path: root of KOTOR1 or KOTOR2 installation.
    namespace_chooser: called when HoloPatcher has multiple namespace options.
    tlk_variant_chooser: called when TLK_REPLACE or MULTI_VARIANT has multiple options.
    """
    if not game_path.exists():
        raise InstallError(f"Game path does not exist: {game_path}")

    method = plan.method

    # ------------------------------------------------------------------ TSLPatcher
    if method == InstallMethod.TSLPATCHER:
        _log("[TSLPatcher] Running patcher...", cb)
        exe = plan.tslpatcher_exe
        if not exe or not exe.exists():
            raise InstallError(
                "TSLPatcher.exe not found. Install manually from:\n"
                f"  {plan.mod_root}"
            )
        _run_patcher(exe, cb, game_path)

    # ----------------------------------------------------------------- HoloPatcher
    elif method == InstallMethod.HOLOPATCHER:
        _log("[HoloPatcher] Running patcher...", cb)
        exe = plan.holopatcher_exe
        if not exe or not exe.exists():
            raise InstallError(
                "HoloPatcher.exe not found. Install manually from:\n"
                f"  {plan.mod_root}"
            )

        # If multiple namespaces, let caller choose (UI will show a picker)
        if plan.namespaces and namespace_chooser:
            chosen = namespace_chooser(plan.namespaces)
            if chosen is None:
                raise InstallError("No namespace selected — installation cancelled.")
            _log(f"  Namespace: {chosen.name}", cb)

        _run_patcher(exe, cb, game_path)

    # --------------------------------------------------------------- TLK replacement
    elif method == InstallMethod.TLK_REPLACE:
        variants = plan.tlk_variants
        if not variants:
            raise InstallError("No dialog.tlk found in this mod.")

        chosen_label, chosen_path = variants[0]  # default to first
        if len(variants) > 1 and tlk_variant_chooser:
            result = tlk_variant_chooser(variants)
            if result is None:
                raise InstallError("No variant selected — installation cancelled.")
            chosen_label, chosen_path = result

        dest = game_path / "dialog.tlk"
        if dest.exists():
            backup = game_path / "dialog.tlk.bak"
            if not backup.exists():
                _log(f"  Backing up existing dialog.tlk → dialog.tlk.bak", cb)
                shutil.copy2(dest, backup)
            else:
                _log(f"  dialog.tlk.bak already exists — skipping additional backup", cb)

        _log(f"  Installing variant: {chosen_label}", cb)
        shutil.copy2(chosen_path, dest)
        _log(f"  dialog.tlk installed to game root.", cb)

    # --------------------------------------------------------------- Multi-variant (TLK)
    elif method == InstallMethod.MULTI_VARIANT:
        variants = plan.tlk_variants
        chosen_label, chosen_path = variants[0]
        if len(variants) > 1 and tlk_variant_chooser:
            result = tlk_variant_chooser(variants)
            if result is None:
                raise InstallError("No variant selected — installation cancelled.")
            chosen_label, chosen_path = result

        dest = game_path / "dialog.tlk"
        if dest.exists():
            backup = game_path / "dialog.tlk.bak"
            if not backup.exists():
                _log(f"  Backing up existing dialog.tlk → dialog.tlk.bak", cb)
                shutil.copy2(dest, backup)
        _log(f"  Installing TLK variant: {chosen_label}", cb)
        shutil.copy2(chosen_path, dest)
        _log(f"  dialog.tlk installed.", cb)

    # ---------------------------------------------------------- Override / Direct copy
    elif method in (InstallMethod.OVERRIDE_COPY, InstallMethod.DIRECT_COPY):
        label = "Override" if method == InstallMethod.OVERRIDE_COPY else "direct"
        _log(f"[{label}] Copying {len(plan.file_mappings)} file(s)...", cb)
        _copy_files(plan, game_path, cb)
        _log("Done.", cb)

    # -------------------------------------------------------------------- Multiple
    elif method == InstallMethod.MULTIPLE:
        _log(f"[multi] Installing {len(plan.sub_plans)} sub-mod(s)...", cb)
        for i, sub in enumerate(plan.sub_plans, 1):
            _log(f"  [{i}/{len(plan.sub_plans)}] {sub.mod_root.name}", cb)
            install(sub, game_path, cb, namespace_chooser, tlk_variant_chooser)

    # ---------------------------------------------------------------------- Manual
    elif method == InstallMethod.MANUAL:
        msg = (
            "This mod requires manual installation.\n"
            + (plan.readme_text[:1000] if plan.readme_text else "No readme found.")
        )
        raise InstallError(msg)

    for warn in plan.warnings:
        _log(f"[warning] {warn}", cb)
