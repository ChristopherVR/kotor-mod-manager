"""
Scrape all KOTOR mod build lists and analyze mod installer types
by fetching each mod's deadlystream page.
"""
import re
import sys
import json
import time
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

DS_RE = re.compile(r"https?://deadlystream\.com/files/file/(\d+)-([^\s\"'<>#/?]+)", re.I)

BUILD_PAGES = {
    "k1_full": "https://kotor.neocities.org/modding/mod_builds/k1/full",
    "k1_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
    "k2_full": "https://kotor.neocities.org/modding/mod_builds/k2/full",
    "k2_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
}

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def scrape_build_page(url: str, build_key: str) -> list[dict]:
    """Extract all mods from a build page, preserving category context."""
    print(f"\nScraping {build_key}: {url}")
    r = s.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    mods = []
    seen_ids = set()
    current_category = "Uncategorized"

    # Walk every element in order to maintain category context
    for el in soup.find_all(["h2", "h3", "h4", "a"]):
        if el.name in ("h2", "h3", "h4"):
            current_category = el.get_text(" ", strip=True)
            continue

        if el.name == "a" and el.get("href"):
            href = el["href"]
            m = DS_RE.search(href)
            if not m:
                continue
            file_id = m.group(1)
            slug = m.group(2)
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)

            # Grab surrounding context for description
            parent = el.find_parent(["li", "td", "p", "div"])
            desc = parent.get_text(" ", strip=True)[:300] if parent else ""

            name = el.get_text(strip=True) or slug.replace("-", " ").title()
            # Clean up name - remove trailing URL artifacts
            name = re.sub(r"\s*https?://.*", "", name).strip() or slug.replace("-", " ").title()

            mods.append({
                "file_id": file_id,
                "slug": slug,
                "url": f"https://deadlystream.com/files/file/{file_id}-{slug}/",
                "name": name[:100],
                "category": current_category,
                "description": desc,
                "build": build_key,
            })

    print(f"  Found {len(mods)} mods")
    return mods


def fetch_ds_page_info(mod: dict) -> dict:
    """Fetch the public deadlystream page for a mod and extract key info."""
    url = mod["url"]
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}

        text = r.text
        soup = BeautifulSoup(text, "lxml")

        # Title
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else mod["name"]
        title = re.sub(r"\s*[-|].*$", "", title).strip()

        # Description / file details body
        desc_el = soup.find("div", class_=re.compile(r"ipsType_richText|file_description|cFileDescription", re.I))
        desc_text = desc_el.get_text(" ", strip=True)[:800] if desc_el else ""

        # Category breadcrumb
        breadcrumbs = [b.get_text(strip=True) for b in soup.find_all(class_=re.compile(r"ipsBreadcrumb|breadcrumb", re.I))]
        cat = " > ".join(breadcrumbs)[:100]

        # Look for install method hints in text
        full_text = (desc_text + " " + text[:3000]).lower()
        hints = []
        if "tslpatcher" in full_text or "tslpatchdata" in full_text:
            hints.append("TSLPatcher")
        if "override" in full_text and ("copy" in full_text or "place" in full_text or "paste" in full_text):
            hints.append("Override copy")
        if "holoimagetools" in full_text or "holopatcher" in full_text:
            hints.append("HoloPatcher")
        if "kotor tool" in full_text:
            hints.append("KotOR Tool (manual)")
        if "readme" in full_text and not hints:
            hints.append("Manual (readme required)")

        # File size / type
        size_el = soup.find(string=re.compile(r"\d+(\.\d+)?\s*(KB|MB|GB)", re.I))
        file_size = size_el.strip() if size_el else "?"

        # Number of downloads
        dl_count_el = soup.find(string=re.compile(r"\d[\d,]+\s*download", re.I))
        dl_count = dl_count_el.strip() if dl_count_el else "?"

        return {
            "title": title[:100],
            "description": desc_text[:300],
            "category": cat,
            "install_hints": hints,
            "file_size": file_size,
            "dl_count": dl_count,
        }
    except Exception as e:
        return {"error": str(e)}


# ---- MAIN ----

# Step 1: Scrape all build pages
all_mods = {}  # file_id -> mod dict
build_membership = defaultdict(list)  # file_id -> [builds]

for build_key, url in BUILD_PAGES.items():
    mods = scrape_build_page(url, build_key)
    for m in mods:
        fid = m["file_id"]
        build_membership[fid].append(build_key)
        if fid not in all_mods:
            all_mods[fid] = m

print(f"\n=== TOTAL UNIQUE MODS ACROSS ALL BUILDS: {len(all_mods)} ===\n")

# Categories breakdown
cats = defaultdict(int)
for m in all_mods.values():
    cats[m["category"]] += 1

print("Top categories:")
for cat, count in sorted(cats.items(), key=lambda x: -x[1])[:20]:
    print(f"  {count:3d}  {cat}")

# Step 2: Fetch DS pages for ALL unique mods to detect install types
print(f"\n=== Fetching deadlystream pages for {len(all_mods)} mods ===")
print("(rate-limited to 1 req/sec to be polite)\n")

install_type_counts = defaultdict(int)
results = []

mods_list = list(all_mods.values())
for i, mod in enumerate(mods_list):
    info = fetch_ds_page_info(mod)
    mod.update(info)
    mod["builds"] = build_membership[mod["file_id"]]

    hints = info.get("install_hints", [])
    if not hints:
        hints = ["Unknown/Override"]
    for h in hints:
        install_type_counts[h] += 1

    results.append(mod)
    print(f"  [{i+1:3d}/{len(mods_list)}] {mod['file_id']:5s} | {', '.join(hints) or 'Unknown':30s} | {info.get('title', mod['name'])[:50]}")

    time.sleep(0.8)  # polite rate limit

# Step 3: Summary
print("\n\n=== INSTALL TYPE SUMMARY ===")
for itype, count in sorted(install_type_counts.items(), key=lambda x: -x[1]):
    print(f"  {count:3d}  {itype}")

# Save results
with open("mod_analysis.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nFull results saved to mod_analysis.json")
print(f"\nMods requiring special handling:")
for m in results:
    hints = m.get("install_hints", [])
    if hints and hints != ["Override copy"] and hints != ["Unknown/Override"]:
        print(f"  [{m['file_id']}] {m.get('title', m['name'])[:60]}")
        print(f"       -> {', '.join(hints)}")
