"""
Scrape full detail from build pages: extract per-mod notes and
any special variant/option guidance from surrounding HTML.
"""
import re, sys, json, time
import requests
from bs4 import BeautifulSoup, NavigableString

sys.stdout.reconfigure(encoding="utf-8")
DS_RE = re.compile(r"deadlystream\.com/files/file/(\d+)-", re.I)

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0"

BUILD_URLS = {
    "k1_full":        "https://kotor.neocities.org/modding/mod_builds/k1/full",
    "k1_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
    "k2_full":        "https://kotor.neocities.org/modding/mod_builds/k2/full",
    "k2_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
}

def get_full_note(link_el) -> str:
    """Walk up to the nearest meaningful container and grab all text."""
    for ancestor in link_el.parents:
        tag = ancestor.name
        if tag in ("li", "tr"):
            return ancestor.get_text(" ", strip=True)
        if tag in ("div", "section", "article"):
            # Only use if it's a small div (not the whole page)
            text = ancestor.get_text(" ", strip=True)
            if len(text) < 1500:
                return text
    return link_el.get_text(strip=True)

def scrape_build(url, build_key):
    r = s.get(url, timeout=30)
    soup = BeautifulSoup(r.text, "lxml")
    main = soup.find("main") or soup

    results = []
    seen = set()
    order = 0
    h2 = h3 = h4 = ""

    for el in main.descendants:
        if isinstance(el, NavigableString):
            continue
        tag = getattr(el, "name", None)
        if not tag:
            continue
        if tag == "h2": h2 = el.get_text(" ", strip=True); h3 = h4 = ""
        elif tag == "h3": h3 = el.get_text(" ", strip=True); h4 = ""
        elif tag == "h4": h4 = el.get_text(" ", strip=True)
        elif tag == "a" and el.get("href"):
            m = DS_RE.search(el["href"])
            if not m or m.group(1) in seen:
                continue
            fid = m.group(1)
            seen.add(fid)
            order += 1
            note = get_full_note(el)
            # Check for any text explicitly mentioning variants, options, versions
            option_hint = ""
            note_lower = note.lower()
            if "corrections only" in note_lower:
                option_hint = "corrections_only"
            elif "pc response" in note_lower or "moderation" in note_lower:
                option_hint = "pc_response_moderation"
            elif "restoration" in note_lower and "ambush" in note_lower:
                option_hint = "check_note"
            elif "restoration" in note_lower:
                option_hint = "restoration"
            elif "ambush" in note_lower:
                option_hint = "ambush"

            name = el.get_text(strip=True)
            name = re.sub(r"https?://\S+", "", name).strip()

            results.append({
                "install_order": order,
                "file_id": fid,
                "name": name[:100],
                "h2": h2, "h3": h3, "h4": h4,
                "note": note[:600],
                "option_hint": option_hint,
                "build": build_key,
            })
    return results

all_data = {}
for key, url in BUILD_URLS.items():
    print(f"Scraping {key}...")
    all_data[key] = scrape_build(url, key)
    time.sleep(0.3)

with open("build_detail.json", "w", encoding="utf-8") as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)

# Print any mods that have option_hints or interesting notes
print("\n=== MODS WITH SPECIAL NOTES / OPTION HINTS ===")
for build, mods in all_data.items():
    for m in mods:
        if m["option_hint"] or any(kw in m["note"].lower() for kw in
                ["install", "before", "after", "first", "then", "choose", "select",
                 "version", "variant", "option", "compatible", "patch", "note"]):
            print(f"\n[{build}] #{m['install_order']:3d} [{m['file_id']}] {m['name'][:60]}")
            print(f"  hint: {m['option_hint'] or '-'}")
            print(f"  note: {m['note'][:300]}")
