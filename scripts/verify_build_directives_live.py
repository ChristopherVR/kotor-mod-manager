"""
Opt-in live check: download a few build mods from DeadlyStream and confirm the
new build-guide handling makes the right call on real mod contents.

    KMI_VERIFY=1 python scripts/verify_build_directives_live.py

Needs a saved DeadlyStream login (the app's keyring entry). It downloads into a
temp dir and only inspects decisions (which namespace/which files) - it does not
write into any game folder.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scraper import build_scraper as bs
from scraper.deadlystream import DeadlyStreamClient, download_name_matches
from installer.extractor import extract
from installer.detector import detect, InstallMethod
from installer.build_directives import match_option_index, select_paths

if not os.environ.get("KMI_VERIFY"):
    print("Set KMI_VERIFY=1 to run the live verification (needs DeadlyStream login).")
    sys.exit(0)

client = DeadlyStreamClient()
client.ensure_logged_in()
print("Logged in to DeadlyStream.\n")

tmp = Path(tempfile.mkdtemp(prefix="kmi_verify_"))
mods = {m.file_id: m for m in bs.scrape_build("k1_full")}
fails = 0


def _extract_all(file_id, slug, keep_names=None):
    archives = client.download_all_files(file_id, tmp / file_id, slug=slug,
                                         keep_names=keep_names)
    roots = []
    for a in archives:
        try:
            roots.append(extract(a))
        except Exception as e:
            print(f"    (extract failed for {a.name}: {e})")
    return archives, roots


def check_namespace(file_id, expect_substr):
    global fails
    mod = mods[file_id]
    print(f"[{file_id}] {mod.name}")
    print(f"    directive summary: {mod.directives.summary() or '(none)'}")
    _, roots = _extract_all(file_id, mod.slug)
    plan = None
    for r in roots:
        p = detect(r)
        if p.namespaces:
            plan = p
            break
        plan = plan or p
    if not plan or not plan.namespaces:
        print(f"    SKIP: no namespaces found (method={plan.method.name if plan else '?'})\n")
        return
    names = [f"{ns.name} {ns.description}" for ns in plan.namespaces]
    idx = match_option_index(names, mod.directives, mod.option_hint)
    chosen = plan.namespaces[idx if idx is not None else 0].name
    print(f"    options: {[ns.name for ns in plan.namespaces]}")
    print(f"    chosen : {chosen!r} (index {idx})")
    ok = idx is not None and expect_substr.lower() in chosen.lower()
    print(("    PASS" if ok else "    FAIL") + f": expected an option containing '{expect_substr}'\n")
    fails += 0 if ok else 1


def check_selection(file_id, expect_excluded):
    global fails
    mod = mods[file_id]
    print(f"[{file_id}] {mod.name}")
    print(f"    directive summary: {mod.directives.summary() or '(none)'}")
    _, roots = _extract_all(file_id, mod.slug)
    all_rels = []
    for r in roots:
        plan = detect(r)
        for m in plan.file_mappings:
            try:
                all_rels.append(str(m.source.relative_to(plan.mod_root)).replace("\\", "/"))
            except ValueError:
                all_rels.append(m.source.name)
    kept, dropped = select_paths(all_rels, mod.directives)
    dropped_l = [d.lower() for d in dropped]
    print(f"    files: {len(all_rels)} total, kept {len(kept)}, dropped {len(dropped)}")
    ok = all(any(exc.lower() in d for d in dropped_l) for exc in expect_excluded) and bool(kept)
    for exc in expect_excluded:
        hit = any(exc.lower() in d for d in dropped_l)
        print(f"      {'dropped' if hit else 'NOT dropped'}: {exc}")
    print(("    PASS" if ok else "    FAIL") + "\n")
    fails += 0 if ok else 1


def check_download_only(file_id, expect_name):
    global fails
    mod = mods[file_id]
    print(f"[{file_id}] {mod.name}")
    print(f"    download_only directive: {mod.directives.download_only}")
    total = len(client.list_download_records(mod.file_id, mod.slug))
    # Real download path: header-level filtering keeps only the named file.
    paths = client.download_all_files(
        mod.file_id, tmp / f"dl_{file_id}", slug=mod.slug,
        keep_names=mod.directives.download_only)
    got = [p.name for p in paths]
    print(f"    submission has {total} file(s); downloaded {len(got)}: {got}")
    ok = bool(mod.directives.download_only) and len(got) == 1 \
        and expect_name.lower() in got[0].lower()
    print(("    PASS" if ok else "    FAIL") + f": expected only '{expect_name}'\n")
    fails += 0 if ok else 1


print("=== Namespace selection (real namespaces.ini) ===")
check_namespace("1293", "compat")     # Korriban: Back in Black -> Community Patch Compatible
check_namespace("1090", "ambush")     # Senni Vek -> Ambush (the recommended one)

print("=== Selective file copy ===")
check_selection("1333", ["n_sithcomm.mdl", "n_sithcomm.mdx"])  # JC's Minor Fixes

print("=== Download-only ===")
check_download_only("982", "hd_twilek_female")  # HD Twi'lek Females

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("=" * 50)
print("ALL LIVE CHECKS PASSED" if fails == 0 else f"{fails} LIVE CHECK(S) FAILED")
sys.exit(1 if fails else 0)
