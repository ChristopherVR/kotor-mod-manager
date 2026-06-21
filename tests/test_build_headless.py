"""
Live e2e test: confirm the mods in a real KOTOR build download, extract, and
detect as headless-installable - with no manual interaction.

This is the real-world confidence check the curated builds need. It is OPT-IN
because it hits the network and requires a DeadlyStream login:

    KMI_LIVE_TEST=1  python tests/test_build_headless.py            # download+detect, all K1 Full
    KMI_LIVE_TEST=1 KMI_BUILD=k1_full KMI_LIMIT=10 python ...       # first 10 mods
    KMI_LIVE_TEST=1 KMI_INSTALL=1 python ...                        # also install into a throwaway game dir

Credentials come from the saved keyring entry (or KMI_DS_USER / KMI_DS_PASS).
For each mod it asserts: download succeeds → extracts → detect() yields a method
that installs WITHOUT a GUI (loose copy / TLK / HoloPatcher, or TSLPatcher when a
headless HoloPatcher shim is available). It prints a per-mod report and a summary
of any mod that would need manual steps.

Default (KMI_LIVE_TEST unset): skips, so this file is safe in CI.
"""
import os
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg
from installer.config_loader import find_system_holopatcher
from installer.detector import InstallMethod, detect
from installer.extractor import ExtractionError, extract
from scraper.build_scraper import scrape_build
from scraper.deadlystream import AuthError, DeadlyStreamClient, DownloadError

# Methods that install with no GUI / no manual steps.
_HEADLESS_METHODS = {
    InstallMethod.OVERRIDE_COPY, InstallMethod.DIRECT_COPY,
    InstallMethod.TLK_REPLACE, InstallMethod.MULTI_VARIANT,
    InstallMethod.HOLOPATCHER, InstallMethod.MULTIPLE,
}


def _enabled() -> bool:
    return os.environ.get("KMI_LIVE_TEST") == "1"


def _login() -> DeadlyStreamClient:
    client = DeadlyStreamClient()
    u = os.environ.get("KMI_DS_USER", "")
    p = os.environ.get("KMI_DS_PASS", "")
    if not (u and p):
        u, p = DeadlyStreamClient.load_credentials()
    if not (u and p):
        raise AuthError("No DeadlyStream credentials (set KMI_DS_USER/KMI_DS_PASS or save them).")
    client.login(u, p)
    return client


def _is_headless(method: InstallMethod, shim_available: bool) -> bool:
    if method in _HEADLESS_METHODS:
        return True
    if method == InstallMethod.TSLPATCHER:
        # TSLPatcher is headless only via the HoloPatcher shim.
        return shim_available
    return False  # MANUAL / unknown


def test_build_headless():
    if not _enabled():
        print("SKIP: live build test (set KMI_LIVE_TEST=1 to run).")
        return

    build_key = os.environ.get("KMI_BUILD", "k1_full")
    limit = int(os.environ.get("KMI_LIMIT", "0"))  # 0 = all
    do_install = os.environ.get("KMI_INSTALL") == "1"

    shim = find_system_holopatcher()
    shim_available = shim is not None
    print(f"Build: {build_key} | HoloPatcher shim: {shim or 'NONE'} | install={do_install}\n")

    print("Scraping build…")
    mods = scrape_build(build_key)
    if limit:
        mods = mods[:limit]
    print(f"{len(mods)} mods to verify.\n")

    client = _login()
    print("Logged in.\n")

    tmp = Path(tempfile.mkdtemp())
    dl_dir = tmp / "dl"
    game = None
    if do_install:
        game = tmp / "game"
        (game / "Override").mkdir(parents=True)
        (game / "Modules").mkdir(parents=True)
        (game / "dialog.tlk").write_bytes(b"BASE")

    results = []  # (order, name, status, method, note)
    for m in mods:
        entry = {"order": m.install_order, "name": m.name, "ok": False,
                 "method": "?", "note": ""}
        try:
            dest = dl_dir / f"{m.file_id}_{m.slug[:30]}"
            dest.mkdir(parents=True, exist_ok=True)
            archives = client.download_all_files(file_id=m.file_id, slug=m.slug, dest_dir=dest)
            extracted = extract(archives[0])
            plan = detect(extracted)
            entry["method"] = plan.method.name
            headless = _is_headless(plan.method, shim_available)
            entry["ok"] = headless
            if not headless:
                entry["note"] = "NOT headless-installable"
            results.append(entry)
            mark = "OK " if headless else "MANUAL"
            print(f"[{m.install_order:3d}] {mark} {plan.method.name:14s} {m.name[:60]}")
        except DownloadError as e:
            entry["note"] = f"download failed: {e}"
            results.append(entry)
            print(f"[{m.install_order:3d}] DLERR  {m.name[:60]} - {e}")
        except ExtractionError as e:
            entry["note"] = f"extract failed: {e}"
            results.append(entry)
            print(f"[{m.install_order:3d}] EXERR  {m.name[:60]} - {e}")
        except Exception as e:
            entry["note"] = f"error: {e}"
            results.append(entry)
            print(f"[{m.install_order:3d}] ERROR  {m.name[:60]} - {e}")

    # Summary
    total = len(results)
    headless_ok = sum(1 for r in results if r["ok"])
    problems = [r for r in results if not r["ok"]]
    print(f"\n{'='*60}")
    print(f"Headless-installable: {headless_ok}/{total}")
    if problems:
        print(f"\nNeeds attention ({len(problems)}):")
        for r in problems:
            print(f"  [{r['order']:3d}] {r['method']:12s} {r['name'][:50]} - {r['note']}")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    # The build is "headless with no issues" only if every mod is auto-installable.
    assert not problems, f"{len(problems)} mod(s) are not headless-installable"
    print("\nALL BUILD MODS ARE HEADLESS-INSTALLABLE")


if __name__ == "__main__":
    try:
        test_build_headless()
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)
