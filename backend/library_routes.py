"""
Mod-manager (Library) API routes.

Wraps installer.mod_manager: list installed mods, enable/disable/uninstall,
compute conflicts, import an arbitrary local mod, and reorder load order.
Mounted in server.py via include_router(library_router).
"""

import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import config as cfg
from backend.models import (
    ImportFolderRequest,
    ImportRequest,
    ReorderRequest,
    UninstallRequest,
    installed_mod_to_dict,
)
from installer import mod_manager
from installer.detector import InstallMethod

library_router = APIRouter(prefix="/api", tags=["library"])

# Set by server.py so we can resolve game paths + publish ws events.
_state = None


def bind_state(state) -> None:
    global _state
    _state = state


def _resolve(game: str = "KOTOR1", profile: str = "", override: Optional[str] = None):
    """
    Resolve a request to (scope, root_path, game_type).
    `scope` is the manifest key (profile id, or the game for the default profile).
    """
    if profile:
        prof = cfg.get_profile(profile)
        if prof:
            raw = override or prof.get("path", "")
            return profile, (Path(raw) if raw else None), prof.get("game", game)
    conf = cfg.load()
    key = "kotor1_path" if game == "KOTOR1" else "kotor2_path"
    raw = override or conf.get(key, "")
    return game, (Path(raw) if raw else None), game


def _publish(event: dict) -> None:
    if _state is not None:
        _state.hub.publish(event)


# ---------------------------------------------------------------------------
# Library listing
# ---------------------------------------------------------------------------

