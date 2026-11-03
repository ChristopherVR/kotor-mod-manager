"""Keep Nexus file names within the API's limits before uploading binaries."""

import re
from pathlib import Path

import pytest


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
).read_text(encoding="utf-8")
NAMES = re.findall(r"^\s+nexus_name: (.+)$", WORKFLOW, re.MULTILINE)


def test_both_platforms_have_distinct_nexus_names():
    assert len(NAMES) == 2
    assert len(set(NAMES)) == 2
    assert any("Windows" in name for name in NAMES)
    assert any("Linux" in name for name in NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_names_match_nexus_create_file_version_schema(name):
    # https://api.nexusmods.com/openapi.yaml, CreateModFileVersionRequest.name
    assert 1 <= len(name) <= 50
    assert re.fullmatch(r"[a-zA-Z0-9 _'().-]+", name)


def test_upload_uses_the_validated_name_without_appending_version():
    assert "NEXUS_DISPLAY_NAME: ${{ matrix.nexus_name }}" in WORKFLOW
    assert "display_name: ${{ env.NEXUS_DISPLAY_NAME }}" in WORKFLOW
    assert '${#NEXUS_DISPLAY_NAME}" -gt 50' in WORKFLOW
