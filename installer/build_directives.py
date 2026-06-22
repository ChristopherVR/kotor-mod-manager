"""
Turn the build guide's free-text per-mod instructions into structured,
actionable install directives.

The kotor.neocities.org build pages carry a lot of nuance in prose: which
TSLPatcher option to pick, which files to copy, which download to grab, whether
a patch must run first, and so on (see scripts/dump_build_instructions.py for
the raw audit). This module parses that prose into a small, conservative set of
directives the installer can act on.

Design rule: only emit a directive when the text is explicit enough to act on
safely. When in doubt we emit nothing, and the installer keeps its existing
behaviour (install the default option / copy everything). Acting wrongly could
break someone's game, so silence beats a guess.
"""

import re
from dataclasses import dataclass, field

# Tokens that identify a "compatible with the community patch" install option.
# The builds ALWAYS install the K1 Community Patch / TSLRCM first, so whenever a
# later mod offers a compatible option, that is the one to pick.
_COMPAT_TOKENS = ["community patch", "k1cp", "tslrcm", "k2cp", "compatib"]

# Phrases that introduce a recommended / required option choice.
_RECO_RE = re.compile(
    r"\b(?:i (?:personally )?recommend(?:ed)?(?: using)?|"
    r"recommend(?:ed)?|select|choose|use|install|apply)\b"
    r"\s+(?:the\s+|using\s+|one of\s+|your\s+)?"
    r"[\"“‘']?([A-Za-z0-9][\w '.’/&+-]{2,60}?)[\"”’']?"
    r"\s+(?:install(?:ation)?|option|version|variant|patch|folder)\b",
    re.I,
)

# "... instead" marks the NON-recommended alternative; we must not prefer it.
_INSTEAD_RE = re.compile(r"\binstead\b", re.I)

# Filenames with a KOTOR-ish extension, e.g. N_AdmrlSaulKar.mdl, p_visasbb.tpc,
# forcecage_updated_1.1.0.zip (dotted version segments are kept whole).
_FILENAME_RE = re.compile(
    r"\b([\w\-]+(?:\.[\w\-]+)*\.(?:mdl|mdx|tpc|tga|dds|2da|gui|txi|utc|uti|utp|"
    r"uts|utt|dlg|ncs|nss|mod|rim|erf|wav|mp3|bik|lip|tlk|jpg|png|rar|7z|zip))\b",
    re.I,
)


def _is_real_filename(fn: str) -> bool:
    """Reject pure-numeric stems (version-number artifacts like '0.zip')."""
    stem = fn.rsplit(".", 1)[0]
    return not stem.replace(".", "").isdigit()

# Quoted phrases (folder names, file labels) - both straight and curly quotes.
_QUOTED_RE = re.compile(r"[\"“‘']([^\"”’']{2,60})[\"”’']")

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

# Generic words that must never drive namespace selection on their own.
_PREF_STOPWORDS = {
    "only", "main", "file", "files", "this", "that", "mods", "mod", "content",
    "contents", "resolution", "installer", "patcher", "tslpatcher", "holopatcher",
    "compatches", "against", "using", "from the", "files from the", "non-english",
    "a non-english mod", "the same", "your preference", "preference",
}


