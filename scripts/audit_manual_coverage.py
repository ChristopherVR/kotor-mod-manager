"""
Audit which mods in the build guides would still land in MANUAL install mode.

We can't run the actual file detector (no downloaded archives), but we can:
  1. Check each mod's install_method hint from the build page
  2. Parse the directives and inspect what the installer can now act on
  3. Flag anything where the instructions contain patterns we DON'T yet handle

Run:  python scripts/audit_manual_coverage.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from installer.build_directives import parse_directives, Directives

DATA = Path("scripts/build_instructions.json")

# Install method hints that the detector maps to MANUAL
KNOWN_MANUAL_HINTS = {"manual", "unknown"}

# Hints we can now handle (after all recent improvements)
HANDLED_HINTS = {
    "tslpatcher", "tsl patcher", "holopatcher", "holo patcher",
    "override", "override copy", "direct copy", "file copy",
    "tlk", "dialog", "movie",
    "game patcher", "standalone patcher",
    # "multiple" and "multi" mean multiple sub-mods, handled by MULTIPLE
    "multiple", "multi",
}

# Keywords in install_method hint that still mean MANUAL
def hint_is_manual(hint: str) -> bool:
    if not hint:
        return False
    hl = hint.lower().strip()
    if any(t in hl for t in HANDLED_HINTS):
        return False
    if any(t in hl for t in ("manual", "run", "execute", "custom")):
        return True
    return False

# Patterns in instructions that we now handle
_NOW_HANDLED_PATTERNS = [
    # multi_run_options - now automated
    re.compile(r"run\s+(?:the\s+)?(?:patcher|installer).{0,80}?(?:once|twice|\d+\s+times|multiple times)", re.I),
    # rename_copies - now automated
    re.compile(r"(?:make|create)\s+a\s+copy|rename\s+(?:it|this|that|the\s+file)", re.I),
    # post_install_delete - now automated
    re.compile(r"delete.{0,100}from\s+(?:the\s+)?override", re.I),
    # compat patches - now automated
    re.compile(r"compat.{0,50}patch|apply.{0,50}compatibility", re.I),
    # GAME_PATCHER - now automated
    re.compile(r"\bpatcher\.exe\b|\bfog.{0,20}fix\b|\b3c.{0,5}fd\b", re.I),
]

# Patterns that STILL need manual action
_STILL_MANUAL_PATTERNS = [
    # Cross-mod extraction (HQ Skyboxes K2 special case)
    (re.compile(r"extract.{0,100}from.{0,100}another mod", re.I),
     "cross-mod extraction"),
    # Hex editing
    (re.compile(r"hex\s+edit", re.I),
     "hex editing"),
    # Registry/exe patching that's not a standalone patcher
    (re.compile(r"edit.{0,30}\.ini\b.{0,80}manually", re.I),
     "manual INI editing"),
    # Very specific manual steps with no automation path
    (re.compile(r"you\s+must\s+manually|manually\s+copy|manually\s+move|manually\s+install", re.I),
     "explicit manual copy"),
    # "do not download" means something tricky
    (re.compile(r"do\s+not\s+download", re.I),
     "conditional download"),
    # No download link (manual source)
    (re.compile(r"(?:no\s+)?download\s+link\s+(?:available|provided|listed)", re.I),
     "no download link"),
]

def analyse_mod(mod: dict) -> dict:
    method_hint = (mod.get("install_method") or "").lower().strip()
    instructions = mod.get("instructions") or ""
    warnings = mod.get("warnings") or ""
    name = mod.get("name", "?")
    build = mod.get("build", "?")

    dirs: Directives = parse_directives(instructions, warnings, method_hint)

    issues = []

    # 1. Check if install_method hint itself is MANUAL
    if hint_is_manual(method_hint):
        issues.append(f"install_method hint: '{method_hint}'")

    # 2. Check for patterns we STILL can't handle
    full_text = f"{instructions} {warnings}"
    for pattern, label in _STILL_MANUAL_PATTERNS:
        if not pattern.search(full_text):
            continue
        # Skip patterns already handled by parsed directives
        if label == "conditional download" and (dirs.download_ignore or dirs.download_only):
            continue
        issues.append(label)

    # 3. Check for patterns we CAN now handle but that used to be manual
    now_handled = []
    for p in _NOW_HANDLED_PATTERNS:
        if p.search(full_text):
            now_handled.append(True)

    return {
        "name": name,
        "build": build,
        "file_id": mod.get("ds_links", [{}])[0].get("file_id") if mod.get("ds_links") else mod.get("file_id", "?"),
        "section": mod.get("section") or mod.get("subsection") or "",
        "method_hint": method_hint,
        "has_manual_notes": bool(dirs.manual_notes),
        "manual_notes": dirs.manual_notes[:2],
        "issues": issues,
        "directives_summary": dirs.summary(),
    }

def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))

    # Deduplicate by file_id - same mod appears in multiple builds
    seen: dict[str, dict] = {}
    for build_key, mods in data.items():
        for mod in mods:
            links = mod.get("ds_links", [])
            fid = links[0].get("file_id") if links else mod.get("file_id", "")
            key = f"{fid}_{mod.get('name','')}"
            if key not in seen:
                mod["build"] = build_key
                seen[key] = mod

    all_mods = list(seen.values())
    results = [analyse_mod(m) for m in all_mods]

    # Separate into buckets
    still_manual = [r for r in results if r["issues"]]
    has_directives = [r for r in results if r["directives_summary"]]
    has_manual_notes = [r for r in results if r["has_manual_notes"]]
    clean = [r for r in results if not r["issues"] and not r["has_manual_notes"]]

    print(f"\n{'='*72}")
    print(f"  KOTOR MOD BUILD - COVERAGE AUDIT")
    print(f"{'='*72}")
    print(f"  Total unique mods:        {len(all_mods)}")
    print(f"  Fully handled:            {len(clean)}")
    print(f"  Has automated directives: {len(has_directives)}")
    print(f"  Has manual_notes warning: {len(has_manual_notes)}")
    print(f"  Still needs manual step:  {len(still_manual)}")
    print(f"{'='*72}\n")

    # Group still-manual by issue type
    by_issue: dict[str, list] = defaultdict(list)
    for r in still_manual:
        for issue in r["issues"]:
            by_issue[issue].append(r)

    print("REMAINING MANUAL CASES BY REASON:")
    print("-"*72)
    for issue_label, mods in sorted(by_issue.items(), key=lambda x: -len(x[1])):
        print(f"\n  [{len(mods)}] {issue_label}")
        for r in mods[:15]:
            note = f"  ({r['directives_summary']})" if r["directives_summary"] else ""
            print(f"      - [{r['file_id']}] {r['name'][:55]}{note}")
        if len(mods) > 15:
            print(f"      ... and {len(mods)-15} more")

    print()
    print("MODS WITH MANUAL_NOTES (player warnings logged but still automated):")
    print("-"*72)
    for r in has_manual_notes[:30]:
        print(f"  [{r['file_id']}] {r['name'][:55]}")
        for note in r["manual_notes"]:
            print(f"      NOTE: {note[:120]}")

    if len(has_manual_notes) > 30:
        print(f"  ... and {len(has_manual_notes)-30} more")

    print()
    print("AUTOMATED DIRECTIVE COVERAGE (sample - mods with non-trivial directives):")
    print("-"*72)
    for r in sorted(has_directives, key=lambda x: x["directives_summary"])[:40]:
        print(f"  [{r['file_id']}] {r['name'][:45]:<45}  {r['directives_summary']}")

    # Also output a machine-readable summary
    out = {
        "total": len(all_mods),
        "clean": len(clean),
        "still_manual": [{"file_id": r["file_id"], "name": r["name"], "issues": r["issues"]} for r in still_manual],
    }
    import sys
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
