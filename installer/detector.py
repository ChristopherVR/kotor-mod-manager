"""Detect the installation method required for an extracted KOTOR mod."""

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class InstallMethod(Enum):
    TSLPATCHER    = auto()   # tslpatchdata/ + TSLPatcher.exe
    HOLOPATCHER   = auto()   # tslpatchdata/ + HoloPatcher.exe (supports namespaces.ini)
    TLK_REPLACE   = auto()   # Contains dialog.tlk → copy to game root
    OVERRIDE_COPY = auto()   # Has Override/ folder → copy contents
    DIRECT_COPY   = auto()   # Loose KOTOR files → copy to Override/
    MULTI_VARIANT = auto()   # Sub-folders each with a variant (user must pick one)
    MULTIPLE      = auto()   # Multiple distinct sub-mods, each needs its own install
    MANUAL        = auto()   # Unknown — show readme to user


OVERRIDE_EXTENSIONS = {
    ".utc", ".uti", ".utd", ".utp", ".uts", ".utt", ".utn", ".utw",
    ".dlg", ".2da", ".nss", ".ncs", ".tga", ".tpc", ".mdl", ".mdx",
    ".wav", ".mp3", ".bik", ".lip", ".gui", ".are", ".git", ".ifo",
    ".mod", ".jrl", ".itp", ".lyt", ".vis", ".txi", ".pth", ".gff",
    ".bic", ".fac", ".ptt",
}

MODULE_EXTENSIONS = {".mod", ".sav", ".rim", ".erf"}
MOVIE_EXTENSIONS  = {".bik", ".avi", ".mpg"}


@dataclass
class NamespaceOption:
    key: str
    name: str
    description: str
    ini_path: Path


@dataclass
class ModFileMapping:
    source: Path
    dest_relative: str  # relative to game root


@dataclass
class InstallPlan:
    method: InstallMethod
    mod_root: Path
    tslpatcher_exe: "Path | None" = None
    holopatcher_exe: "Path | None" = None
    tslpatcher_ini: "Path | None" = None
    namespaces: list[NamespaceOption] = field(default_factory=list)
    file_mappings: list[ModFileMapping] = field(default_factory=list)
    tlk_variants: list[tuple[str, Path]] = field(default_factory=list)  # (label, dialog.tlk path)
    readme_text: str = ""
    warnings: list[str] = field(default_factory=list)
    sub_plans: list["InstallPlan"] = field(default_factory=list)


def _find_file(root: Path, name: str) -> "Path | None":
    name_lower = name.lower()
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower() == name_lower:
            return p
    return None


def _find_dir(root: Path, name: str) -> "Path | None":
    name_lower = name.lower()
    for p in root.rglob("*"):
        if p.is_dir() and p.name.lower() == name_lower:
            return p
    return None


def _read_readme(root: Path) -> str:
    readme_names = [
        "readme.txt", "readme.md", "readme.rtf", "readme.html",
        "install.txt", "installation.txt", "instructions.txt",
        "read me.txt", "read_me.txt",
    ]
    for name in readme_names:
        match = _find_file(root, name)
        if match:
            try:
                return match.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    return ""


def _parse_namespaces(namespaces_ini: Path) -> list[NamespaceOption]:
    """Parse HoloPatcher's namespaces.ini to get install options."""
    try:
        text = namespaces_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Find [Namespaces] section
    ns_section = re.search(r"\[Namespaces\](.*?)(?=\[|$)", text, re.S)
    if not ns_section:
        return []

    ns_keys = re.findall(r"^\s*Namespace\d+\s*=\s*(\S+)", ns_section.group(1), re.M | re.I)
    options = []
    for key in ns_keys:
        section = re.search(rf"\[{re.escape(key)}\](.*?)(?=\[|$)", text, re.S)
        if not section:
            continue
        body = section.group(1)
        ini_name  = re.search(r"^\s*IniName\s*=\s*(.+)$",   body, re.M | re.I)
        data_path = re.search(r"^\s*DataPath\s*=\s*(.*)$",   body, re.M | re.I)
        name      = re.search(r"^\s*Name\s*=\s*(.+)$",       body, re.M | re.I)
        desc      = re.search(r"^\s*Description\s*=\s*(.+)$", body, re.M | re.I)

        # IniName defaults to changes.ini; DataPath may be empty (= tslpatchdata root)
        ini_file = ini_name.group(1).strip() if ini_name else "changes.ini"
        sub_path = data_path.group(1).strip() if data_path else ""
        ini_path = namespaces_ini.parent / sub_path / ini_file
        options.append(NamespaceOption(
            key=key,
            name=(name.group(1).strip() if name else key),
            description=(desc.group(1).strip()[:200] if desc else ""),
            ini_path=ini_path,
        ))
    return options


