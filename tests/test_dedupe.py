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
    b.name = "Cool Mod"
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
    b.name = "Patched Mod"
    b.deploy_kind = "baked"
    b.state = "baked"
    assert mod_manager.dedupe("KOTOR1")["removed"] == 1
    (m,) = store["m"].mods
    assert m.deploy_kind == "baked" and not m.toggleable
    assert {f.rel_path for f in m.deployed_files} == {"Override/a.2da", "Override/b.2da"}
