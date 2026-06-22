"""One-off audit: pull the FULL structured per-mod instructions from the
kotor.neocities.org build pages so we can see what nuance/dependency text the
current scraper is dropping. Writes build_instructions.json next to it.
"""
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

DS = re.compile(r"deadlystream\.com/files/file/(\d+)-([^\s\"'<>#/?]+)", re.I)
BUILD_URLS = {
    "k1_full": "https://kotor.neocities.org/modding/mod_builds/k1/full",
    "k1_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
    "k2_full": "https://kotor.neocities.org/modding/mod_builds/k2/full",
    "k2_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
}

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0"

LABELS = ["author", "description", "category & tier", "category", "tier",
          "non-english functionality", "installation method", "mod notes",
          "compatibility", "warning"]


def is_name_p(el):
    if getattr(el, "name", None) != "p":
        return False
    txt = el.get_text(" ", strip=True).lower()
    return el.find("strong") is not None and txt.startswith("name:")


def scrape(url, build_key):
    r = s.get(url, timeout=30)
    soup = BeautifulSoup(r.text, "lxml")
    main = soup.find("main") or soup

    # Build a flat ordered list of name-blocks.
    name_ps = [p for p in main.find_all("p") if is_name_p(p)]
    out = []
    for order, p in enumerate(name_ps, 1):
        # Collect sibling elements until the next name block or a heading.
        block_els = [p]
        sib = p.next_sibling
        while sib is not None:
            if getattr(sib, "name", None):
                if is_name_p(sib) or sib.name in ("h2", "h3", "h4"):
                    break
                block_els.append(sib)
            sib = sib.next_sibling

        # Section/category from the most recent preceding headings.
        h2 = h3 = ""
        prev = p.find_previous(["h2", "h3"])
        # Walk back to capture both h2 and h3 context.
        h2el = p.find_previous("h2")
        h3el = p.find_previous("h3")
        h2 = h2el.get_text(" ", strip=True) if h2el else ""
        h3 = h3el.get_text(" ", strip=True) if h3el else ""

        ds_links, other_links, fields, instructions, warnings = [], [], {}, [], []
        for el in block_els:
            for a in el.find_all("a", href=True) if hasattr(el, "find_all") else []:
                m = DS.search(a["href"])
                anchor = a.get_text(" ", strip=True)
                if m:
                    ds_links.append({"file_id": m.group(1), "slug": m.group(2),
                                     "anchor": anchor, "href": a["href"]})
                else:
                    other_links.append({"anchor": anchor, "href": a["href"]})
            # Labeled field paragraphs (Author:, Description:, etc.)
            if getattr(el, "name", None) == "p":
                strong = el.find("strong")
                txt = el.get_text(" ", strip=True)
                if strong:
                    label = strong.get_text(" ", strip=True).rstrip(":").strip().lower()
                    if label in LABELS:
                        val = txt.split(":", 1)[1].strip() if ":" in txt else txt
                        fields[label] = val
            # Instruction / warning divs (and any div with a heading-ish lead).
            if getattr(el, "name", None) in ("div", "blockquote"):
                t = el.get_text(" ", strip=True)
                low = t.lower()
                if "installation instruction" in low:
                    instructions.append(t)
                elif "warning" in low or "note" in low[:30]:
                    warnings.append(t)
                elif t:
                    instructions.append(t)

        name = ""
        # Prefer the first DS anchor that looks like a name, else the Name: text.
        name_txt = p.get_text(" ", strip=True)
        name = re.sub(r"^name:\s*", "", name_txt, flags=re.I).strip()

        out.append({
            "install_order": order,
            "build": build_key,
            "name": name[:120],
            "section": h2,
            "subsection": h3,
            "ds_links": ds_links,
            "other_links": other_links,
            "author": fields.get("author", ""),
            "description": fields.get("description", ""),
            "category_tier": fields.get("category & tier", fields.get("category", "")),
            "non_english": fields.get("non-english functionality", ""),
            "install_method": fields.get("installation method", ""),
            "instructions": " ".join(instructions)[:2000],
            "warnings": " ".join(warnings)[:1500],
        })
    return out


def main():
    data = {}
    for key, url in BUILD_URLS.items():
        print("scraping", key, file=sys.stderr)
        data[key] = scrape(url, key)
        time.sleep(0.4)
    with open("scripts/build_instructions.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    for k, v in data.items():
        print(k, len(v), "mods", file=sys.stderr)


if __name__ == "__main__":
    main()