@library_router.get("/library")
def get_library(game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    scope, _root, game_type = _resolve(game, profile)
    manifest = mod_manager.load_manifest(scope)
    conflicts = mod_manager.compute_conflicts(scope)
    counts = mod_manager.conflict_counts_by_mod(conflicts)
    mods = sorted(manifest.mods, key=lambda m: m.load_order)
    return {
        "game": game_type, "profile": scope,
        "mods": [installed_mod_to_dict(m, counts.get(m.id, 0)) for m in mods],
    }


@library_router.get("/library/{mod_id}")
def get_library_mod(mod_id: str, game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    from dataclasses import asdict
    scope, _root, _gt = _resolve(game, profile)
    manifest = mod_manager.load_manifest(scope)
    mod = manifest.find(mod_id)
    if not mod:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    d = installed_mod_to_dict(mod)
    d["deployed_files"] = [asdict(f) for f in mod.deployed_files]
    d["baked_files"] = [asdict(f) for f in mod.baked_files]
    return d


# ---------------------------------------------------------------------------
# Enable / disable / uninstall
# ---------------------------------------------------------------------------

def _guard_not_running():
    if _state and _state.pipeline and _state.pipeline.is_running:
        return JSONResponse(status_code=409, content={"ok": False, "error": "install_running"})
    return None


def _toggle(mod_id: str, game: str, profile: str, action: str):
    busy = _guard_not_running()
    if busy:
        return busy
    scope, root, _gt = _resolve(game, profile)
    if not root or not root.exists():
        return JSONResponse(status_code=400, content={"ok": False, "error": "game_path_required"})
    try:
        fn = mod_manager.enable if action == "enable" else mod_manager.disable
        mod = fn(scope, root, mod_id)
    except mod_manager.ModNotToggleableError as e:
        return JSONResponse(status_code=409, content={"ok": False, "error": "not_toggleable", "message": str(e)})
    except mod_manager.ModManagerError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    conflicts = mod_manager.compute_conflicts(scope)
    counts = mod_manager.conflict_counts_by_mod(conflicts)
    _publish({"type": "library", "event": "changed", "profile": scope})
    return {"ok": True, "mod": installed_mod_to_dict(mod, counts.get(mod.id, 0)), "conflicts": conflicts}


@library_router.post("/library/{mod_id}/enable")
def enable_mod(mod_id: str, game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    return _toggle(mod_id, game, profile, "enable")


@library_router.post("/library/{mod_id}/disable")
def disable_mod(mod_id: str, game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    return _toggle(mod_id, game, profile, "disable")


@library_router.post("/library/{mod_id}/uninstall")
def uninstall_mod(mod_id: str, req: UninstallRequest,
                  game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    busy = _guard_not_running()
    if busy:
        return busy
    scope, root, _gt = _resolve(game, profile)
    if not root or not root.exists():
        return JSONResponse(status_code=400, content={"ok": False, "error": "game_path_required"})
    try:
        mod_manager.uninstall(scope, root, mod_id, force=req.force)
    except mod_manager.ModManagerError as e:
        return JSONResponse(status_code=409, content={"ok": False, "error": "baked_no_backup", "message": str(e)})
    _publish({"type": "library", "event": "changed", "profile": scope})
    return {"ok": True}


@library_router.post("/library/reorder")
def reorder_mods(req: ReorderRequest, profile: str = Query("")) -> dict:
    scope, _root, _gt = _resolve(req.game, profile)
    manifest = mod_manager.reorder(scope, req.ordered_ids)
    conflicts = mod_manager.compute_conflicts(scope)
    counts = mod_manager.conflict_counts_by_mod(conflicts)
    mods = sorted(manifest.mods, key=lambda m: m.load_order)
    _publish({"type": "library", "event": "changed", "profile": scope})
    return {"ok": True, "mods": [installed_mod_to_dict(m, counts.get(m.id, 0)) for m in mods], "conflicts": conflicts}


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------

@library_router.get("/conflicts")
def get_conflicts(game: str = Query("KOTOR1"), profile: str = Query("")) -> dict:
    scope, _root, _gt = _resolve(game, profile)
    return {"conflicts": mod_manager.compute_conflicts(scope)}


# ---------------------------------------------------------------------------
# Import arbitrary local mods (a single archive/folder, or a folder of archives)
# ---------------------------------------------------------------------------

_ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".7zip")


def _import_and_record(scope: str, root: Path, game_type: str, src: Path,
                       name: str, option_hint: str, unattended: bool) -> None:
    """Detect → install → record one archive/folder. Emits log + library events."""
    from installer.installer import install
    from installer.patcher_strategy import run_tslpatcher_cascade
    from installer.runner import run_holopatcher
    from installer.pipeline import loose_mappings

    def log(msg, tag=""):
        _publish({"type": "log", "message": msg, "tag": tag})

    try:
        extracted, plan = mod_manager.detect_import(src)
        if plan.method == InstallMethod.MANUAL:
            log(f"Skipped '{name}': needs manual installation.", "warning")
            return
        log(f"Importing: {name} ({plan.method.name})")
        baked = plan.method in (InstallMethod.TSLPATCHER, InstallMethod.HOLOPATCHER)
        if baked:
            before = mod_manager.snapshot_targets(root)
            if plan.method == InstallMethod.HOLOPATCHER:
                exe = plan.holopatcher_exe
                tslpatchdata = exe.parent / "tslpatchdata" if exe else None
                run_holopatcher(exe, root, tslpatchdata, 0, lambda m: log(f"  {m}", "muted"))
            else:
                run_tslpatcher_cascade(
                    mod_root=plan.mod_root, exe=plan.tslpatcher_exe, game_dir=root,
                    option_hint=option_hint, cb=lambda m: log(f"  {m}", "muted"),
                    allow_manual=not unattended,
                )
            after = mod_manager.snapshot_targets(root)
            rec = mod_manager.record_install(
                scope, root, name=name, install_method=plan.method.name,
                source_type="import", source_ref=str(src),
                deploy_kind=mod_manager.DeployKind.BAKED.value,
                snapshot_before=before, snapshot_after=after, option_hint=option_hint,
                readme_text=plan.readme_text, game_type=game_type,
            )
        else:
            mappings = loose_mappings(plan)
            pre_existing = {rel for (rel, _s) in mappings if (root / rel).exists()}
            install(plan, root, lambda m: log(f"  {m}", "muted"))
            rec = mod_manager.record_install(
                scope, root, name=name, install_method=plan.method.name,
                source_type="import", source_ref=str(src),
                deploy_kind=mod_manager.DeployKind.LOOSE.value,
                plan_file_mappings=mappings, pre_existing=pre_existing,
                option_hint=option_hint, readme_text=plan.readme_text, game_type=game_type,
            )
        log(f"Imported '{name}'.", "success")
        _publish({"type": "library", "event": "imported", "profile": scope,
                  "mod": installed_mod_to_dict(rec)})
    except Exception as e:
        log(f"Import failed for '{name}': {e}", "error")
        _publish({"type": "library", "event": "import_failed", "error": str(e)})


@library_router.post("/library/import")
def import_mod(req: ImportRequest) -> dict:
    scope, root, game_type = _resolve(req.game, req.profile, req.game_path)
    if not root or not root.exists():
        return JSONResponse(status_code=400, content={"ok": False, "error": "game_path_required", "game": req.game})

    src = Path(req.path)
    if not src.exists():
        return JSONResponse(status_code=400, content={"ok": False, "error": "path_not_found"})

    # Detect synchronously so the client learns the method (and manual case) up front.
    try:
        extracted, plan = mod_manager.detect_import(src)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"detect_failed: {e}"})
    if plan.method == InstallMethod.MANUAL:
        return {"ok": False, "error": "manual",
                "readme": plan.readme_text[:4000], "mod_root": str(plan.mod_root)}

    name = req.name or src.stem
    threading.Thread(
        target=_import_and_record,
        args=(scope, root, game_type, src, name, req.option_hint, req.unattended),
        daemon=True,
    ).start()
    return JSONResponse(status_code=202, content={"ok": True, "detected_method": plan.method.name})


@library_router.post("/library/import-folder")
def import_folder(req: ImportFolderRequest) -> dict:
    """Batch-import every mod archive in a folder (drag-and-drop a folder of zips)."""
    scope, root, game_type = _resolve(req.game, req.profile, req.game_path)
    if not root or not root.exists():
        return JSONResponse(status_code=400, content={"ok": False, "error": "game_path_required", "game": req.game})

    folder = Path(req.path)
    if not folder.exists() or not folder.is_dir():
        return JSONResponse(status_code=400, content={"ok": False, "error": "not_a_folder"})

    archives = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _ARCHIVE_EXTS
    )
    if not archives:
        return JSONResponse(status_code=400, content={"ok": False, "error": "no_archives_found"})

    def _run_all():
        _publish({"type": "log", "message": f"Importing {len(archives)} mod(s) from {folder.name}…", "tag": "info"})
        for arc in archives:
            _import_and_record(scope, root, game_type, arc, arc.stem, "", req.unattended)
        _publish({"type": "library", "event": "import_folder_done", "profile": scope, "count": len(archives)})
        _publish({"type": "log", "message": f"Folder import complete ({len(archives)} archive(s)).", "tag": "success"})

    threading.Thread(target=_run_all, daemon=True).start()
    return JSONResponse(status_code=202, content={"ok": True, "count": len(archives)})