def _collect_loose_files(root: Path) -> list[ModFileMapping]:
    mappings = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        ext = p.suffix.lower()
        # Skip files inside tslpatchdata or backup folders
        parts_lower = [x.lower() for x in p.relative_to(root).parts]
        if "tslpatchdata" in parts_lower or "backup" in parts_lower:
            continue

        if ext in MODULE_EXTENSIONS:
            mappings.append(ModFileMapping(source=p, dest_relative=f"Modules/{p.name}"))
        elif ext in MOVIE_EXTENSIONS:
            mappings.append(ModFileMapping(source=p, dest_relative=f"Movies/{p.name}"))
        elif ext in OVERRIDE_EXTENSIONS:
            mappings.append(ModFileMapping(source=p, dest_relative=f"Override/{p.name}"))
    return mappings


def _find_holopatcher(root: Path) -> "Path | None":
    for p in root.rglob("*.exe"):
        if "holopatcher" in p.name.lower() or "holocron" in p.name.lower():
            return p
    return None


def _tslpatcher_exe_names() -> set:
    """Known patcher exe names (current + legacy), sourced from config."""
    try:
        from installer.config_loader import legacy_tslpatcher_exe_names
        return {n.lower() for n in legacy_tslpatcher_exe_names()}
    except Exception:
        return {"tslpatcher.exe", "patcher.exe", "installer.exe"}


def _find_tslpatcher(root: Path) -> "Path | None":
    names = _tslpatcher_exe_names()
    # Exact name match is most reliable
    for p in root.rglob("*.exe"):
        if p.name.lower() in names:
            return p
    # Heuristic fallback for oddly-named patchers that still ship tslpatchdata
    for p in root.rglob("*.exe"):
        low = p.name.lower()
        if "patch" in low or "install" in low or "modder" in low:
            # Avoid uninstallers / unrelated tools
            if "uninstall" not in low:
                return p
    return None


def _find_tlk_variants(root: Path) -> list[tuple[str, Path]]:
    """Find dialog.tlk files. Returns (label, path) pairs."""
    variants = []
    for p in root.rglob("dialog.tlk"):
        # Label = parent folder name, or "Default" if at root
        label = p.parent.name if p.parent != root else "Default"
        variants.append((label, p))
    return variants


