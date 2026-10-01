"""A mod must be listed once, however many times or in how many parts it was
recorded, and the Library's dedupe merges old duplicates without losing files."""

import pytest

from installer import mod_manager
from installer.mod_manager import GameManifest


@pytest.fixture
def store(monkeypatch):
    holder = {"m": GameManifest(game="KOTOR1")}
    monkeypatch.setattr(mod_manager, "load_manifest", lambda game: holder["m"])
    monkeypatch.setattr(mod_manager, "save_manifest",
                        lambda m: holder.__setitem__("m", m))
    return holder


def _record(game, name, files):
    for f in files:
        p = game / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f)
    return mod_manager.record_install(
        "KOTOR1", game, name=name, install_method="DIRECT_COPY",
        source_type="build", source_ref="1", deploy_kind="loose",
        plan_file_mappings=[(f, None) for f in files])


def test_recording_same_mod_twice_keeps_one_entry(store, tmp_path):
    first = _record(tmp_path, "Cool Mod", ["Override/a.2da"])
    second = _record(tmp_path, "cool mod ", ["Override/b.2da"])
    assert first.id == second.id
    assert len(store["m"].mods) == 1
    assert {f.rel_path for f in store["m"].mods[0].deployed_files} == {
        "Override/a.2da", "Override/b.2da"}


def test_dedupe_merges_existing_duplicates(store, tmp_path):
    a = _record(tmp_path, "Cool Mod", ["Override/a.2da"])
    # Simulate a pre-fix library: append a second record directly.
    b = _record(tmp_path, "Other Mod", ["Override/b.2da"])
    b.name = "Cool Mod"; b.source_ref = a.source_ref
    result = mod_manager.dedupe("KOTOR1")
    assert result["removed"] == 1
    mods = store["m"].mods
    assert len(mods) == 1 and mods[0].id == a.id
    assert {f.rel_path for f in mods[0].deployed_files} == {
        "Override/a.2da", "Override/b.2da"}
    assert mod_manager.dedupe("KOTOR1")["removed"] == 0


def test_dedupe_merges_patcher_and_loose_parts(store, tmp_path):
    a = _record(tmp_path, "Patched Mod", ["Override/a.2da"])
    b = _record(tmp_path, "Other", ["Override/b.2da"])
    b.name = "Patched Mod"; b.source_ref = a.source_ref
    b.deploy_kind = "baked"
    b.state = "baked"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 1
    (m,) = store["m"].mods
    assert m.deploy_kind == "baked" and not m.toggleable
    assert {f.rel_path for f in m.deployed_files} == {"Override/a.2da", "Override/b.2da"}


def test_same_name_different_source_same_files_is_merged(store, tmp_path):
    a = _record(tmp_path, "Texture Pack", ["Override/a.tga", "Override/b.tga"])
    b = _record(tmp_path, "Other", ["Override/a.tga", "Override/b.tga"])
    b.name = "Texture Pack"; b.source_ref = "999"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 1


def test_same_name_different_files_is_not_merged(store, tmp_path):
    _record(tmp_path, "Texture Pack", ["Override/a.tga"])
    b = _record(tmp_path, "Other", ["Override/b.tga"])
    b.name = "Texture Pack"; b.source_ref = "999"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 0
    assert len(store["m"].mods) == 2


def test_same_files_but_different_content_is_not_merged(store, tmp_path):
    _record(tmp_path, "Texture Pack", ["Override/a.tga"])
    b = _record(tmp_path, "Other", ["Override/a.tga"])
    b.name = "Texture Pack"; b.source_ref = "999"
    b.deployed_files[0].sha256 = "different"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 0


def test_one_extra_file_is_not_merged(store, tmp_path):
    _record(tmp_path, "Texture Pack", ["Override/a.tga", "Override/b.tga"])
    b = _record(tmp_path, "Other", ["Override/a.tga", "Override/b.tga", "Override/c.tga"])
    b.name = "Texture Pack"; b.source_ref = "999"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 0


def test_unmergeable_same_names_are_flagged(store, tmp_path):
    a = _record(tmp_path, "Texture Pack", ["Override/a.tga"])
    b = _record(tmp_path, "Other", ["Override/b.tga"])
    b.name = "Texture Pack"; b.source_ref = "999"
    c = _record(tmp_path, "Solo", ["Override/c.tga"])
    flagged = mod_manager.unmergeable_duplicates(store["m"].mods)
    assert flagged == {a.id, b.id} and c.id not in flagged
    assert mod_manager.dedupe("KOTOR1")["remaining"] == 2
