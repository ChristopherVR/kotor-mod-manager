"""
Scrape the KOTOR build pages to extract installation order and structure.
Dumps the full ordered mod list with section/tier context.
"""
import re
import sys
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString

sys.stdout.reconfigure(encoding="utf-8")

DS_RE = re.compile(r"https?://deadlystream\.com/files/file/(\d+)-([^\s\"'<>#/?]+)", re.I)

BUILD_PAGES = {
    "k1_full":        "https://kotor.neocities.org/modding/mod_builds/k1/full",
    "k1_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
    "k2_full":        "https://kotor.neocities.org/modding/mod_builds/k2/full",
    "k2_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
}

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0"


def scrape_ordered(url: str, build_key: str) -> list[dict]:
    print(f"\nScraping {build_key}...")
    r = s.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    mods = []
    seen_ids = set()
    install_order = 0

    # Walk the DOM in order, tracking headings for section/tier context
    h1 = ""
    h2 = ""
    h3 = ""
    h4 = ""

    # Find the main content area
    main = soup.find("main") or soup.find("div", class_=re.compile(r"main|content|copy", re.I)) or soup

    def walk(node):
        nonlocal h1, h2, h3, h4, install_order

        for child in node.children:
            if isinstance(child, NavigableString):
                continue

            tag = child.name
            if not tag:
                continue

            if tag == "h1":
                h1 = child.get_text(" ", strip=True)
                h2 = h3 = h4 = ""
            elif tag == "h2":
                h2 = child.get_text(" ", strip=True)
                h3 = h4 = ""
            elif tag == "h3":
                h3 = child.get_text(" ", strip=True)
                h4 = ""
            elif tag == "h4":
                h4 = child.get_text(" ", strip=True)
            elif tag == "a" and child.get("href"):
                href = child["href"]
                m = DS_RE.search(href)
                if m:
                    file_id = m.group(1)
                    slug = m.group(2)
                    if file_id not in seen_ids:
                        seen_ids.add(file_id)
                        install_order += 1
                        name = child.get_text(strip=True)
                        name = re.sub(r"https?://\S+", "", name).strip() or slug.replace("-", " ").title()

                        # Gather surrounding note text from parent container
                        parent = child.find_parent(["li", "tr", "p", "div"])
                        note = ""
                        if parent:
                            full_text = parent.get_text(" ", strip=True)
                            # Strip the link text itself
                            note = full_text.replace(name, "").strip()[:200]

                        mods.append({
                            "install_order": install_order,
                            "file_id": file_id,
                            "slug": slug,
                            "url": f"https://deadlystream.com/files/file/{file_id}-{slug}/",
                            "name": name[:100],
                            "section_h1": h1,
                            "section_h2": h2,
                            "section_h3": h3,
                            "section_h4": h4,
                            "note": note,
                            "build": build_key,
                        })

            # Recurse into containers (but not scripts/styles)
            if tag not in ("script", "style", "head"):
                walk(child)

    walk(main)
    print(f"  Found {len(mods)} mods in install order")
    return mods


# Scrape all 4 builds
all_builds = {}
for build_key, url in BUILD_PAGES.items():
    mods = scrape_ordered(url, build_key)
    all_builds[build_key] = mods
    time.sleep(0.5)

# Save full ordered data
out_path = Path("ordered_mods.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_builds, f, indent=2, ensure_ascii=False)

print(f"\nSaved to {out_path}")

# Print K1 Full build order as a sample
print("\n=== K1 FULL BUILD - INSTALLATION ORDER ===")
for m in all_builds["k1_full"]:
    sec = " > ".join(filter(None, [m["section_h2"], m["section_h3"], m["section_h4"]]))
    print(f"  {m['install_order']:3d}. [{m['file_id']:5s}] {m['name'][:55]:<55s}  ({sec[:60]})")