@dataclass
class Directives:
    # Ordered keywords for choosing a TSLPatcher/HoloPatcher namespace. The
    # installer tries each against the mod's real option names; first hit wins.
    namespace_preferences: list[str] = field(default_factory=list)
    # Whether the mod offers a community-patch-compatible option we should take.
    prefer_compatible: bool = False
    # Download record name substrings to keep; empty means "take all".
    download_only: list[str] = field(default_factory=list)
    # Download record name substrings to skip.
    download_ignore: list[str] = field(default_factory=list)
    # Loose-file selection: keep only files matching these substrings ...
    file_only: list[str] = field(default_factory=list)
    # ... and/or drop files matching these (explicit names / folders).
    file_except: list[str] = field(default_factory=list)
    # The bundled patch component must be applied BEFORE the main mod.
    patch_first: bool = False
    # A bundled/linked patch must be installed for the mod to work correctly.
    requires_patch: bool = False
    # Mod needs the patcher run more than once (compatibility / optional parts).
    multi_run: bool = False
    # Free-text cautions we surface to the user but cannot fully automate.
    manual_notes: list[str] = field(default_factory=list)
    raw: str = ""

    def is_empty(self) -> bool:
        return not any([
            self.namespace_preferences, self.prefer_compatible,
            self.download_only, self.download_ignore,
            self.file_only, self.file_except,
            self.patch_first, self.requires_patch, self.multi_run,
            self.manual_notes,
        ])

    def summary(self) -> str:
        """A short, player-readable note about the special handling applied."""
        bits: list[str] = []
        if self.prefer_compatible:
            bits.append("picks the community-patch-compatible option")
        elif self.namespace_preferences:
            bits.append(f"picks the '{self.namespace_preferences[0]}' option")
        if self.download_only:
            bits.append("downloads only the recommended file")
        if self.file_only or self.file_except:
            bits.append("copies only the recommended files")
        if self.patch_first:
            bits.append("applies the patch first")
        if self.requires_patch:
            bits.append("installs the required patch")
        if self.multi_run:
            bits.append("runs the patcher more than once")
        return "; ".join(bits)


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        s = s.strip()
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _parse_namespace(text: str, dirs: Directives) -> None:
    low = text.lower()
    # 1. Community-patch-compatible option (deterministic for these builds).
    if re.search(r"compatib\w*\s+(install|installation|option|patch)", low) or \
       re.search(r"(community patch|k1cp|tslrcm|k2cp)[ -]?compatible", low):
        dirs.prefer_compatible = True
        dirs.namespace_preferences.extend(
            ["community patch", "tslrcm", "k1cp", "k2cp", "compatible"]
        )

    # 2. Explicit recommendation, clause by clause so a rejected alternative in
    #    the same sentence ("...recommend Ambush, but choose Restoration instead")
    #    doesn't suppress the recommendation.
    clauses: list[str] = []
    for sent in _split_sentences(text):
        clauses.extend(re.split(r";|,?\s+but\s+|\s+however\s+|,\s+whereas\s+",
                                sent, flags=re.I))
    for sent in clauses:
        if _INSTEAD_RE.search(sent):
            # This clause names the rejected alternative - skip it.
            continue
        for m in _RECO_RE.finditer(sent):
            opt = m.group(1).strip(" '\"‘’“”.")
            # Reject filler captures (articles, stopwords, and the trailing
            # keywords themselves so "use the patch" doesn't yield "the").
            if len(opt) < 3 or opt.lower() in {
                "main", "mod", "file", "files", "it", "this", "that", "default",
                "executable", "patcher", "installer", "contents", "above", "below",
                "the", "a", "an", "your", "its", "their", "one", "both", "either",
                "patch", "option", "version", "variant", "install", "folder",
                "following", "other", "same", "first", "second", "third",
            }:
                continue
            dirs.namespace_preferences.append(opt)
            # Also add a short tail token (e.g. "Senni Vek's Ambush" -> "ambush").
            tail = opt.split()[-1].strip("'’s")
            if tail and tail.lower() != opt.lower():
                dirs.namespace_preferences.append(tail)

    dirs.namespace_preferences = _dedupe(dirs.namespace_preferences)


_NEG_RE = re.compile(r"\b(do not|don't|dont|ignore|not any|avoid|never|except)\b", re.I)
# An affirmative imperative to grab a specific download, e.g. "download the X",
# "download just the main file", "download both ...". Excludes descriptive
# mentions like "the version from the 'X.rar' download".
_DL_AFFIRM_RE = re.compile(r"\bdownload(?:ing)?\s+(?:the|just|only|both|your)\b", re.I)


def _clauses(text: str) -> list[str]:
    out: list[str] = []
    for sent in _split_sentences(text):
        out.extend(c.strip() for c in re.split(r"[;,]", sent) if c.strip())
    return out


def _parse_download_choice(text: str, dirs: Directives) -> None:
    if "download" not in text.lower():
        return
    # Only act on an affirmative "download the/just/only/both X" clause that has
    # no negation ("do not download", "ignore the other ...") - those describe
    # what to AVOID and must never become a download_only target.
    for clause in _clauses(text):
        if not _DL_AFFIRM_RE.search(clause) or _NEG_RE.search(clause):
            continue
        # Filenames after the download verb (skip preview images).
        tail = clause[_DL_AFFIRM_RE.search(clause).start():]
        for fn in _FILENAME_RE.findall(tail):
            if not fn.lower().endswith(_IMG_EXTS) and _is_real_filename(fn):
                dirs.download_only.append(fn)
        for paren in re.findall(r"\(([^)]*\.(?:7z|zip|rar)[^)]*)\)", tail, re.I):
            for fn in _FILENAME_RE.findall(paren):
                if _is_real_filename(fn):
                    dirs.download_only.append(fn)
    dirs.download_only = _dedupe(dirs.download_only)


def _parse_file_selection(text: str, dirs: Directives) -> None:
    low = text.lower()
    # EXCEPT <explicit files>: capture the named files to drop.
    if "except" in low:
        # Take the text after the first "except" and harvest filenames there.
        after = text[low.index("except"):]
        names = [n for n in _FILENAME_RE.findall(after)
                 if not n.lower().endswith(_IMG_EXTS)]
        dirs.file_except.extend(names)

    # "ignore the MacOS folder" / "ignore the Effix folder".
    for m in re.finditer(r"ignore the ([\w '’-]{2,40}?) folder", text, re.I):
        dirs.file_except.append(m.group(1).strip())

    # "only move the four .dds ... files" / "only move the .TGA files".
    for m in re.finditer(
        r"only (?:move|copy|install|use)[^.]*?(\.(?:dds|tga|tpc|mdl|mdx|2da))\b",
        text, re.I,
    ):
        dirs.file_only.append(m.group(1).lower())

    # "Only move the files from 'X'" / "move just the files in the base folder".
    if re.search(r"only (move|copy|install|use) the files (from|in)", low):
        for q in _QUOTED_RE.findall(text):
            if not q.lower().endswith(_IMG_EXTS):
                dirs.file_only.append(q)

    dirs.file_only = _dedupe(dirs.file_only)
    dirs.file_except = _dedupe(dirs.file_except)


