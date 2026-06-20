"""
Download one representative mod from each installer type and unpack it.
Reads DeadlyStream credentials from Windows Credential Manager (keyring).
"""
import re
import sys
import json
import time
import zipfile
from pathlib import Path

import keyring
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

# One representative per install type (file_id, slug, label, expected_type)
SAMPLES = [
    ("1313",  "kotor-dialogue-fixes",                "Dialogue_Fixes",      "Override"),
    ("491",   "kotor-high-quality-starfields-and-nebulas", "HQ_Starfields",  "Override"),
    ("1487",  "k1-saber-throw-knockdown-effect",     "Saber_Throw",         "TSLPatcher"),
    ("2321",  "minor-music-tweaks",                  "Minor_Music",         "TSLPatcher"),
    ("2729",  "k1-k2-swoops-to-k1",                 "K2_Swoops",           "HoloPatcher"),
    ("2785",  "kebla-yurt-renovation",               "Kebla_Yurt",          "HoloPatcher"),
    ("1090",  "senni-vek-mod",                       "Senni_Vek",           "HoloPatcher"),
    ("824",   "ajunta-pall-unique-appearance",       "Ajunta_Pall",         "Manual"),
]

DEST = Path("D:/Development/kotor-mod-installer/mod_samples")
DEST.mkdir(exist_ok=True)
DS_BASE = "https://deadlystream.com"

s = requests.Session()
s.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_csrf(html: str, soup: BeautifulSoup) -> str | None:
    # Try JSON embedded key
    m = re.search(r'"csrfKey"\s*:\s*"([a-f0-9]+)"', html, re.I)
    if m:
        return m.group(1)
    # Try data attribute
    m = re.search(r'data-csrfkey="([a-f0-9]+)"', html, re.I)
    if m:
        return m.group(1)
    # Try hidden input
    inp = soup.find("input", {"name": "csrfKey"})
    if inp and inp.get("value"):
        return inp["value"]
    # Try meta tag
    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]
    # Try any a tag with csrfKey in href
    for a in soup.find_all("a", href=True):
        m = re.search(r"csrfKey=([a-f0-9]+)", a["href"])
        if m:
            return m.group(1)
    return None


# ---- Login ----
SERVICE = "kotor_mod_installer_ds"
DS_USER = keyring.get_password(SERVICE, "__last_user__") or ""
DS_PASS = keyring.get_password(SERVICE, DS_USER) if DS_USER else ""
logged_in = False

if DS_USER and DS_PASS:
    print(f"Logging in as {DS_USER}...")
    login_r = s.get(f"{DS_BASE}/login/", timeout=20)
    login_soup = BeautifulSoup(login_r.text, "lxml")
    csrf_val = get_csrf(login_r.text, login_soup)

    if not csrf_val:
        # Dump a snippet to debug
        print("  CSRF not found on login page. Snippet:")
        print(login_r.text[:2000])
    else:
        print(f"  CSRF: {csrf_val[:12]}...")
        auth_r = s.post(f"{DS_BASE}/login/", data={
            "_processLogin": "usernamepassword",
            "auth": DS_USER,
            "password": DS_PASS,
            "csrfKey": csrf_val,
            "remember_me": "1",
        }, timeout=20, allow_redirects=True)

        if "sign_out" in auth_r.text.lower() or "logout" in auth_r.text.lower():
            logged_in = True
            print("  Logged in!")
        else:
            # Check cookies
            for c in s.cookies:
                if "member" in c.name.lower():
                    logged_in = True
                    break
            if logged_in:
                print("  Logged in (via cookie check)!")
            else:
                print("  Login may have failed. Checking response snippet:")
                print(auth_r.text[:500])
else:
    print("No credentials in keyring — proceeding without login.")


def download_mod(file_id: str, slug: str, label: str) -> Path | None:
    mod_dir = DEST / f"{file_id}_{label}"
    mod_dir.mkdir(exist_ok=True)

    page_url = f"{DS_BASE}/files/file/{file_id}-{slug}/"
    print(f"  Fetching page: {page_url}")
    r = s.get(page_url, timeout=20)
    if r.status_code != 200:
        print(f"  Page failed: HTTP {r.status_code}")
        return None

    soup = BeautifulSoup(r.text, "lxml")
    csrf_val = get_csrf(r.text, soup)
    if not csrf_val:
        print("  No CSRF found on file page")
        return None

    dl_url = f"{DS_BASE}/files/file/{file_id}-{slug}/?do=download&csrfKey={csrf_val}"
    print(f"  Downloading...")
    r2 = s.get(dl_url, stream=True, timeout=120, allow_redirects=True)

    if r2.status_code in (403, 401):
        print(f"  Access denied — login required")
        return None
    if r2.status_code != 200:
        print(f"  Download failed: HTTP {r2.status_code}")
        return None

    cd = r2.headers.get("Content-Disposition", "")
    fn_m = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)["\']?', cd)
    filename = fn_m.group(1).strip().strip("\"'") if fn_m else f"mod_{file_id}.zip"
    dest_file = mod_dir / filename
    total = int(r2.headers.get("Content-Length", 0))
    downloaded = 0

    with open(dest_file, "wb") as f:
        for chunk in r2.iter_content(65536):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)

    size_kb = downloaded // 1024
    print(f"  Saved: {filename} ({size_kb} KB)")
    return dest_file


