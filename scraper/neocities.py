"""Scrape KOTOR mod lists from neocities-style mod guide pages."""

import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

DEADLYSTREAM_FILE_RE = re.compile(
    r"https?://deadlystream\.com/files/file/(\d+)-([^/?#\"'\s]+)", re.IGNORECASE
)
DEADLYSTREAM_ID_RE = re.compile(r"/files/file/(\d+)-")


@dataclass
class ModEntry:
    name: str
    url: str
    file_id: str
    description: str = ""
    category: str = ""
    game: str = ""  # "KOTOR1", "KOTOR2", or "both"
    source_page: str = ""
    tags: list = field(default_factory=list)


def _guess_game(text: str) -> str:
    t = text.lower()
    has_k1 = any(w in t for w in ["kotor 1", "kotor1", "knights of the old republic 1", "k1 "])
    has_k2 = any(w in t for w in ["kotor 2", "kotor2", "knights of the old republic 2", "k2 ", "tsl", "the sith lords"])
    if has_k1 and has_k2:
        return "both"
    if has_k2:
        return "KOTOR2"
    if has_k1:
        return "KOTOR1"
    return ""


def _extract_links_from_page(html: str, page_url: str) -> list[ModEntry]:
    soup = BeautifulSoup(html, "lxml")
    mods: dict[str, ModEntry] = {}

    page_game = _guess_game(soup.get_text())

    for a in soup.find_all("a", href=True):
        href = a["href"]
        match = DEADLYSTREAM_FILE_RE.search(href)
        if not match:
            # Try relative or partial
            if "deadlystream.com/files/file/" in href:
                id_match = DEADLYSTREAM_ID_RE.search(href)
                if id_match:
                    file_id = id_match.group(1)
                    full_url = "https://deadlystream.com/files/file/" + href.split("/files/file/")[-1].rstrip("/")
                else:
                    continue
            else:
                continue
        else:
            file_id = match.group(1)
            full_url = match.group(0)
            if not full_url.startswith("http"):
                full_url = "https://" + full_url

        # Clean URL to canonical form
        canonical = re.sub(r"\?.*", "", full_url).rstrip("/")

        if file_id in mods:
            continue

        # Try to find a name - use link text, or nearby heading
        name = a.get_text(strip=True)
        if not name or name.lower().startswith("http"):
            # Walk up to find a better label
            parent = a.find_parent(["li", "td", "div", "p"])
            if parent:
                name = parent.get_text(" ", strip=True)[:80]

        if not name:
            name = f"Mod #{file_id}"

        # Grab description from surrounding paragraph or list item
        description = ""
        container = a.find_parent(["li", "tr", "div", "p"])
        if container:
            description = container.get_text(" ", strip=True)[:300]

        # Infer category from nearest heading
        category = ""
        heading = None
        for el in reversed(list(a.parents)):
            prev = el.find_previous_sibling(re.compile("^h[1-6]$"))
            if prev:
                heading = prev.get_text(strip=True)
                break
        if heading:
            category = heading

        game = _guess_game(description + " " + category) or page_game

        mods[file_id] = ModEntry(
            name=name,
            url=canonical,
            file_id=file_id,
            description=description,
            category=category,
            game=game,
            source_page=page_url,
        )

    return list(mods.values())


def scrape_page(url: str, session: Optional[requests.Session] = None) -> list[ModEntry]:
    """Fetch a neocities mod guide page and extract all deadlystream mod links."""
    s = session or requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (KOTOR-Mod-Installer)"
    resp = s.get(url, timeout=30)
    resp.raise_for_status()
    return _extract_links_from_page(resp.text, url)


def scrape_multiple(urls: list[str], session: Optional[requests.Session] = None) -> list[ModEntry]:
    """Scrape multiple pages and deduplicate by file_id."""
    s = session or requests.Session()
    seen_ids: set[str] = set()
    results: list[ModEntry] = []
    for url in urls:
        try:
            entries = scrape_page(url, s)
            for e in entries:
                if e.file_id not in seen_ids:
                    seen_ids.add(e.file_id)
                    results.append(e)
        except Exception as exc:
            print(f"[scraper] Failed to scrape {url}: {exc}")
    return results
