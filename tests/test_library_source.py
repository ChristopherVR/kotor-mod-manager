"""The Library links each installed mod to the page it is really hosted on."""
from types import SimpleNamespace

from backend import library_routes as lr
from backend.models import installed_mod_to_dict
from installer.mod_manager import InstalledMod, _mod_from_dict


def _mod(**kw):
    base = dict(id="m1", name="Mod", game="KOTOR1", source_type="build", source_ref="42",
                install_method="LOOSE", deploy_kind="loose", state="enabled",
                enabled=True, load_order=0, build_key="k1_full")
    base.update(kw)
    return InstalledMod(**base)


def test_a_recorded_host_and_url_are_used_as_is():
    m = _mod(source_ref="guide:10", source_host="nexus",
             source_url="https://www.nexusmods.com/kotor/mods/1365")
    assert lr._source_of(m) == ("nexus", "https://www.nexusmods.com/kotor/mods/1365")


def test_older_numeric_records_are_deadlystream():
    assert lr._source_of(_mod(source_ref="1258")) == ("deadlystream", "")


def test_older_guide_records_are_looked_up_in_the_loaded_build(monkeypatch):
    build_mod = SimpleNamespace(file_id="guide:10", source_host="nexus",
                                url="https://www.nexusmods.com/kotor/mods/1365")
    monkeypatch.setattr(lr, "_state", SimpleNamespace(loaded_mods={"k1_full": [build_mod]}))
    assert lr._source_of(_mod(source_ref="guide:10")) == (
        "nexus", "https://www.nexusmods.com/kotor/mods/1365")


def test_unknown_source_gives_no_link(monkeypatch):
    monkeypatch.setattr(lr, "_state", SimpleNamespace(loaded_mods={}))
    monkeypatch.setattr(lr, "_build_entry", lambda *a: None)
    assert lr._source_of(_mod(source_ref="guide:10")) == ("", "")
    assert lr._source_of(_mod(source_type="import", source_ref="")) == ("", "")


def test_the_api_carries_host_and_url():
    m = _mod(source_host="mega", source_url="https://mega.nz/file/x#y")
    d = installed_mod_to_dict(m, source=lr._source_of(m))
    assert d["source_host"] == "mega" and d["source_url"] == "https://mega.nz/file/x#y"


def test_manifests_written_before_this_still_load():
    d = {"id": "m1", "name": "Mod", "game": "KOTOR1", "source_type": "build",
         "source_ref": "42", "install_method": "LOOSE", "deploy_kind": "loose",
         "state": "enabled", "enabled": True, "load_order": 0}
    assert _mod_from_dict(d).source_host == ""