def unpack(archive: Path) -> Path | None:
    out_dir = archive.parent / archive.stem
    suffix = archive.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(out_dir)
        elif suffix == ".7z":
            import py7zr
            with py7zr.SevenZipFile(archive) as z:
                z.extractall(out_dir)
        elif suffix == ".rar":
            import rarfile
            with rarfile.RarFile(archive) as z:
                z.extractall(out_dir)
        else:
            # Try zip fallback
            try:
                with zipfile.ZipFile(archive) as z:
                    z.extractall(out_dir)
            except Exception:
                out_dir = archive.parent
        return out_dir
    except Exception as e:
        print(f"  Unpack error: {e}")
        return None


def analyze(directory: Path) -> dict:
    override_exts = {
        ".utc", ".uti", ".utd", ".utp", ".uts", ".utt", ".dlg", ".2da",
        ".nss", ".ncs", ".tga", ".tpc", ".mdl", ".mdx", ".wav", ".mp3",
        ".lip", ".gui", ".are", ".git", ".ifo", ".mod", ".jrl", ".lyt",
        ".vis", ".txi", ".gff", ".bic",
    }
    info = {
        "has_tslpatchdata": False,
        "has_tslpatcher_exe": False,
        "has_holopatcher": False,
        "has_override_folder": False,
        "loose_override_files": [],
        "exe_files": [],
        "readme_files": [],
        "ini_files": [],
        "other_dirs": [],
        "total_files": 0,
        "all_top_level": [],
    }

    for p in directory.rglob("*"):
        rel = p.relative_to(directory)
        parts = rel.parts
        name_lower = p.name.lower()
        rel_lower = str(rel).lower().replace("\\", "/")

        if p.is_dir():
            if name_lower == "override":
                info["has_override_folder"] = True
            elif name_lower == "tslpatchdata":
                info["has_tslpatchdata"] = True
            if len(parts) == 1:
                info["all_top_level"].append(f"[DIR] {p.name}")
            continue

        info["total_files"] += 1
        if len(parts) == 1:
            info["all_top_level"].append(p.name)

        if name_lower == "tslpatcher.exe":
            info["has_tslpatcher_exe"] = True
        if "holopatcher" in name_lower or "holocron" in name_lower:
            info["has_holopatcher"] = True
        if p.suffix.lower() == ".exe":
            info["exe_files"].append(str(rel))
        if name_lower.startswith("readme") or name_lower.startswith("install") or name_lower == "read me.txt":
            info["readme_files"].append(str(rel))
        if name_lower.endswith(".ini"):
            info["ini_files"].append(str(rel))

        # Loose override files (not inside tslpatchdata or override dir)
        if (p.suffix.lower() in override_exts
                and "tslpatchdata" not in rel_lower
                and "/override/" not in "/" + rel_lower):
            info["loose_override_files"].append(str(rel))

    return info


# ---- Main ----
all_results = {}

for file_id, slug, label, expected in SAMPLES:
    print(f"\n{'='*60}")
    print(f"[{file_id}] {label} (expected: {expected})")

    archive = download_mod(file_id, slug, label)
    if not archive:
        all_results[file_id] = {"label": label, "expected": expected, "status": "download_failed"}
        time.sleep(2)
        continue

    extracted = unpack(archive)
    if not extracted or not extracted.exists():
        all_results[file_id] = {"label": label, "expected": expected, "status": "unpack_failed"}
        time.sleep(1)
        continue

    structure = analyze(extracted)
    all_results[file_id] = {"label": label, "expected": expected, "status": "ok", **structure}

    print(f"  Top-level contents: {structure['all_top_level']}")
    print(f"  tslpatchdata folder: {structure['has_tslpatchdata']}")
    print(f"  tslpatcher.exe:      {structure['has_tslpatcher_exe']}")
    print(f"  HoloPatcher:         {structure['has_holopatcher']}")
    print(f"  Override folder:     {structure['has_override_folder']}")
    print(f"  Loose override files:{len(structure['loose_override_files'])}")
    print(f"  EXE files:           {structure['exe_files']}")
    print(f"  INI files:           {structure['ini_files']}")
    print(f"  README files:        {structure['readme_files']}")
    print(f"  Total files:         {structure['total_files']}")

    time.sleep(1)

with open("sample_results.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

print(f"\n\nAll results saved to sample_results.json")
print("\n=== SUMMARY ===")
for fid, res in all_results.items():
    status = res.get("status", "?")
    if status != "ok":
        print(f"  [{fid}] {res['label']:30s} FAILED: {status}")
        continue
    detected = []
    if res.get("has_tslpatchdata") or res.get("has_tslpatcher_exe"):
        detected.append("TSLPatcher")
    if res.get("has_holopatcher"):
        detected.append("HoloPatcher")
    if res.get("has_override_folder"):
        detected.append("Override-folder")
    if res.get("loose_override_files"):
        detected.append(f"Loose({len(res['loose_override_files'])})")
    if not detected:
        detected.append("Unknown/Manual")
    print(f"  [{fid}] {res['label']:30s} expected={res['expected']:12s} detected={', '.join(detected)}")
