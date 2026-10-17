"""Release pages must show only the requested version's changes."""

import pytest

from tools.release_notes import release_notes


CHANGELOG = """# Changelog

## [Unreleased]

### Features
- Still in development

## [0.19.4] - 2026-10-14

### Bug Fixes
- Latest fix

## [0.19.3] - 2026-10-13

### Features
- Older feature
"""


@pytest.mark.parametrize("tag", ["v0.19.4", "0.19.4"])
def test_only_requested_release(tag):
    assert release_notes(CHANGELOG, tag) == (
        "## [0.19.4] - 2026-10-14\n\n### Bug Fixes\n- Latest fix\n"
    )


def test_last_release_and_windows_line_endings():
    assert release_notes(CHANGELOG.replace("\n", "\r\n"), "v0.19.3").endswith(
        "- Older feature\n"
    )


@pytest.mark.parametrize(
    "changelog, tag",
    [
        (CHANGELOG, "v0.19.40"),
        (CHANGELOG + "\n## [0.19.4]\n- Duplicate", "v0.19.4"),
        ("## [0.19.4]\n\n## [0.19.3]\n- Older", "v0.19.4"),
    ],
)
def test_missing_duplicate_or_empty_entry_blocks_release(changelog, tag):
    with pytest.raises(ValueError):
        release_notes(changelog, tag)
