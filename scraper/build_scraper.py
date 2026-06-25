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
    # Full structured detail parsed from the build page's per-mod block. The
    # build guide puts the real, often critical, install nuance here (which
    # patcher option to pick, which files to copy, multi-run steps, required
    # patches) - see installer/build_directives.py for how it's acted on.
    instructions: str = ""    # "Installation Instructions" / "Download Instructions" text
    warnings: str = ""        # "Usage Warning" / "Known Bugs" / "Compatibility Warning" text
    install_method: str = ""  # the page's "Installation Method:" line (free text)
    description: str = ""      # the page's "Description:" line
    author: str = ""

    @property
    def ds_url(self) -> str:
        return f"https://deadlystream.com/files/file/{self.file_id}-{self.slug}/"

    @property
    def directives(self):
        """Parsed, actionable install directives from the page text (lazy)."""
        from installer.build_directives import parse_directives
        return parse_directives(self.instructions, self.warnings, self.install_method)


# Anchor text that is NOT a mod name (download links, mirrors, etc.)
_GENERIC_LINK_TEXT = {
    "download", "download here", "here", "link", "this", "this one", "mirror",
    "click here", "get it here", "dl", "file", "page", "mod", "read more",
    "deadlystream", "nexus", "nexusmods", "source", "official",
}


def _slug_to_name(slug: str) -> str:
    return re.sub(r"\s+", " ", slug.replace("-", " ").replace("_", " ")).strip().title()


def _clean_mod_name(el, slug: str) -> str:
    """
    Derive a reliable mod name. The anchor text is preferred, but many build
    pages use generic link text ("Download", "here") or wrap the name in a
    nearby heading/bold - fall back to those, then to the slug.
    """
    raw = el.get_text(" ", strip=True)
    raw = re.sub(r"https?://\S+", "", raw).strip()
    norm = raw.lower().strip(" :–-•|")

    def usable(s: str) -> bool:
        n = s.lower().strip(" :–-•|")
        return bool(n) and len(n) >= 3 and n not in _GENERIC_LINK_TEXT and not n.isdigit()

    if usable(raw):
        return raw[:120]

    # Look for a nearby strong/b/heading inside the same list item / row.
    for ancestor in el.parents:
        atag = getattr(ancestor, "name", None)
        if atag in ("li", "tr", "p", "td", "div"):
            for cand in ancestor.find_all(["strong", "b", "h3", "h4", "h5"]):
                txt = cand.get_text(" ", strip=True)
                if usable(txt):
                    return txt[:120]
            # The leading text of the container before the link often is the name.
            lead = ancestor.get_text(" ", strip=True)
            lead = re.split(r"\b(download|here|mirror|link)\b", lead, 1, flags=re.I)[0].strip(" :–-•|")
            if usable(lead) and len(lead) <= 90:
                return lead[:120]
            break

    return _slug_to_name(slug)[:120]


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


# Labels used in the build pages' per-mod blocks (a <p> like
# "<strong>Author:</strong> ...").
_FIELD_LABELS = {
    "author": "author",
    "description": "description",
    "category & tier": "category_tier",
    "category": "category_tier",
    "non-english functionality": "non_english",
    "installation method": "install_method",
}


def _is_name_p(el) -> bool:
    """A '<p><strong>Name:</strong> ...</p>' block anchor."""
    if getattr(el, "name", None) != "p":
        return False
    if not el.find("strong"):
        return False
    return el.get_text(" ", strip=True).lower().startswith("name:")


def _gather_block(link_el) -> dict:
    """
    Collect the full per-mod block around a DeadlyStream link and pull out the
    labelled fields (Author/Description/Installation Method) plus the free-text
    Installation Instructions and Warning/Known-Bugs sections.

    The build pages format each mod as a 'Name:' paragraph followed by sibling
    paragraphs/divs; the old scraper only saw the link's own paragraph, dropping
    every instruction. We only walk forward when the anchor really is a 'Name:'
    block so prose links (e.g. the intro Amazon fix) don't swallow neighbours.
    """
    anchor = None
    for anc in link_el.parents:
        if getattr(anc, "name", None) == "p":
            anchor = anc
            break
    if anchor is None:
        anchor = link_el.find_parent(["li", "div", "td", "tr"]) or link_el

    els = [anchor]
    if _is_name_p(anchor):
        sib = anchor.next_sibling
        while sib is not None:
            if getattr(sib, "name", None):
                if _is_name_p(sib) or sib.name in ("h2", "h3", "h4"):
                    break
                els.append(sib)
            sib = sib.next_sibling

    fields: dict[str, str] = {}
    instructions: list[str] = []
    warnings: list[str] = []
    for el in els:
        name = getattr(el, "name", None)
        if name == "p":
            strong = el.find("strong")
            if strong:
                label = strong.get_text(" ", strip=True).rstrip(":").strip().lower()
                key = _FIELD_LABELS.get(label)
                if key:
                    txt = el.get_text(" ", strip=True)
                    val = txt.split(":", 1)[1].strip() if ":" in txt else txt
                    fields[key] = val
        if name in ("div", "blockquote", "aside"):
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            low = t.lower()
            if "instruction" in low[:40]:
                instructions.append(t)
            elif any(w in low[:40] for w in ("warning", "known bug", "note", "caution")):
                warnings.append(t)
            else:
                instructions.append(t)

    full = " ".join(e.get_text(" ", strip=True) for e in els if getattr(e, "name", None))
    return {
        "author": fields.get("author", ""),
        "description": fields.get("description", ""),
        "install_method": fields.get("install_method", ""),
        "instructions": " ".join(instructions).strip(),
        "warnings": " ".join(warnings).strip(),
        "note": full,
    }


def scrape_build(build_key: str, session: Optional[requests.Session] = None,
                 url: Optional[str] = None, game: Optional[str] = None) -> list[BuildMod]:
    # url/game are supplied for user-added custom builds; built-in builds resolve
    # from the BUILD_URLS / BUILD_GAME tables.
    url = url or BUILD_URLS[build_key]
    game = game or BUILD_GAME.get(build_key, "KOTOR1")
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

            # Pull the full per-mod block: labelled fields + the actual
            # Installation Instructions / Warning sections the guide relies on.
            block = _gather_block(el)
            instructions = block["instructions"]
            warnings = block["warnings"]
            # Hints are derived from the real instructions, not just the name.
            hint_source = " ".join([instructions, warnings, block["note"]])

            name = _clean_mod_name(el, slug)

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
                note=block["note"][:800],
                option_hint=_extract_option_hint(hint_source),
                install_method_hint=_extract_install_method_hint(
                    block["install_method"] or hint_source),
                build_key=build_key,
                instructions=instructions[:2500],
                warnings=warnings[:1500],
                install_method=block["install_method"][:200],
                description=block["description"][:600],
                author=block["author"][:120],
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
