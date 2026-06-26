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

# "copy X ... rename ... to Y" - copy a file under a new name in addition to the original.
# Handles: "make a copy of N_Duros02.tga, rename to N_Duros04.tga",
#           "copy the file 'LDA_EHawk01' ... Rename this duplicate to 'M36_EHawk01.tga'",
#           "Make a copy of N_CommM0801 ... Rename that duplicate file to 'N_CommM08.tga'".
_RENAME_COPY_RE = re.compile(
    r"(?:make\s+(?:a\s+)?(?:copy|duplicate)\s+of\s+|copy\s+(?:the\s+)?(?:file\s+)?)"
    r"['\"]?([A-Za-z0-9_.-]+)['\"]?"
    r".{0,300}?"
    r"(?:rename\b.{0,60}?\bto\s+|creating\s+)"  # flexible: "rename ... to" or "creating"
    r"['\"]?([A-Za-z0-9_.-]+\.[a-z0-9]+)['\"]?",
    re.I | re.S,
)

# "repeat with SRC creating DST" - additional copy-rename pair after the first.
_RENAME_REPEAT_RE = re.compile(
    r"repeat\s+with\s+['\"]?([A-Za-z0-9_.-]+\.[a-z0-9]+)['\"]?"
    r"\s+creating\s+['\"]?([A-Za-z0-9_.-]+\.[a-z0-9]+)['\"]?",
    re.I,
)

# "creating X and Y" - second destination name attached to a preceding source.
_RENAME_AND_RE = re.compile(
    r"creating\s+['\"]?([A-Za-z0-9_.-]+\.[a-z0-9]+)['\"]?"
    r"\s+and\s+['\"]?([A-Za-z0-9_.-]+\.[a-z0-9]+)['\"]?",
    re.I,
)

# "rename copies to BASENAME retaining file extensions" - copy all files, replacing stem.
_RENAME_BASE_RE = re.compile(
    r"rename\s+copies?\s+to\s+([A-Za-z0-9_-]+)\s+retaining\s+(?:file\s+)?extensions?",
    re.I,
)

