"""External build IDs must work as Windows folders throughout the app."""

from types import SimpleNamespace

import pytest

from backend.library_routes import _source_folder
from installer.download_paths import download_folder_name
from installer.mod_manager import cache_stats
from installer.pipeline import ModStatus, Pipeline
from scraper.build_scraper import BuildMod


@pytest.mark.parametrize("file_id,slug", [
    ("guide:9", "ultimate-korriban-high-resolution"),
    ("guide:10", 'bad/slug:with?characters.'),
    ("../escape", "mod"),
])
def test_folder_is_a_single_windows_safe_component(file_id, slug):
    name = download_folder_name(file_id, slug)
    assert not any(c in name for c in '<>:"/\\|?*')
    assert not name.endswith((" ", "."))


def test_numeric_ids_keep_existing_cache_names():
    assert download_folder_name("42", "test-mod") == "42_test-mod"
    assert download_folder_name("guide:9", "mod") != download_folder_name("guide-9", "mod")


def test_external_mod_cache_is_reused_and_found_by_library(tmp_path):
    mod = BuildMod(1, "guide:9", "korriban", "Korriban", "https://mega.nz/file/x#y",
                   "KOTOR1", "", "", "", "", "", "k1_full", source_host="mega")
    folder = tmp_path / download_folder_name(mod.file_id, mod.slug)
    folder.mkdir()
    archive = folder / "mod.zip"
    archive.write_bytes(b"cached archive")

    class NoNetwork:
        def download_all_files(self, **kwargs):
            pytest.fail("A completed cached download should be reused")

    pipeline = Pipeline([mod], tmp_path / "game", tmp_path, NoNetwork())
    pipeline._download_mod(pipeline.mods[0])
    assert pipeline.mods[0].status != ModStatus.ERROR
    assert pipeline.mods[0].archive_paths == [archive]
    record = SimpleNamespace(source_type="build", source_ref=mod.file_id, source_slug=mod.slug)
    assert _source_folder(record, tmp_path) == folder
    stats = cache_stats(tmp_path, {mod.file_id})
    assert stats["entries"][0]["in_use"]


def test_open_download_reveals_the_same_safe_folder(monkeypatch, tmp_path):
    from backend import server, fsutil
    from backend.models import OpenDownloadRequest
    folder = tmp_path / download_folder_name("guide:9", "korriban")
    folder.mkdir()
    monkeypatch.setattr(server.cfg, "download_dir", lambda: tmp_path)
    seen = []
    monkeypatch.setattr(fsutil, "reveal_path", lambda path: seen.append(path) or True)
    result = server.open_mod_download(OpenDownloadRequest(
        file_id="guide:9", slug="korriban", game="KOTOR1"))
    assert seen == [folder]
    assert not result["fallback"]
