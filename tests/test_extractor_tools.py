"""7-Zip discovery, saved overrides and extraction without external 7-Zip."""
import io
import sys
import types
import zipfile
from unittest.mock import MagicMock, Mock

import pytest

import config
from installer import extractor


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "settings")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings" / "config.json")


def test_custom_path_takes_priority(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: {"seven_zip_path": '"D:/Portable Tools/7z.exe"'})
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: cmd)
    assert extractor._find_7z() == "D:/Portable Tools/7z.exe"


def test_missing_custom_path_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: {"seven_zip_path": "/missing/7z"})
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: "/usr/bin/7zz" if cmd == "7zz" else None)
    assert extractor._find_7z() == "/usr/bin/7zz"


def test_windows_environment_install(monkeypatch, tmp_path):
    base = tmp_path / "Custom Program Files"
    expected = str(base / "7-Zip" / "7z.exe")
    monkeypatch.setattr(extractor.sys, "platform", "win32")
    monkeypatch.setenv("ProgramW6432", str(base))
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: cmd if cmd == expected else None)
    # Registry is absent on Linux test runners.
    registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
                                    KEY_WOW64_64KEY=256, KEY_WOW64_32KEY=512, KEY_READ=1,
                                    OpenKey=Mock(side_effect=OSError))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert extractor._find_7z() == expected


def test_windows_registry_install(monkeypatch, tmp_path):
    expected = str(tmp_path / "7z.exe")
    monkeypatch.setattr(extractor.sys, "platform", "win32")
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: cmd if cmd == expected else None)
    key = Mock()
    key.__enter__ = Mock(return_value=key)
    key.__exit__ = Mock(return_value=False)
    registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
                                    KEY_WOW64_64KEY=256, KEY_WOW64_32KEY=512, KEY_READ=1,
                                    OpenKey=Mock(return_value=key),
                                    QueryValueEx=Mock(return_value=(str(tmp_path), 1)))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert extractor._find_7z() == expected


def test_settings_roundtrip(tmp_path, monkeypatch):
    from backend import server
    from backend.models import SettingsModel

    path = str(tmp_path / "Portable 7-Zip" / "7z.exe")
    server.set_settings(SettingsModel(seven_zip_path=path, nexus_api_key="keep-me"))
    assert server.get_settings()["seven_zip_path"] == path
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: path if cmd == path else None)
    assert server.extractor_status() == {"seven_zip_path": path}
    server.set_settings(SettingsModel(**{**server.get_settings(), "seven_zip_path": ""}))
    assert server.get_settings()["seven_zip_path"] == ""
    assert server.get_settings()["nexus_api_key"] == "keep-me"


@pytest.mark.parametrize("suffix", [".zip", ".exe"])
def test_zip_and_zip_sfx_without_external_tools(tmp_path, monkeypatch, suffix):
    monkeypatch.setattr(extractor, "_find_7z", lambda: None)
    monkeypatch.setattr(extractor, "HAS_7Z", False)
    run = Mock(side_effect=AssertionError("ZIP must not need an external tool"))
    monkeypatch.setattr(extractor.subprocess, "run", run)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("textures/test.tga", b"texture")
    archive = tmp_path / f"mod{suffix}"
    archive.write_bytes((b"MZ fake SFX stub" if suffix == ".exe" else b"") + payload.getvalue())
    dest = extractor.extract(archive, tmp_path / "out")
    assert (dest / "textures" / "test.tga").read_bytes() == b"texture"
    run.assert_not_called()


@pytest.mark.parametrize("platform,tool", [("win32", "tar"), ("linux", "bsdtar")])
@pytest.mark.parametrize("suffix", [".7z", ".rar", ".exe"])
def test_system_archive_fallback(tmp_path, monkeypatch, platform, tool, suffix):
    monkeypatch.setattr(extractor.sys, "platform", platform)
    monkeypatch.setattr(extractor, "_find_7z", lambda: None)
    monkeypatch.setattr(extractor, "_find_unrar", lambda: None)
    monkeypatch.setattr(extractor, "HAS_7Z", False)
    monkeypatch.setattr(extractor, "HAS_RAR", False)
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: tool if cmd == tool else None)
    run = Mock(return_value=types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(extractor.subprocess, "run", run)
    archive = tmp_path / f"mod{suffix}"
    archive.write_bytes(b"fake archive")
    dest = tmp_path / "output with spaces"
    extractor.extract(archive, dest)
    run.assert_called_once_with([tool, "-xf", str(archive.resolve()), "-C", str(dest.resolve())],
                                capture_output=True)


def test_broken_7z_executable_does_not_block_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "_find_7z", lambda: "/broken/7z")
    fallback = Mock(return_value=True)
    monkeypatch.setattr(extractor, "_extract_system_archive", fallback)
    monkeypatch.setattr(extractor.subprocess, "run", Mock(side_effect=PermissionError))
    extractor._extract_self_extracting_exe(tmp_path / "mod.exe", tmp_path / "out")
    fallback.assert_called_once()


def test_sfx_error_explains_settings_not_path(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "_find_7z", lambda: None)
    monkeypatch.setattr(extractor, "_extract_system_archive", lambda *a: False)
    monkeypatch.setattr(extractor, "HAS_7Z", False)
    with pytest.raises(extractor.ExtractionError, match="Settings > General > Archive extraction") as error:
        extractor._extract_self_extracting_exe(tmp_path / "tslrcm2022.exe", tmp_path / "out")
    assert "do not need to change PATH" in str(error.value)


def test_zip_unsupported_method_uses_system_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor.zipfile, "ZipFile", Mock(side_effect=NotImplementedError))
    fallback = Mock(return_value=True)
    monkeypatch.setattr(extractor, "_extract_system_archive", fallback)
    archive, dest = tmp_path / "mod.zip", tmp_path / "out"
    extractor._extract_zip(archive, dest)
    fallback.assert_called_once_with(archive, dest, is_zip=True)


def test_linux_unzip_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(extractor.sys, "platform", "linux")
    monkeypatch.setattr(extractor.shutil, "which", lambda cmd: "/usr/bin/unzip" if cmd == "unzip" else None)
    run = Mock(return_value=types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(extractor.subprocess, "run", run)
    archive, dest = tmp_path / "mod.zip", tmp_path / "out"
    assert extractor._extract_system_archive(archive, dest, is_zip=True)
    assert run.call_args.args[0] == ["/usr/bin/unzip", "-o", str(archive.resolve()), "-d", str(dest.resolve())]


def test_failed_system_extraction_falls_back_to_library(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "_find_7z", lambda: None)
    monkeypatch.setattr(extractor, "_extract_system_archive", lambda *a: False)
    monkeypatch.setattr(extractor, "HAS_7Z", True)
    library = MagicMock()
    monkeypatch.setattr(extractor, "py7zr", types.SimpleNamespace(SevenZipFile=library), raising=False)
    extractor._extract_7z(tmp_path / "mod.7z", tmp_path / "out")
    library.assert_called_once()
