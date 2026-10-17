"""Extract one release from the full changelog for GitHub Releases."""

import argparse
import re
from pathlib import Path


def release_notes(changelog: str, tag: str) -> str:
    version = tag.removeprefix("v")
    sections = list(re.finditer(r"^## \[([^\]]+)\][^\n]*$", changelog, re.MULTILINE))
    matches = [i for i, section in enumerate(sections) if section[1] == version]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one changelog entry for {tag}")
    index = matches[0]
    start = sections[index].start()
    end = sections[index + 1].start() if index + 1 < len(sections) else len(changelog)
    notes = changelog[start:end].strip()
    if not notes.partition("\n")[2].strip():
        raise ValueError(f"Changelog entry for {tag} is empty")
    return notes + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--output", type=Path, default=Path("release-notes.md"))
    args = parser.parse_args()
    args.output.write_text(
        release_notes(args.changelog.read_text(encoding="utf-8"), args.tag),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
