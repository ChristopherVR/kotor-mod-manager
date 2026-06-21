"""
Persistent KOTOR mod manager: tracks installed mods per game so installs are
reversible (enable/disable/uninstall) and conflicts are computable.

Two install classes:
  - LOOSE  (Override/Modules/Movies copies, dialog.tlk): a finite, known file
    set — fully reversible by moving files in/out of the game tree.
  - BAKED  (TSLPatcher/HoloPatcher): the patcher mutates shared files in place.
    Captured via a before/after snapshot delta; recorded but not cleanly
    toggleable (removal would need a full backup/restore).

State lives under ~/.kotor_mod_installer/:
  library/<GAME>.json     manifest
  disabled/<GAME>/<id>/   files moved out of the game tree while disabled
  backups/<GAME>/<id>/    displaced originals (for restore on uninstall)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import config as cfg

MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_LOCK = threading.RLock()

# Areas a patcher may touch (relative to game root).
SNAPSHOT_DIRS = ["Override", "Modules"]
SNAPSHOT_FILES = ["dialog.tlk"]


class ModManagerError(Exception):
    pass


class ModNotToggleableError(ModManagerError):
    pass


class DeployKind(str, Enum):
    LOOSE = "loose"
    BAKED = "baked"


class ModState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    BAKED = "baked"
    BROKEN = "broken"


class SourceType(str, Enum):
    BUILD = "build"
    DEADLYSTREAM = "deadlystream"
    IMPORT = "import"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DeployedFile:
    rel_path: str
    sha256: str
    size: int
    overwrote: bool = False
    backup_rel: Optional[str] = None


@dataclass
class BakedFile:
    rel_path: str
    post_sha256: str
    pre_sha256: Optional[str] = None
    created: bool = False


@dataclass
class InstalledMod:
    id: str
    name: str
    game: str
    source_type: str
    source_ref: str
    install_method: str
    deploy_kind: str
    state: str
    enabled: bool
    load_order: int
    install_ts: float = field(default_factory=time.time)
    build_key: Optional[str] = None
    option_hint: str = ""
    source_slug: str = ""
    deployed_files: list[DeployedFile] = field(default_factory=list)
    baked_files: list[BakedFile] = field(default_factory=list)
    # Incompatibilities the mod declares about ITSELF (parsed from its readme).
    incompatibilities: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def toggleable(self) -> bool:
        return self.deploy_kind == DeployKind.LOOSE.value


@dataclass
class GameManifest:
    schema_version: int = MANIFEST_SCHEMA_VERSION
    game: str = "KOTOR1"
    mods: list[InstalledMod] = field(default_factory=list)
    next_load_order: int = 0

    def find(self, mod_id: str) -> Optional[InstalledMod]:
        return next((m for m in self.mods if m.id == mod_id), None)


# ---------------------------------------------------------------------------
# Storage roots
# ---------------------------------------------------------------------------

def _library_dir() -> Path:
    d = cfg.CONFIG_DIR / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(game: str) -> Path:
    return _library_dir() / f"{game}.json"


def _disabled_root(game: str, mod_id: str) -> Path:
    return cfg.CONFIG_DIR / "disabled" / game / mod_id


def _backup_root(game: str, mod_id: str) -> Path:
    return cfg.CONFIG_DIR / "backups" / game / mod_id


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _mod_from_dict(d: dict) -> InstalledMod:
    d = dict(d)
    d["deployed_files"] = [DeployedFile(**f) for f in d.get("deployed_files", [])]
    d["baked_files"] = [BakedFile(**f) for f in d.get("baked_files", [])]
    # tolerate unknown/missing keys
    known = InstalledMod.__dataclass_fields__.keys()
    d = {k: v for k, v in d.items() if k in known}
    return InstalledMod(**d)


def load_manifest(game: str) -> GameManifest:
    path = _manifest_path(game)
    if not path.exists():
        return GameManifest(game=game)
    import json
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GameManifest(game=game)
    mods = [_mod_from_dict(m) for m in raw.get("mods", [])]
    return GameManifest(
        schema_version=raw.get("schema_version", MANIFEST_SCHEMA_VERSION),
        game=raw.get("game", game),
        mods=mods,
        next_load_order=raw.get("next_load_order", len(mods)),
    )


def save_manifest(m: GameManifest) -> None:
    import json
    path = _manifest_path(m.game)
    tmp = path.with_suffix(".json.tmp")
    data = {
        "schema_version": m.schema_version,
        "game": m.game,
        "next_load_order": m.next_load_order,
        "mods": [asdict(mod) for mod in m.mods],
    }
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_join(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    root_r = root.resolve()
    if p != root_r and root_r not in p.parents:
        raise ModManagerError(f"unsafe path escapes game root: {rel}")
    return p


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


import re

# Phrases a mod readme uses to declare it conflicts with another mod.
_INCOMPAT_PATTERNS = [
    r"incompatible with[:\s]+([^\n.;()]+)",
    r"not compatible with[:\s]+([^\n.;()]+)",
    r"do(?:es)?\s*n[o']t\s+work\s+with[:\s]+([^\n.;()]+)",
    r"conflicts?\s+with[:\s]+([^\n.;()]+)",
    r"do not (?:use|install)\s+(?:this\s+)?with[:\s]+([^\n.;()]+)",
]


def parse_incompatibilities(readme_text: str) -> list[str]:
    """
    Extract declared-incompatibility keywords from a mod's own readme so the
    manager can flag conflicts the mod itself warns about. Heuristic: capture
    the phrase after common 'incompatible with X' wordings.
    """
    if not readme_text:
        return []
    found: list[str] = []
    low = readme_text
    for pat in _INCOMPAT_PATTERNS:
        for m in re.finditer(pat, low, re.IGNORECASE):
            name = m.group(1).strip(" \t-–—\"'")
            # Trim trailing connective words and over-long captures.
            name = re.split(r"\b(?:and|or|but|because|since|as|if|when)\b", name, 1)[0].strip()
            name = name[:80].strip()
            if len(name) >= 4 and name.lower() not in (x.lower() for x in found):
                found.append(name)
    return found[:20]


def snapshot_targets(game_root: Path) -> dict[str, str]:
    """
    Cheap signature snapshot of patch-target areas: rel_posix -> "size:mtime_ns".
    Used to compute the touched-file delta around a patcher run without hashing
    everything up front.
    """
    sig: dict[str, str] = {}
    for d in SNAPSHOT_DIRS:
        base = game_root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                st = p.stat()
                sig[_rel_posix(p, game_root)] = f"{st.st_size}:{st.st_mtime_ns}"
    for f in SNAPSHOT_FILES:
        p = game_root / f
        if p.is_file():
            st = p.stat()
            sig[_rel_posix(p, game_root)] = f"{st.st_size}:{st.st_mtime_ns}"
    return sig


# ---------------------------------------------------------------------------
# Recording installs
# ---------------------------------------------------------------------------

def record_install(
    game: str,
    game_root: Path,
    *,
    name: str,
    install_method: str,
    source_type: str,
    source_ref: str,
    deploy_kind: str,
    plan_file_mappings: Optional[list[tuple[str, Path]]] = None,
    pre_existing: Optional[set[str]] = None,
    snapshot_before: Optional[dict[str, str]] = None,
    snapshot_after: Optional[dict[str, str]] = None,
    build_key: Optional[str] = None,
    option_hint: str = "",
    readme_text: str = "",
    game_type: str = "",
    source_slug: str = "",
) -> InstalledMod:
    """
    Record a completed install into the per-game manifest.

    Loose installs: pass plan_file_mappings [(dest_relative, source_path)] and
    optionally pre_existing (set of dest_relative that already existed).
    Baked installs: pass snapshot_before/after signature dicts.
    """
    with _MANIFEST_LOCK:
        manifest = load_manifest(game)
        mod_id = uuid.uuid4().hex
        load_order = manifest.next_load_order
        manifest.next_load_order += 1

        deployed: list[DeployedFile] = []
        baked: list[BakedFile] = []
        pre_existing = pre_existing or set()

        if deploy_kind == DeployKind.LOOSE.value and plan_file_mappings:
            backup_dir = _backup_root(game, mod_id)
            for dest_rel, _src in plan_file_mappings:
                dest = _safe_join(game_root, dest_rel)
                if not dest.is_file():
                    continue
                overwrote = dest_rel in pre_existing
                deployed.append(DeployedFile(
                    rel_path=dest_rel,
                    sha256=_sha256(dest),
                    size=dest.stat().st_size,
                    overwrote=overwrote,
                ))
            _ = backup_dir  # reserved for displaced-original backups (future)

        elif deploy_kind == DeployKind.BAKED.value:
            before = snapshot_before or {}
            after = snapshot_after or {}
            for rel, sig in after.items():
                if before.get(rel) == sig:
                    continue  # unchanged
                p = game_root / rel
                if not p.is_file():
                    continue
                baked.append(BakedFile(
                    rel_path=rel,
                    post_sha256=_sha256(p),
                    pre_sha256=None,
                    created=rel not in before,
                ))

        if deploy_kind == DeployKind.BAKED.value:
            state = ModState.BAKED.value
            enabled = True
        else:
            state = ModState.ENABLED.value
            enabled = True

        mod = InstalledMod(
            id=mod_id, name=name, game=(game_type or game),
            source_type=source_type, source_ref=source_ref,
            install_method=install_method, deploy_kind=deploy_kind,
            state=state, enabled=enabled, load_order=load_order,
            build_key=build_key, option_hint=option_hint, source_slug=source_slug,
            deployed_files=deployed, baked_files=baked,
            incompatibilities=parse_incompatibilities(readme_text),
        )
        manifest.mods.append(mod)
        save_manifest(manifest)
        return mod


# ---------------------------------------------------------------------------
# Enable / disable / uninstall
# ---------------------------------------------------------------------------

def disable(game: str, game_root: Path, mod_id: str) -> InstalledMod:
    with _MANIFEST_LOCK:
        manifest = load_manifest(game)
        mod = manifest.find(mod_id)
        if not mod:
            raise ModManagerError(f"Mod {mod_id} not found")
        if not mod.toggleable:
            raise ModNotToggleableError(
                f"'{mod.name}' was installed by a patcher and cannot be toggled; "
                "uninstall/reinstall the game's affected files instead."
            )
        if mod.state == ModState.DISABLED.value:
            return mod

        store = _disabled_root(game, mod_id)
        for df in mod.deployed_files:
            src = _safe_join(game_root, df.rel_path)
            if not src.exists():
                continue  # already gone (a later mod may own it)
            # Only move files we still own (hash matches).
            try:
                if _sha256(src) != df.sha256:
                    continue  # overwritten by a later mod; leave it
            except OSError:
                continue
            dst = store / df.rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

        mod.state = ModState.DISABLED.value
        mod.enabled = False
        save_manifest(manifest)
        return mod


def enable(game: str, game_root: Path, mod_id: str) -> InstalledMod:
    with _MANIFEST_LOCK:
        manifest = load_manifest(game)
        mod = manifest.find(mod_id)
        if not mod:
            raise ModManagerError(f"Mod {mod_id} not found")
        if not mod.toggleable:
            raise ModNotToggleableError(f"'{mod.name}' cannot be toggled (baked install).")
        if mod.state == ModState.ENABLED.value:
            return mod

        store = _disabled_root(game, mod_id)
        for df in mod.deployed_files:
            src = store / df.rel_path
            if not src.exists():
                continue
            dst = _safe_join(game_root, df.rel_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        # Clean up empty disabled store
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)

        mod.state = ModState.ENABLED.value
        mod.enabled = True
        save_manifest(manifest)
        return mod


def uninstall(game: str, game_root: Path, mod_id: str, *, force: bool = False) -> None:
    with _MANIFEST_LOCK:
        manifest = load_manifest(game)
        mod = manifest.find(mod_id)
        if not mod:
            raise ModManagerError(f"Mod {mod_id} not found")

        if mod.deploy_kind == DeployKind.BAKED.value and not force:
            raise ModManagerError(
                f"'{mod.name}' was installed by a patcher (TSLPatcher/HoloPatcher) "
                "and modified shared game files in place; it can't be cleanly "
                "removed. Pass force=true to drop the record (patched files "
                "remain — a clean reinstall/verify of the game is recommended)."
            )

        if mod.deploy_kind == DeployKind.LOOSE.value:
            if mod.state == ModState.DISABLED.value:
                shutil.rmtree(_disabled_root(game, mod_id), ignore_errors=True)
            else:
                for df in mod.deployed_files:
                    p = _safe_join(game_root, df.rel_path)
                    if p.exists():
                        try:
                            if _sha256(p) == df.sha256:
                                p.unlink()
                        except OSError:
                            pass
                shutil.rmtree(_disabled_root(game, mod_id), ignore_errors=True)

        shutil.rmtree(_backup_root(game, mod_id), ignore_errors=True)
        manifest.mods = [m for m in manifest.mods if m.id != mod_id]
        save_manifest(manifest)


def reorder(game: str, ordered_ids: list[str]) -> GameManifest:
    with _MANIFEST_LOCK:
        manifest = load_manifest(game)
        index = {mid: i for i, mid in enumerate(ordered_ids)}
        for m in manifest.mods:
            if m.id in index:
                m.load_order = index[m.id]
        manifest.mods.sort(key=lambda m: m.load_order)
        save_manifest(manifest)
        return manifest


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def _conflict_explanation(ctype: str, kinds: set, winner: str, losers: list[str]) -> tuple[str, str]:
    """Return (description, recommendation) explaining a file conflict in plain terms."""
    others = ", ".join(f"“{n}”" for n in losers) or "another mod"
    if kinds == {"baked"}:
        return (
            f"Two patcher mods both modify this file. TSLPatcher/HoloPatcher "
            f"usually merge their changes, so this is often fine — but review it "
            f"if you see odd behaviour.",
            "Usually safe to leave as-is; install order can still matter.",
        )
    base = {
        "2da": (
            f"Both mods ship a copy of this 2DA table. Only one file can sit in "
            f"Override, so “{winner}” wins and the changes from {others} are "
            f"overwritten and lost."
        ),
        "dialog": (
            f"Both mods provide a dialog.tlk (the game's text/string table). Only "
            f"one can be active — “{winner}” wins and {others}'s text is ignored."
        ),
        "module": (
            f"Both mods change the same module/area file. “{winner}” wins; {others} "
            f"may not work correctly."
        ),
        "override": (
            f"Both mods install a file with the same name into Override. “{winner}” "
            f"wins and the version from {others} is shadowed."
        ),
    }.get(ctype, f"“{winner}” and {others} both write the same file; one overrides the other.")
    rec = ("Decide which mod should provide this file: keep it enabled and disable "
           "the other, or set load order so the intended mod wins.")
    return base, rec


def _resource_type(rel_lower: str) -> str:
    if rel_lower.endswith("dialog.tlk"):
        return "dialog"
    if rel_lower.endswith(".2da"):
        return "2da"
    if rel_lower.endswith((".mod", ".rim", ".erf")) or rel_lower.startswith("modules/"):
        return "module"
    return "override"


def compute_conflicts(game: str) -> list[dict]:
    """
    Compute file-level conflicts across ENABLED mods. Returns UI-shaped dicts:
    {id, resource, type, severity, participants:[{mod_id,mod_name,enabled}],
     winner_mod_id}.
    """
    manifest = load_manifest(game)
    # rel_lower -> list of (load_order, mod, kind)
    owners: dict[str, list[tuple[int, InstalledMod, str]]] = {}
    display: dict[str, str] = {}

    for mod in manifest.mods:
        if not mod.enabled:
            continue
        if mod.deploy_kind == DeployKind.LOOSE.value:
            for df in mod.deployed_files:
                key = df.rel_path.lower()
                display.setdefault(key, df.rel_path)
                owners.setdefault(key, []).append((mod.load_order, mod, "loose"))
        else:
            for bf in mod.baked_files:
                key = bf.rel_path.lower()
                display.setdefault(key, bf.rel_path)
                owners.setdefault(key, []).append((mod.load_order, mod, "baked"))

    conflicts: list[dict] = []
    for key, parts in owners.items():
        distinct = {m.id for _, m, _ in parts}
        if len(distinct) < 2:
            continue
        parts_sorted = sorted(parts, key=lambda t: (t[0], t[1].install_ts))
        kinds = {k for _, _, k in parts}
        # loose-vs-loose hard overwrite = warning; all-baked merge = info; mixed = warning
        if kinds == {"baked"}:
            severity = "info"
        else:
            severity = "warning"
        winner = parts_sorted[0][1]
        seen_ids: set[str] = set()
        participants = []
        for _, m, _k in parts_sorted:
            if m.id in seen_ids:
                continue
            seen_ids.add(m.id)
            participants.append({"mod_id": m.id, "mod_name": m.name, "enabled": m.enabled})
        ctype = _resource_type(key)
        desc, rec = _conflict_explanation(ctype, kinds, winner.name,
                                          [p["mod_name"] for p in participants if p["mod_id"] != winner.id])
        conflicts.append({
            "id": key,
            "resource": display[key],
            "type": ctype,
            "severity": severity,
            "participants": participants,
            "winner_mod_id": winner.id,
            "description": desc,
            "recommendation": rec,
        })

    # ---- Declared incompatibilities (from the mods' own readmes) ----
    enabled_mods = [m for m in manifest.mods if m.enabled]
    seen_pairs: set[tuple[str, str]] = set()
    for a in enabled_mods:
        if not a.incompatibilities:
            continue
        for b in enabled_mods:
            if a.id == b.id:
                continue
            if not _name_matches(b.name, a.incompatibilities):
                continue
            pair = tuple(sorted((a.id, b.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            conflicts.append({
                "id": f"declared:{pair[0]}:{pair[1]}",
                "resource": f"{a.name}  ↔  {b.name}",
                "type": "declared",
                "severity": "error",
                "participants": [
                    {"mod_id": a.id, "mod_name": a.name, "enabled": a.enabled},
                    {"mod_id": b.id, "mod_name": b.name, "enabled": b.enabled},
                ],
                "winner_mod_id": None,
                "description": (
                    f"“{a.name}” states in its own readme that it is "
                    f"incompatible with “{b.name}”. Running both enabled can "
                    f"cause crashes, missing content, or broken scripting."
                ),
                "recommendation": "Disable one of these two mods.",
            })

    sev_rank = {"error": 0, "warning": 1, "info": 2}
    conflicts.sort(key=lambda c: (sev_rank.get(c["severity"], 3), c["resource"]))
    return conflicts


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _name_matches(name: str, keywords: list[str]) -> bool:
    """True if any declared-incompatibility keyword refers to `name`."""
    nn = _normalize(name)
    if not nn:
        return False
    for kw in keywords:
        nk = _normalize(kw)
        if len(nk) < 4:
            continue
        if nk in nn or nn in nk:
            return True
        # token overlap: most significant words shared
        ntoks = {t for t in nn.split() if len(t) > 3}
        ktoks = {t for t in nk.split() if len(t) > 3}
        if ntoks and ktoks and len(ntoks & ktoks) >= 2:
            return True
    return False


def conflict_counts_by_mod(conflicts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in conflicts:
        for p in c["participants"]:
            counts[p["mod_id"]] = counts.get(p["mod_id"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Import any local mod (archive or folder)
# ---------------------------------------------------------------------------

def detect_import(archive_or_dir: Path):
    """Extract (if needed) + detect. Returns (extracted_dir, InstallPlan)."""
    from installer.detector import detect
    from installer.extractor import extract

    p = Path(archive_or_dir)
    if p.is_file():
        extracted = extract(p)
    else:
        extracted = p
    return extracted, detect(extracted)
