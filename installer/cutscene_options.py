"""Choose cutscene alternatives before any movie or texture is installed.

The Rescaled packs contain multiple files with the same destination. Flattening
every folder lets filesystem order choose the subtitle/legal-screen style.
Use the actual archive folders as choices rather than guessing their names.
"""
from collections import defaultdict
from pathlib import Path

from installer.detector import InstallMethod, InstallPlan, _collect_loose_files


def _choose_alternatives(root, mappings, ask):
    by_dest = defaultdict(list)
    for mapping in mappings:
        by_dest[mapping.dest_relative.lower()].append(mapping)
    # Files that offer the same folders form one choice (e.g. all six subtitled
    # movies), so the player does not answer once per movie.
    groups = defaultdict(list)
    for dest, candidates in sorted(by_dest.items()):
        if len(candidates) > 1:
            folders = tuple(sorted({m.source.parent for m in candidates}, key=str))
            groups[folders].append(dest)
    selected = dict(by_dest)
    for folders, destinations in groups.items():
        labels = [p.relative_to(root).as_posix() if p != root else "Default"
                  for p in folders]
        body = ("These folders contain alternative versions of the same files. "
                "Choose one style; it will apply to all files in this group.\n\n"
                + ", ".join(Path(d).name for d in destinations[:6]))
        answer = ask("Cutscene style", body, [*labels, "skip"])
        if answer not in labels:
            return None
        folder = folders[labels.index(answer)]
        for dest in destinations:
            selected[dest] = [m for m in by_dest[dest] if m.source.parent == folder]
    return [m for candidates in selected.values() for m in candidates]


def prepare_cutscenes(payloads, ask):
    """payloads: (extracted root, is mods add-on) pairs. None means skip.

    Add-on folders are opt-in: a build can omit TSLRCM, Extended Enclave or
    M4-78, so copying every supported mod's movies would be incorrect.
    """
    if not payloads or all(addon for _, addon in payloads):
        raise ValueError("The main cutscene pack is missing; an add-on cannot be installed on its own.")
    chosen = []
    for root, addon in payloads:
        mappings = [m for m in _collect_loose_files(root)
                    if m.dest_relative.startswith(("Movies/", "Override/"))]
        if not mappings:
            raise ValueError(f"No cutscene files found in {root.name}.")
        if not addon:
            selected = _choose_alternatives(root, mappings, ask)
            if selected is None:
                return None
            chosen.extend(selected)
            continue
        # Remove shared archive wrapper directories to reveal the actual
        # optional mod folders, without hardcoding a particular release layout.
        base = root
        while all(m.source.parent != base for m in mappings):
            first = {m.source.relative_to(base).parts[0] for m in mappings}
            if len(first) != 1:
                break
            child = base / next(iter(first))
            # A lone component is still a mod choice; retain its label.
            if any(m.source.parent == child for m in mappings):
                break
            base = child
        components = defaultdict(list)
        for mapping in mappings:
            rel = mapping.source.relative_to(base)
            components[rel.parts[0] if len(rel.parts) > 1 else "Additional cutscenes"].append(mapping)
        for label, files in sorted(components.items()):
            answer = ask(f"Cutscenes for {label}",
                         "Use these replacement cutscenes only if you installed the "
                         f"corresponding mod ({label}). Your main movie pack is kept either way.",
                         ["Install these cutscenes", "Leave these out", "skip"])
            if answer == "Leave these out":
                continue
            if answer != "Install these cutscenes":
                return None
            selected = _choose_alternatives(base, files, ask)
            if selected is None:
                return None
            chosen.extend(selected)
    # Explicitly selected mod replacements override the main movie pack.
    by_dest = {m.dest_relative.lower(): m for m in chosen}
    return InstallPlan(InstallMethod.DIRECT_COPY, payloads[0][0],
                       file_mappings=list(by_dest.values()))
