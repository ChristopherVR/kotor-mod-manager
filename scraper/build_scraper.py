"""
Scrape ordered mod lists from kotor.neocities.org build pages.
Returns mods in their recommended installation order with variant hints.
"""
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup, NavigableString

DS_RE = re.compile(r"deadlystream\.com/files/file/(\d+)-([^\s\"'<>#/?]+)", re.I)

BUILD_URLS = {
    "k1_full":        "https://kotor.neocities.org/modding/mod_builds/k1/full",
    "k1_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free",
    "k2_full":        "https://kotor.neocities.org/modding/mod_builds/k2/full",
    "k2_spoilerfree": "https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free",
}

BUILD_GAME = {
    "k1_full": "KOTOR1",
    "k1_spoilerfree": "KOTOR1",
    "k2_full": "KOTOR2",
    "k2_spoilerfree": "KOTOR2",
}


@dataclass
class BuildMod:
    install_order: int
    file_id: str
    slug: str
    name: str
    url: str
    game: str             # "KOTOR1" or "KOTOR2"
    section: str          # h2 section heading
    category: str         # h3/h4 category
    note: str             # surrounding text from build page
    option_hint: str      # e.g. "pc_response_moderation", "restoration"
    install_method_hint: str  # e.g. "loose", "tslpatcher", "holopatcher" (from page text)
    build_key: str

    @property
    def ds_url(self) -> str:
        return f"https://deadlystream.com/files/file/{self.file_id}-{self.slug}/"


def _extract_option_hint(note: str) -> str:
    t = note.lower()
    if "pc response moderation" in t or "moderation version" in t:
        return "pc_response_moderation"
    if "corrections only" in t:
        return "corrections_only"
    if "restoration" in t and "ambush" in t:
        return "restoration"   # default to restoration when both mentioned
    if "restoration" in t:
        return "restoration"
    if "ambush" in t:
        return "ambush"
    return ""


def _extract_install_method_hint(note: str) -> str:
    t = note.lower()
    if "holopatcher" in t:
        return "holopatcher"
    if "tslpatcher" in t:
        return "tslpatcher"
    if "loose-file" in t or "loose file" in t:
        return "loose"
    return ""


def scrape_build(build_key: str, session: Optional[requests.Session] = None) -> list[BuildMod]:
    url = BUILD_URLS[build_key]
    game = BUILD_GAME[build_key]
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0")

    r = s.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    main = soup.find("main") or soup

    mods: list[BuildMod] = []
    seen: set[str] = set()
    order = 0
    h2 = h3 = h4 = ""

    for el in main.descendants:
        if isinstance(el, NavigableString):
            continue
        tag = getattr(el, "name", None)
        if not tag:
            continue

        if tag == "h2":
            h2 = el.get_text(" ", strip=True)
            h3 = h4 = ""
        elif tag == "h3":
            h3 = el.get_text(" ", strip=True)
            h4 = ""
        elif tag == "h4":
            h4 = el.get_text(" ", strip=True)
        elif tag == "a" and el.get("href"):
            m = DS_RE.search(el["href"])
            if not m:
                continue
            fid, slug = m.group(1), m.group(2)
            if fid in seen:
                continue
            seen.add(fid)
            order += 1

            # Grab note from nearest container
            note = ""
            for ancestor in el.parents:
                atag = getattr(ancestor, "name", None)
                if atag in ("li", "tr"):
                    note = ancestor.get_text(" ", strip=True)
                    break
                if atag in ("div", "section"):
                    candidate = ancestor.get_text(" ", strip=True)
                    if len(candidate) < 2000:
                        note = candidate
                        break

            name = el.get_text(strip=True)
            name = re.sub(r"https?://\S+", "", name).strip() or slug.replace("-", " ").title()

            category = h4 or h3 or ""
            section = h2

            mods.append(BuildMod(
                install_order=order,
                file_id=fid,
                slug=slug,
                name=name[:120],
                url=f"https://deadlystream.com/files/file/{fid}-{slug}/",
                game=game,
                section=section,
                category=category,
                note=note[:600],
                option_hint=_extract_option_hint(note),
                install_method_hint=_extract_install_method_hint(note),
                build_key=build_key,
            ))

    return mods


def scrape_all_builds(session: Optional[requests.Session] = None) -> dict[str, list[BuildMod]]:
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0")
    result = {}
    for key in BUILD_URLS:
        result[key] = scrape_build(key, s)
        time.sleep(0.3)
    return result