def _plan_for_root(mod_root: Path) -> InstallPlan:
    readme = _read_readme(mod_root)

    # 1. HoloPatcher (must check before TSLPatcher since it also has tslpatchdata/)
    holopatcher_exe = _find_holopatcher(mod_root)
    if holopatcher_exe:
        tslpatchdata = _find_dir(mod_root, "tslpatchdata")
        namespaces_ini = None
        namespaces: list[NamespaceOption] = []
        if tslpatchdata:
            candidate = tslpatchdata / "namespaces.ini"
            if candidate.exists():
                namespaces_ini = candidate
                namespaces = _parse_namespaces(candidate)
        changes_ini = _find_file(mod_root, "changes.ini") if not namespaces else None
        return InstallPlan(
            method=InstallMethod.HOLOPATCHER,
            mod_root=mod_root,
            holopatcher_exe=holopatcher_exe,
            tslpatcher_ini=changes_ini,
            namespaces=namespaces,
            readme_text=readme,
        )

    # 2. TSLPatcher (handled headlessly via the HoloPatcher shim cascade — the
    #    mod's own .exe is optional; tslpatchdata + an ini is enough).
    tslpatcher_data = _find_dir(mod_root, "tslpatchdata")
    tslpatcher_exe  = _find_tslpatcher(mod_root)
    if tslpatcher_data and (
        tslpatcher_exe
        or (tslpatcher_data / "changes.ini").exists()
        or (tslpatcher_data / "namespaces.ini").exists()
    ):
        changes_ini = tslpatcher_data / "changes.ini"
        namespaces_ini = tslpatcher_data / "namespaces.ini"
        namespaces: list[NamespaceOption] = []
        if namespaces_ini.exists():
            namespaces = _parse_namespaces(namespaces_ini)
        return InstallPlan(
            method=InstallMethod.TSLPATCHER,
            mod_root=mod_root,
            tslpatcher_exe=tslpatcher_exe,
            tslpatcher_ini=changes_ini if changes_ini.exists() else None,
            namespaces=namespaces,
            readme_text=readme,
        )

    # 3. dialog.tlk replacement
    tlk_variants = _find_tlk_variants(mod_root)
    if tlk_variants:
        return InstallPlan(
            method=InstallMethod.TLK_REPLACE,
            mod_root=mod_root,
            tlk_variants=tlk_variants,
            readme_text=readme,
        )

    # 4. Override folder present
    override_dir = _find_dir(mod_root, "override")
    if override_dir:
        mappings = []
        for p in override_dir.rglob("*"):
            if p.is_file():
                mappings.append(ModFileMapping(
                    source=p,
                    dest_relative=f"Override/{p.name}",
                ))
        # Also check for Modules/, Movies/ siblings
        modules_dir = _find_dir(mod_root, "modules")
        if modules_dir:
            for p in modules_dir.rglob("*"):
                if p.is_file():
                    mappings.append(ModFileMapping(source=p, dest_relative=f"Modules/{p.name}"))
        return InstallPlan(
            method=InstallMethod.OVERRIDE_COPY,
            mod_root=mod_root,
            file_mappings=mappings,
            readme_text=readme,
        )

    # 5. Loose KOTOR files in the root
    mappings = _collect_loose_files(mod_root)
    if mappings:
        return InstallPlan(
            method=InstallMethod.DIRECT_COPY,
            mod_root=mod_root,
            file_mappings=mappings,
            readme_text=readme,
        )

    return InstallPlan(
        method=InstallMethod.MANUAL,
        mod_root=mod_root,
        readme_text=readme,
        warnings=["Could not determine installation method automatically."],
    )


def detect(extracted_dir: Path) -> InstallPlan:
    """Analyse an extracted mod directory and return an install plan."""
    plan = _plan_for_root(extracted_dir)
    if plan.method != InstallMethod.MANUAL:
        return plan

    # Sub-folders might each be a variant or separate sub-mod
    sub_dirs = [d for d in extracted_dir.iterdir() if d.is_dir()
                and d.name.lower() not in ("__macosx", ".ds_store", "backup")]

    if not sub_dirs:
        return plan

    # Check if this looks like a multi-variant (same type of content in each sub-dir)
    # e.g. Dialogue Fixes with "Corrections only/" and "PC Response Moderation version/"
    all_contain_tlk = all(_find_tlk_variants(d) for d in sub_dirs)
    if all_contain_tlk and len(sub_dirs) > 1:
        # Each sub-folder is a variant of the same mod — user picks one
        all_variants = []
        for d in sub_dirs:
            for label, path in _find_tlk_variants(d):
                all_variants.append((d.name, path))
        return InstallPlan(
            method=InstallMethod.MULTI_VARIANT,
            mod_root=extracted_dir,
            tlk_variants=all_variants,
            readme_text=_read_readme(extracted_dir),
        )

    # Each sub-folder is a distinct sub-mod
    sub_plans = []
    for sub in sub_dirs:
        sp = _plan_for_root(sub)
        sub_plans.append(sp)

    if any(sp.method != InstallMethod.MANUAL for sp in sub_plans):
        return InstallPlan(
            method=InstallMethod.MULTIPLE,
            mod_root=extracted_dir,
            sub_plans=sub_plans,
            readme_text=_read_readme(extracted_dir),
        )

    return plan
