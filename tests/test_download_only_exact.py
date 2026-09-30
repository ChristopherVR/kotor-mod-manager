"""A build guide's "download only X" means the file X, not every add-on whose
name starts the same way (HQ Skyboxes II: the main pack versus its planet add-ons)."""
from pathlib import Path

import pytest

from scraper import nexus
from scraper.deadlystream import (DeadlyStreamClient, download_name_matches,
                                  exact_keep_matches, select_keep_matches)
from tests.test_pipeline_fixes import _mod, _pipeline

FAMILY = ["HQSkyboxesII_K1_BOSSR.7z", "HQSkyboxesII_K1_Yavin4.7z", "HQSkyboxesII_K1_1k.7z",
          "HQSkyboxesII_K1_1k_Yavin4.7z", "HQSkyboxesII_K1.7z"]
KEEP = ["HQSkyboxesII_K1.7z"]


def test_strict_matching_takes_only_the_exact_file():
    assert [n for n in FAMILY if download_name_matches(n, KEEP, strict=True)] == ["HQSkyboxesII_K1.7z"]
    # The loose rule is what pulled in the whole family.
    assert len([n for n in FAMILY if download_name_matches(n, KEEP)]) == len(FAMILY)


def test_strict_ignores_case_and_punctuation():
    assert download_name_matches("hq skyboxes ii k1.7Z", KEEP, strict=True)


def test_exact_matches_helper_and_select_agree():
    assert exact_keep_matches(FAMILY, KEEP) == ["HQSkyboxesII_K1.7z"]
    assert select_keep_matches(FAMILY, KEEP) == ["HQSkyboxesII_K1.7z"]


def _client_with_records(monkeypatch, names):
    c = DeadlyStreamClient()
    recs = [{"name": "Download", "url": f"https://x/{n}", "record_id": str(i)} for i, n in enumerate(names)]
    monkeypatch.setattr(c, "list_download_records", lambda *a, **k: recs)
    fetched = []

    def fake_download(url, dest_dir, file_id, **kw):
        name = url.rsplit("/", 1)[1]
        if kw.get("keep_names") and not download_name_matches(name, kw["keep_names"],
                                                              strict=kw.get("strict_keep", False)):
            return None                                   # skipped after the headers, as in real life
        fetched.append(name)
        f = Path(dest_dir) / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        return f

    monkeypatch.setattr(c, "_download_from_url", fake_download)
    return c, fetched


def test_only_the_exact_file_is_downloaded_not_the_add_ons(tmp_path, monkeypatch):
    c, fetched = _client_with_records(monkeypatch, FAMILY)
    out = c.download_all_files("723", tmp_path, slug="hq", keep_names=KEEP)
    assert fetched == ["HQSkyboxesII_K1.7z"]              # nothing else was fetched
    assert [p.name for p in out] == ["HQSkyboxesII_K1.7z"]


def test_a_loosely_named_guide_entry_still_finds_its_file(tmp_path, monkeypatch):
    c, fetched = _client_with_records(monkeypatch, ["HD_Twilek_Female_v2.rar", "Unrelated.zip"])
    out = c.download_all_files("1", tmp_path, slug="t", keep_names=["hd_twilek_female.rar"])
    assert [p.name for p in out] == ["HD_Twilek_Female_v2.rar"]


# ------------------------------------------------------- cache left by an interrupted run

def _skybox_pipeline(tmp_path):
    m = _mod()
    m.file_id, m.slug, m.name = "723", "high-quality-skyboxes-ii", "High Quality Skyboxes II"
    m.instructions = "Download Instructions simply download the 'HQSkyboxesII_K1.7z' file."
    p = _pipeline(tmp_path, [m])
    assert p.mods[0].build_mod.directives.download_only == KEEP
    return p


def test_leftover_add_ons_without_the_wanted_file_are_not_taken_for_the_mod(tmp_path):
    """The real failure: three add-on archives from an interrupted download."""
    p = _skybox_pipeline(tmp_path)
    d = p._mod_dir(p.mods[0])
    d.mkdir(parents=True)
    for n in ("HQSkyboxesII_K1_BOSSR.7z", "HQSkyboxesII_K1_OrdMandell.7z", "HQSkyboxesII_K1_Yavin4.7z"):
        (d / n).write_bytes(b"7z")
    assert p._cached_for(p.mods[0], d) == []                # download it again, properly


def test_the_wanted_file_being_present_counts_as_cached(tmp_path):
    p = _skybox_pipeline(tmp_path)
    d = p._mod_dir(p.mods[0])
    d.mkdir(parents=True)
    for n in ("HQSkyboxesII_K1_BOSSR.7z", "HQSkyboxesII_K1.7z"):
        (d / n).write_bytes(b"7z")
    assert [c.name for c in p._cached_for(p.mods[0], d)] == ["HQSkyboxesII_K1.7z"]


def test_a_recorded_finished_download_is_trusted_as_it_is(tmp_path):
    p = _skybox_pipeline(tmp_path)
    d = p._mod_dir(p.mods[0])
    d.mkdir(parents=True)
    (d / "Renamed By The Author.7z").write_bytes(b"7z")
    p._write_cache_manifest(d, [d / "Renamed By The Author.7z"])
    assert [c.name for c in p._cached_for(p.mods[0], d)] == ["Renamed By The Author.7z"]


# ------------------------------------------------------------------------- Nexus

def test_nexus_prefers_the_exact_named_file():
    files = [
        {"file_id": 1, "file_name": "HQSkyboxesII_K1_Yavin4.7z", "category_name": "OPTIONAL", "uploaded_timestamp": 9},
        {"file_id": 2, "file_name": "HQSkyboxesII_K1.7z", "category_name": "MAIN", "uploaded_timestamp": 1},
    ]
    assert [f["file_id"] for f in nexus.pick_files(files, keep_names=KEEP)] == [2]