def _parse_order_and_deps(text: str, dirs: Directives) -> None:
    low = text.lower()
    if re.search(r"patch is (actually )?run first|run the patch first|"
                 r"for this specific mod[^.]*patch[^.]*first", low):
        dirs.patch_first = True
    if re.search(r"make sure to install (it|the patch|this patch)|"
                 r"make sure to (also )?(install|add) the (compatibility )?patch|"
                 r"you (must|need to) install the patch|"
                 r"install the patch after", low):
        dirs.requires_patch = True
    if re.search(r"re-?run the (patcher|installer|executable)|run (it )?(again|twice)|"
                 r"run the patcher \w+ times|multi-?run|run \d+ times|"
                 r"need to be run \d+ times", low):
        dirs.multi_run = True


def _parse_manual_notes(text: str, dirs: Directives) -> None:
    for sent in _split_sentences(text):
        sl = sent.lower()
        if any(k in sl for k in ("do not overwrite", "do not move", "do not use",
                                 "do not apply", "brick", "hex edit", "manually",
                                 "do not download")):
            dirs.manual_notes.append(sent[:200])
    dirs.manual_notes = _dedupe(dirs.manual_notes)


def match_option_index(option_names: list[str], dirs: "Directives",
                       legacy_hint: str = "") -> "int | None":
    """
    Pick the best install option (TSLPatcher namespace or TLK variant) for these
    directives. Returns an index into option_names, or None for "no opinion"
    (the caller then keeps its default, usually index 0).

    Order of preference:
      1. The community-patch-compatible option, when the mod offers one (the
         builds always install K1CP / TSLRCM, so this is the right pick).
      2. The page's recommended option(s), in order.
      3. A legacy single-string hint (back-compat).
    """
    if not option_names:
        return None
    low = [n.lower() for n in option_names]

    if dirs.prefer_compatible:
        for i, n in enumerate(low):
            if any(tok in n for tok in _COMPAT_TOKENS):
                return i

    for pref in dirs.namespace_preferences:
        p = pref.lower().strip()
        # Ignore short or generic captures so a stray "the"/"file"/"only" can't
        # mis-select a namespace; only act on a specific option token.
        if len(p) < 4 or p in _PREF_STOPWORDS:
            continue
        for i, n in enumerate(low):
            if p in n:
                return i

    if legacy_hint:
        h = legacy_hint.replace("_", " ").lower().strip()
        for i, n in enumerate(low):
            if h and (h in n):
                return i
    return None


def _path_matches(rel_path: str, entry: str) -> bool:
    """Does a relative file path match a selection entry?

    Entries are either an extension ('.dds'), a folder name ('MacOS', 'Patch'),
    or a filename ('N_SithComM.mdl'). Matching is case-insensitive and uses
    whole path components (not loose substrings) so 'Patch' can't match
    'patcher.exe'.
    """
    rp = rel_path.lower().replace("\\", "/")
    parts = rp.split("/")
    fname = parts[-1]
    e = entry.lower().strip()
    if not e:
        return False
    if e.startswith("."):
        return fname.endswith(e)
    return e == fname or e in parts


def select_paths(rel_paths: list[str], dirs: "Directives") -> tuple[list[str], list[str]]:
    """
    Apply the build guide's file-selection directives to a list of relative
    paths. Returns (kept, dropped).

    Safety: if 'only' filters would drop EVERYTHING (e.g. the instruction names
    a folder our extraction flattened away), we keep all files rather than
    install nothing, leaving the existing copy-everything behaviour intact.
    """
    if not dirs.file_only and not dirs.file_except:
        return list(rel_paths), []
    kept, dropped = [], []
    for rp in rel_paths:
        if any(_path_matches(rp, e) for e in dirs.file_except):
            dropped.append(rp)
            continue
        if dirs.file_only and not any(_path_matches(rp, e) for e in dirs.file_only):
            dropped.append(rp)
            continue
        kept.append(rp)
    if dirs.file_only and not kept:
        return list(rel_paths), []
    return kept, dropped


def parse_directives(instructions: str, warnings: str = "",
                     install_method: str = "") -> Directives:
    """Parse the build page's per-mod text into actionable install directives."""
    text = " ".join(t for t in (instructions, warnings) if t).strip()
    dirs = Directives(raw=text)
    if not text:
        return dirs
    # Strip the inline section headings ("Download Instructions", "Usage
    # Warning", etc.) so they don't glue onto the first sentence and confuse
    # clause-level negation checks.
    text = re.sub(
        r"\b(Download|Installation|Usage|Compatibility|Known)\s+"
        r"(Instructions|Warning|Bugs|Method)\b",
        ". ", text, flags=re.I,
    )
    _parse_namespace(text, dirs)
    _parse_download_choice(text, dirs)
    _parse_file_selection(text, dirs)
    _parse_order_and_deps(text, dirs)
    _parse_manual_notes(text, dirs)
    return dirs
