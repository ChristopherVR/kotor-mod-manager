"""External guide entries must never be sent to the DeadlyStream downloader."""

from types import SimpleNamespace

import pytest

from installer.external_downloads import download_external
from installer.pipeline import ModStatus, Pipeline
from scraper import nexus
from scraper.build_scraper import BuildMod
from scraper.deadlystream import DownloadError


def _mod(host="nexus"):
    return BuildMod(1, "guide:9", "test-mod", "Test Mod",
                    "https://www.nexusmods.com/kotor/mods/123", "KOTOR1",
                    "", "", "", "", "", "k1_full", source_host=host)


def test_pipeline_routes_nexus_to_its_own_api(monkeypatch, tmp_path):
    monkeypatch.setattr(nexus, "load_api_key", lambda _: "test-key")
    monkeypatch.setattr(nexus, "list_files", lambda *args: [
        {"file_id": 45, "file_name": "mod.zip", "category_id": 1},
        {"file_id": 46, "file_name": "old.zip", "category_id": 7}])
    seen = []

    def download(game, mod_id, file_id, dest_dir, key, **kwargs):
        seen.append((game, mod_id, file_id, key, dest_dir))
        path = dest_dir / "mod.zip"
        path.write_bytes(b"downloaded archive")
        return path

    monkeypatch.setattr(nexus, "download_file", download)
    pipeline = Pipeline([_mod()], tmp_path / "game", tmp_path, object())
    pipeline._download_mod(pipeline.mods[0])
    assert pipeline.mods[0].status != ModStatus.ERROR
    assert seen[0][:4] == ("KOTOR1", 123, 45, "test-key")
    assert seen[0][4].name == "guide%3A9_test-mod"


def test_unsupported_host_explains_manual_cache_recovery(tmp_path):
    mod = _mod("mega")
    mod.url = "https://mega.nz/file/abc#key"
    with pytest.raises(DownloadError) as error:
        download_external(mod, tmp_path, object())
    assert mod.url in str(error.value)
    assert str(tmp_path) in str(error.value)
    assert "retry" in str(error.value)
    assert not mod.auto_downloadable


def test_nexus_free_account_error_includes_where_to_put_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(nexus, "load_api_key", lambda _: "test-key")
    monkeypatch.setattr(nexus, "list_files", lambda *args: [
        {"file_id": 45, "file_name": "mod.zip", "category_id": 1}])

    def refuse(*args, **kwargs):
        raise nexus.NexusAuthError("Nexus Premium is required.")

    monkeypatch.setattr(nexus, "download_file", refuse)
    with pytest.raises(DownloadError, match="Premium") as error:
        download_external(_mod(), tmp_path, object())
    assert str(tmp_path) in str(error.value)


def test_direct_download_uses_guide_url(tmp_path):
    mod = _mod("direct")
    mod.url = "https://example.test/mod.zip"
    seen = []
    client = SimpleNamespace(_download_from_url=lambda url, *args, **kwargs:
                             seen.append(url) or tmp_path / "mod.zip")
    assert download_external(mod, tmp_path, client) == [tmp_path / "mod.zip"]
    assert seen == [mod.url]
