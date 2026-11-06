"""Nexus packages must contain the exact scanned app and player instructions."""

import hashlib
from zipfile import ZipFile

import pytest

from tools.package_nexus import package_nexus


@pytest.fixture(params=["windows", "linux"])
def inputs(tmp_path, request):
    files = {}
    for name, content in {
        "executable": b"MZ\x00standalone app",
        "notes": b"## [1.2.3]\n\n### Fixes\n- **Fixed** `downloads`\n- [Guide](https://example.com)\n",
        "scan_report": b"ClamAV\nInfected files: 0\n",
        "license_file": b"GPL-3.0-only\n",
    }.items():
        files[name] = tmp_path / name
        files[name].write_bytes(content)
    return dict(
        tag="v1.2.3", repository="ChristopherVR/kotor-mod-manager",
        platform=request.param,
        output=tmp_path / "nexus", **files,
    )


def test_nexus_api_requests_name_the_app_and_version(monkeypatch):
    from scraper import nexus
    seen = {}

    class R:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake(req, timeout=0):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return R()

    monkeypatch.setattr(nexus.urllib.request, "urlopen", fake)
    nexus._get_json("https://api.nexusmods.com/v1/users/validate.json", "k")
    assert seen["application-name"] == "KOTOR Mod Installer"
    assert seen["application-version"] == nexus._app_version() != "0.0.0"


def test_package_contains_exact_app_instructions_license_report_and_checksums(inputs):
    archive = package_nexus(**inputs)
    is_linux = inputs["platform"] == "linux"
    suffix = "-linux" if is_linux else ""
    executable_name = "KOTOR-Mod-Installer-linux-x86_64" if is_linux else "KOTOR-Mod-Installer.exe"
    assert archive.name == f"kotor-mod-installer-1.2.3{suffix}-nexus.zip"
    with ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {
            executable_name, "READ-ME-FIRST.txt", "virus-scan.txt",
            "LICENSE", "SHA256SUMS.txt", "nexus-build.flag",
        }
        assert "never updates itself" in zipped.read("READ-ME-FIRST.txt").decode()
        assert zipped.read(executable_name) == inputs["executable"].read_bytes()
        assert zipped.read("virus-scan.txt") == inputs["scan_report"].read_bytes()
        assert zipped.read("LICENSE") == inputs["license_file"].read_bytes()
        readme = zipped.read("READ-ME-FIRST.txt").decode()
        assert "not a mod to deploy with Vortex" in readme
        assert "releases/tag/v1.2.3" in readme
        if is_linux:
            assert "chmod +x KOTOR-Mod-Installer-linux-x86_64" in readme
            assert "WebKitGTK 4.1" in readme
            assert "SmartScreen" not in readme
            info = zipped.getinfo(executable_name)
            assert info.create_system == 3
            assert (info.external_attr >> 16) & 0o777 == 0o755
        for line in zipped.read("SHA256SUMS.txt").decode().splitlines():
            digest, name = line.split("  ", 1)
            assert digest == hashlib.sha256(zipped.read(name)).hexdigest()
    description = (inputs["output"] / f"description{suffix}.txt").read_text(encoding="utf-8")
    assert executable_name in description
    assert ("Linux x86_64" if is_linux else "Windows") in description
    assert "Fixed downloads" in description
    assert "Guide (https://example.com)" in description
    assert "###" not in description
    assert "releases/tag/v1.2.3" in description


@pytest.mark.parametrize("name", ["executable", "notes", "scan_report", "license_file"])
@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_input_blocks_packaging(inputs, name, missing):
    if missing:
        inputs[name].unlink()
    else:
        inputs[name].write_bytes(b"")
    with pytest.raises(ValueError, match="Missing or empty"):
        package_nexus(**inputs)
    assert not inputs["output"].exists()


@pytest.mark.parametrize("tag", ["../1.2.3", "v1.2", "v1.2.3;echo bad", ""])
def test_invalid_version_cannot_become_an_archive_path(inputs, tag):
    inputs["tag"] = tag
    with pytest.raises(ValueError, match="Invalid release version"):
        package_nexus(**inputs)


def test_prerelease_version(inputs):
    inputs["tag"] = "v1.2.3-beta.1"
    suffix = "-linux" if inputs["platform"] == "linux" else ""
    assert package_nexus(**inputs).name == f"kotor-mod-installer-1.2.3-beta.1{suffix}-nexus.zip"


def test_invalid_repository(inputs):
    inputs["repository"] = "owner/repo/../../other"
    with pytest.raises(ValueError, match="Invalid GitHub repository"):
        package_nexus(**inputs)


def test_platform_packages_and_descriptions_do_not_overwrite_each_other(inputs):
    windows_archive = package_nexus(**{**inputs, "platform": "windows"})
    windows_description = (inputs["output"] / "description.txt").read_bytes()
    linux_archive = package_nexus(**{**inputs, "platform": "linux"})
    assert windows_archive != linux_archive
    assert windows_archive.is_file() and linux_archive.is_file()
    assert (inputs["output"] / "description.txt").read_bytes() == windows_description
    assert (inputs["output"] / "description-linux.txt").is_file()


def test_unsupported_platform(inputs):
    inputs["platform"] = "../macos"
    with pytest.raises(ValueError, match="Unsupported platform"):
        package_nexus(**inputs)