# "rename it/this/the file FILENAME" - copy all files under this new stem.
# Used when the source is vague ("the file") but the destination is named.
_RENAME_IT_RE = re.compile(
    r"\brename\s+(?:it|this|the\s+(?:file|copy|duplicate))\s+(?:to\s+|as\s+)?"
    r"['\"]?([A-Za-z0-9_-]+)(?:\.[a-z0-9]+)?['\"]?",
    re.I,
)

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
    # File copy-and-rename pairs: [(src_filename, dst_filename), ...].
    # Installer creates an additional copy of src under the dst name.
    rename_copies: list = field(default_factory=list)
    # When set, copy all files in the mod under this stem (keeping extensions).
    # e.g. "PLC_CompPnl_b" → PLC_CompPnl.tpc becomes PLC_CompPnl_b.tpc as well.
    rename_base_copies: str = ""
    # Ordered list of TSLPatcher/HoloPatcher option names to run in sequence.
    # Non-empty implies multi_run; each entry is matched via match_option_index.
    multi_run_options: list[str] = field(default_factory=list)
    # Files to delete from Override/Modules AFTER the mod installs successfully.
    # Populated from "delete X from Override" instructions in the build guide.
    post_install_delete: list[str] = field(default_factory=list)
    raw: str = ""

    def is_empty(self) -> bool:
        return not any([
            self.namespace_preferences, self.prefer_compatible,
            self.download_only, self.download_ignore,
            self.file_only, self.file_except,
            self.patch_first, self.requires_patch, self.multi_run,
            self.manual_notes, self.rename_copies, self.rename_base_copies,
            self.multi_run_options, self.post_install_delete,
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
        if self.multi_run_options:
            bits.append(f"runs the patcher {len(self.multi_run_options)} times "
                        f"({', '.join(self.multi_run_options[:2])}"
                        f"{', ...' if len(self.multi_run_options) > 2 else ''})")
        elif self.multi_run:
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

    # ---- EXCLUSIONS ----

    # "except X.tga, Y.tga" or "except for the Effix folder" - capture filenames and
    # folder names after the word "except".
    if "except" in low:
        after = text[low.index("except"):]
        # Filenames (known extensions)
        names = [n for n in _FILENAME_RE.findall(after)
                 if not n.lower().endswith(_IMG_EXTS)]
        dirs.file_except.extend(names)
        # Folder names: "except for the X folder" / "except the X folder"
        for m in re.finditer(r"except\s+(?:for\s+)?(?:the\s+)?([A-Za-z][A-Za-z0-9 _-]{2,40}?)\s+folder", after, re.I):
            dirs.file_except.append(m.group(1).strip())

    # "delete X.tga" / "remove X.tga" before installing (pre-install exclusion).
    # Exclude "delete from Override/game" which is a post-install cleanup instruction.
    _POST_OVERRIDE_RE = re.compile(
        r"\bdelete\b.{0,60}?\bfrom\s+(?:the\s+)?(?:override|your\s+game|the\s+game|the\s+install)",
        re.I,
    )
    for sent in _split_sentences(text):
        sl = sent.lower()
        if ("delete" not in sl and "remove" not in sl) or _POST_OVERRIDE_RE.search(sent):
            continue
        for fn in _FILENAME_RE.findall(sent):
            if not fn.lower().endswith(_IMG_EXTS) and _is_real_filename(fn):
                dirs.file_except.append(fn)

    # "do not move/install/use X.tga" - explicit single-file negation.
    for m in re.finditer(
        r"do\s+not\s+(?:move|install|include|use|overwrite)\s+"
        r"[‘\"]?([A-Za-z0-9_.-]+\.(?:tga|tpc|dds|mdl|mdx|2da|wav|mp3|utm))[‘\"]?",
        text, re.I,
    ):
        fn = m.group(1).strip()
        if _is_real_filename(fn):
            dirs.file_except.append(fn)

    # "ignore the MacOS folder / skip the Optional folder / never apply the X folder"
    # Scan full sentences that contain ignore/skip/never-apply verbs for ALL folder names.
    _FOLDER_STOPWORDS = {"all", "any", "other", "these", "those", "following", "each"}
    _FOLDER_VERB_RE = re.compile(
        r"\b(?:ignore|skip|do\s+not\s+(?:use|install|include)|never\s+apply)\b", re.I)
    for sent in _split_sentences(text):
        if not _FOLDER_VERB_RE.search(sent):
            continue
        for m in re.finditer(
            r"(?:ignore|skip|do\s+not\s+(?:use|install|include)|never\s+apply|and)\s+(?:the\s+)?"
            r"[‘\"]?([A-Za-z][A-Za-z0-9 _-]{2,40}?)[‘\"]?\s+(?:sub)?folder",
            sent, re.I,
        ):
            name = m.group(1).strip()
            if name.lower() not in _FOLDER_STOPWORDS:
                dirs.file_except.append(name)

    # "delete X.tpc, Y.tpc from Override" - post-install cleanup.
    # These files must be removed AFTER install so a newer .dds or replacement wins.
    for m in re.finditer(
        r"\bdelete\b(.{5,300}?)\bfrom\s+(?:the\s+)?(?:override|your\s+override"
        r"|the\s+override)\b",
        text, re.I,
    ):
        for fn in _FILENAME_RE.findall(m.group(1)):
            if not fn.lower().endswith(_IMG_EXTS) and _is_real_filename(fn):
                dirs.post_install_delete.append(fn)
    dirs.post_install_delete = _dedupe(dirs.post_install_delete)

    # ---- INCLUSIONS ----

    # "only move/copy the .dds files" - extension-based whitelist.
    for m in re.finditer(
        r"only\s+(?:move|copy|install|use)[^.]*?(\.(?:dds|tga|tpc|mdl|mdx|2da))\b",
        text, re.I,
    ):
        dirs.file_only.append(m.group(1).lower())

    # "only move/use the files from/in ‘QuotedFolder’" - quoted subfolder name.
    if re.search(r"only\s+(?:move|copy|install|use)\s+the\s+files?\s+(?:from|in)\b", low):
        for q in _QUOTED_RE.findall(text):
            if not q.lower().endswith(_IMG_EXTS):
                dirs.file_only.append(q)

    # "only use the files in/from the X subfolder" (unquoted folder name).
    for m in re.finditer(
        r"only\s+(?:use|move|install|copy)\s+(?:the\s+)?(?:files?\s+)?(?:in|from)\s+"
        r"(?:the\s+)?[‘\"]?([A-Za-z][A-Za-z0-9 _-]{2,40}?)[‘\"]?\s+(?:sub)?folder",
        text, re.I,
    ):
        name = m.group(1).strip()
        if name.lower() not in {"base", "the", "a", "this", "that", "same"}:
            dirs.file_only.append(name)

    # "navigate to the X folder and move" - explicit subfolder navigation instruction.
    for m in re.finditer(
        r"(?:navigate|go)\s+(?:in)?to\s+(?:the\s+)?[‘\"]?([A-Za-z][A-Za-z0-9 _-]{2,40}?)[‘\"]?"
        r"\s+(?:sub)?folder\s+(?:and|inside|within)\s+(?:move|copy|install)",
        text, re.I,
    ):
        name = m.group(1).strip()
        if name.lower() not in {"base", "the", "a", "this", "that"}:
            dirs.file_only.append(name)

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

    # Try to extract the exact ordered option names for a multi-run install
    # so the log message (and eventually the installer) can name them explicitly.
    # e.g. "run once selecting Kaevee Removal Part 1, once selecting Saedhe's Head"
    _OPTION_RUN_RE = re.compile(
        r"(?:once|each\s+time)\s+(?:selecting|choosing|for|with)\s+"
        r"['\"]?([A-Za-z][A-Za-z0-9 _',&-]{2,80}?)['\"]?"
        r"(?=\s*[,;.]|\s+and\b|\s+once\b|$)",
        re.I,
    )
    opts = [m.group(1).strip(" '\".,;") for m in _OPTION_RUN_RE.finditer(text)]
    if opts and len(opts) >= 2:
        dirs.multi_run_options = _dedupe(opts)
        dirs.multi_run = True


def _parse_rename_copies(text: str, dirs: Directives) -> None:
    """Parse copy-and-rename directives from build guide instructions."""
    pairs: list[tuple[str, str]] = []

    for src, dst in _RENAME_COPY_RE.findall(text):
        src, dst = src.strip(" '\""), dst.strip(" '\"")
        if src and dst and src.lower() != dst.lower():
            pairs.append((src, dst))

    # "repeat with SRC creating DST" - additional pair using a different source.
    for src, dst in _RENAME_REPEAT_RE.findall(text):
        src, dst = src.strip(" '\""), dst.strip(" '\"")
        if src and dst and src.lower() != dst.lower():
            pairs.append((src, dst))

    # "creating X and Y" - two destinations from a single preceding source.
    for m in _RENAME_AND_RE.finditer(text):
        name1, name2 = m.group(1).strip(), m.group(2).strip()
        src_for = next((s for s, d in pairs if d.lower() == name1.lower()), None)
        if src_for and not any(d.lower() == name2.lower() for _, d in pairs):
            pairs.append((src_for, name2))

    seen: set[str] = set()
    for src, dst in pairs:
        key = f"{src.lower()}\x00{dst.lower()}"
        if key not in seen:
            seen.add(key)
            dirs.rename_copies.append((src, dst))

    # Base-name rename: "rename copies to STEM retaining file extensions"
    m = _RENAME_BASE_RE.search(text)
    if m:
        dirs.rename_base_copies = m.group(1).strip()
    elif not dirs.rename_copies:
        # "rename it/this/the file FILENAME" - vague source means copy all files.
        m = _RENAME_IT_RE.search(text)
        if m:
            dirs.rename_base_copies = m.group(1).strip()


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
    _parse_rename_copies(text, dirs)
    _parse_manual_notes(text, dirs)
    return dirs
