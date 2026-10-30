"""Regression coverage for the live build download audit."""
from pathlib import Path

import pytest

from scraper import hosts
from scraper.deadlystream import DeadlyStreamClient, DownloadError
from tests.test_hosts import FakeResp
from tests.test_pipeline_fixes import _mod, _pipeline


def test_dropbox_forces_download_and_keeps_access_key(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(hosts, "download_direct", lambda url, *a: seen.append(url))
    hosts.download_dropbox("https://www.dropbox.com/scl/fi/a/mod.zip?rlkey=abc&dl=0", tmp_path)
    assert seen == ["https://www.dropbox.com/scl/fi/a/mod.zip?rlkey=abc&dl=1"]


def test_ntcore_follows_only_the_official_archive(tmp_path, monkeypatch):
    responses = iter([
        FakeResp(text='<a href="https://other.example/4gb_patch.zip">Ad</a>'
                      '<a href="/files/4gb_patch.zip">Download</a>', url="https://ntcore.com/4gb-patch/"),
        FakeResp(b"PKdata", {"Content-Type": "application/zip", "Content-Length": "6"},
                 url="https://ntcore.com/files/4gb_patch.zip"),
    ])
    seen = []
    def get(self, url, **kw):
        seen.append(url)
        return next(responses)
    monkeypatch.setattr(hosts.requests.Session, "get", get)
    out = hosts.download_ntcore("https://ntcore.com/?page_id=371", tmp_path)
    assert out.name == "4gb_patch.zip" and out.read_bytes() == b"PKdata"
    assert seen[-1] == "https://ntcore.com/files/4gb_patch.zip"


def _k2_records():
    return [{"name": f"k2rs_30fps{addon}_{size}.7z", "url": "https://example/file"}
            for addon in ("", "_mods") for size in ("1920x1080", "2560x1440")]


def test_k2_downloads_one_main_and_matching_addon(tmp_path):
    client = DeadlyStreamClient()
    client.list_download_records = lambda *a: _k2_records()
    fetched, offered = [], []
    def choose(records):
        offered.extend(records)
        return records[1]
    def fetch(url, dest, fid, **kw):
        fetched.append(kw['fallback_name'])
        return dest / kw['fallback_name']
    client._download_from_url = fetch
    client.download_all_files("2503", tmp_path, choose_variant=choose,
                              resolution_companions=["_mods"])
    assert len(offered) == 2 and all("_mods" not in r["name"] for r in offered)
    assert fetched == ["k2rs_30fps_2560x1440.7z", "k2rs_30fps_mods_2560x1440.7z"]


def test_k2_missing_matching_addon_does_not_download_partial_mod(tmp_path):
    client = DeadlyStreamClient()
    client.list_download_records = lambda *a: _k2_records()[:-1]
    with pytest.raises(DownloadError, match="matching"):
        client.download_all_files("2503", tmp_path, choose_variant=lambda rs: rs[1],
                                  resolution_companions=["_mods"])


def test_linked_patch_cache_requires_main_and_patch(tmp_path, monkeypatch):
    mod = _mod(patch_urls=["https://mega.nz/file/patch#key"],
               instructions="Download only 'main.zip'.")
    p = _pipeline(tmp_path, [mod])
    pm = p.mods[0]
    dest = p._mod_dir(pm)
    dest.mkdir(parents=True)
    (dest / "old-patch.zip").write_bytes(b"old")
    p._write_cache_manifest(dest, [dest / "old-patch.zip"])
    seen = []
    def main(**kw):
        path = kw["dest_dir"] / "main.zip"
        path.write_bytes(b"main")
        return [path]
    def patch(host, url, folder, *a):
        seen.append((host, url))
        folder.mkdir(parents=True)
        path = folder / "patch.zip"
        path.write_bytes(b"patch")
        return [path]
    p._client.download_all_files = main
    monkeypatch.setattr(hosts, "download_from_host", patch)
    p._download_mod(pm)
    assert [a.name for a in pm.archive_paths] == ["main.zip", "patch.zip"]
    assert seen == [("mega", mod.patch_urls[0])]
    assert p._cached_for(pm, dest) == pm.archive_paths
    pm.archive_paths[-1].unlink()
    assert p._cached_for(pm, dest) == []


@pytest.mark.parametrize("build", ["k2_full", "k2_spoilerfree"])
def test_k2_guide_does_not_filter_out_main_pack(build):
    mod = _mod(file_id="2503", build_key=build,
               instructions='Download the file with "_mods" appended to the filename.')
    assert mod.directives.download_only == []
    assert mod.directives.resolution_companions == ["_mods"]


def test_k2_addon_only_legacy_cache_is_not_reused(tmp_path):
    p = _pipeline(tmp_path, [_mod(file_id="2503", build_key="k2_full")])
    pm = p.mods[0]
    dest = p._mod_dir(pm)
    dest.mkdir(parents=True)
    addon = dest / "k2rs_30fps_mods_1920x1080.7z"
    addon.write_bytes(b"addon")
    p._write_cache_manifest(dest, [addon])
    assert p._cached_for(pm, dest) == []


def test_k2_cache_discards_addons_for_other_resolutions(tmp_path):
    p = _pipeline(tmp_path, [_mod(file_id="2503", build_key="k2_full")])
    pm = p.mods[0]
    dest = p._mod_dir(pm)
    dest.mkdir(parents=True)
    names = ["k2rs_30fps_1920x1080.7z", "k2rs_30fps_mods_1920x1080.7z",
             "k2rs_30fps_mods_2560x1440.7z"]
    paths = [dest / name for name in names]
    for path in paths:
        path.write_bytes(b"archive")
    p._write_cache_manifest(dest, paths)
    assert p._cached_for(pm, dest) == paths[:2]


def test_new_manual_main_in_mod_folder_can_receive_linked_patch(tmp_path, monkeypatch):
    import time
    import installer.pipeline as pipeline
    p = _pipeline(tmp_path, [_mod(source_host="gamefront", patch_urls=["https://mega.nz/file/patch#key"])])
    pm = p.mods[0]
    dest = p._mod_dir(pm)
    dest.mkdir(parents=True)
    seen = {"_started": time.time() - 1}
    main = dest / "main.zip"
    main.write_bytes(b"main")
    monkeypatch.setattr(pipeline, "_DROP_SETTLE_SECONDS", 0)
    assert p._dropped_archive(pm, dest, seen) == [main]


def test_gamefront_opens_browser_in_an_interactive_run(tmp_path, monkeypatch):
    import webbrowser
    p = _pipeline(tmp_path, [_mod(source_host="gamefront", url="https://www.gamefront.com/games/x/file/y")],
                  on_confirm=lambda *a: None)
    seen = []
    monkeypatch.setattr(webbrowser, "open", lambda url: seen.append(url))
    monkeypatch.setattr(p, "_dropped_archive", lambda *a: [tmp_path / "mod.zip"])
    assert p._await_dropped_file(p.mods[0], tmp_path, "") == [tmp_path / "mod.zip"]
    assert seen == [p.mods[0].build_mod.url]
