"""Conflict detection and bulk resolution.

A finished curated build reports hundreds of file overlaps that are working
exactly as the guide intended, so the value of this list depends entirely on it
not crying wolf. These tests pin the cases that made it noisy.
"""

import pytest

from installer import mod_manager
from installer.mod_manager import (DeployedFile, DeployKind, GameManifest,
                                   InstalledMod, _logical_id, compute_conflicts,
                                   resolve_conflicts)


def _mod(name, mod_id, files, *, source_ref="", build_key="k1_spoilerfree",
         enabled=True, load_order=0, incompat=None):
    return InstalledMod(
        id=mod_id, name=name, game="KOTOR1", source_type="build",
        source_ref=source_ref or mod_id, install_method="DIRECT_COPY",
        deploy_kind=DeployKind.LOOSE.value, state="enabled", enabled=enabled,
        load_order=load_order, build_key=build_key,
        deployed_files=[DeployedFile(rel_path=f, sha256="x", size=1) for f in files],
        incompatibilities=incompat or [],
    )


@pytest.fixture
def manifest(monkeypatch):
    """An in-memory manifest so tests never touch the real library."""
    store = {"m": GameManifest(game="KOTOR1")}
    monkeypatch.setattr(mod_manager, "load_manifest", lambda game: store["m"])
    monkeypatch.setattr(mod_manager, "save_manifest",
                        lambda m: store.__setitem__("m", m))
    return store["m"]


# ---------------------------------------------------------------------------
# Identity - the self-conflict bug
# ---------------------------------------------------------------------------

def test_the_same_mod_under_two_source_refs_is_one_identity():
    """Installed once via a build and again via another, a mod gets different
    source_refs. Keyed on those it looked like two mods and conflicted with
    itself: 'Blaster Visual Effects is incompatible with Blaster Visual
    Effects'."""
    a = _mod("Blaster Visual Effects", "id-a", [], source_ref="1271")
    b = _mod("Blaster Visual Effects", "id-b", [], source_ref="guide:106")
    assert _logical_id(a) == _logical_id(b)


def test_a_mod_never_conflicts_with_itself(manifest):
    manifest.mods = [
        _mod("Blaster Visual Effects", "id-a", ["Override/fx.tga"],
             source_ref="1271", incompat=["Blaster Visual Effects"]),
        _mod("Blaster Visual Effects", "id-b", ["Override/fx.tga"],
             source_ref="guide:106", incompat=["Blaster Visual Effects"]),
    ]
    assert compute_conflicts("KOTOR1") == []


def test_two_genuinely_different_mods_still_conflict(manifest):
    manifest.mods = [
        _mod("Blaster Visual Effects", "a", ["Override/x.tga"],
             incompat=["Realistic Visual Effects"]),
        _mod("Realistic Visual Effects", "b", ["Override/y.tga"]),
    ]
    declared = [c for c in compute_conflicts("KOTOR1") if c["type"] == "declared"]
    assert len(declared) == 1


# ---------------------------------------------------------------------------
# Wording - the duplicated-names bug
# ---------------------------------------------------------------------------

def test_the_winner_is_not_also_listed_as_shadowed(manifest):
    """The loser list filtered on record id, so a winner with several records
    reappeared in its own shadowed list, producing '"KOTOR Community Patch"
    wins and the version from "KOTOR Community Patch", "KOTOR Community
    Patch" ... is shadowed'."""
    # Different build keys so this takes the cross-build path, which is the one
    # that actually enumerates the shadowed mods.
    manifest.mods = [
        _mod("KOTOR Community Patch", "k1", ["Override/a.2da"],
             source_ref="1258", build_key="k1_full", load_order=0),
        _mod("KOTOR Community Patch", "k2", ["Override/a.2da"],
             source_ref="1258", build_key="k1_full", load_order=1),
        _mod("Character Textures & Model Fixes", "c1", ["Override/a.2da"],
             source_ref="2659", build_key="k1_spoilerfree", load_order=2),
    ]
    c = compute_conflicts("KOTOR1")[0]
    desc = c["description"]
    assert desc.count("KOTOR Community Patch") == 1
    assert desc.count("Character Textures & Model Fixes") == 1


# ---------------------------------------------------------------------------
# Severity - curated overlaps are the design
# ---------------------------------------------------------------------------

def test_overlap_between_curated_mods_is_informational(manifest):
    manifest.mods = [
        _mod("HD Astromech Droids", "a", ["Override/c.tga"], build_key="k1_full"),
        _mod("Character Textures", "b", ["Override/c.tga"],
             build_key="k1_spoilerfree", load_order=1),
    ]
    assert compute_conflicts("KOTOR1")[0]["severity"] == "info"


def test_overlap_with_a_hand_imported_mod_is_still_a_warning(manifest):
    """An imported mod clashing with a build mod is a genuine surprise - the
    build never planned for it, so this one must not be silenced."""
    manifest.mods = [
        _mod("HD Astromech Droids", "a", ["Override/c.tga"]),
        _mod("My Custom Reskin", "b", ["Override/c.tga"], build_key=None, load_order=1),
    ]
    assert compute_conflicts("KOTOR1")[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# Bulk resolution
# ---------------------------------------------------------------------------

def test_dismiss_hides_conflicts_and_undismiss_restores_them(manifest):
    manifest.mods = [
        _mod("A", "a", ["Override/f.tga"]),
        _mod("B", "b", ["Override/f.tga"], load_order=1),
    ]
    ids = [c["id"] for c in compute_conflicts("KOTOR1")]
    assert ids

    resolve_conflicts("KOTOR1", ids, "dismiss")
    assert compute_conflicts("KOTOR1") == []

    resolve_conflicts("KOTOR1", ids, "undismiss")
    assert len(compute_conflicts("KOTOR1")) == len(ids)


def test_declared_conflicts_are_never_auto_resolved(manifest):
    """Which side of a declared incompatibility to keep is a judgement call, so
    bulk disabling must refuse rather than silently pick one."""
    manifest.mods = [
        _mod("A", "a", ["Override/x.tga"], incompat=["Totally Other Mod"]),
        _mod("Totally Other Mod", "b", ["Override/y.tga"]),
    ]
    declared = [c["id"] for c in compute_conflicts("KOTOR1") if c["type"] == "declared"]
    out = resolve_conflicts("KOTOR1", declared, "disable_losers")
    assert out["disabled"] == []
    assert out["skipped"] and "manual" in out["skipped"][0]["reason"]


def test_declared_conflicts_report_the_files_both_mods_write(manifest):
    """Without the overlap there is no way to judge a declared incompatibility:
    the readme says 'incompatible' but not what actually collides."""
    manifest.mods = [
        _mod("Blaster Visual Effects", "a",
             ["Override/fx_a.tga", "Override/shared.tga"],
             incompat=["Realistic Visual Effects"]),
        _mod("Realistic Visual Effects", "b",
             ["Override/fx_b.tga", "Override/shared.tga"]),
    ]
    declared = [c for c in compute_conflicts("KOTOR1") if c["type"] == "declared"][0]
    assert declared["shared_files"] == ["Override/shared.tga"]
    assert declared["shared_file_count"] == 1


def test_a_declared_conflict_with_no_file_overlap_reports_zero(manifest):
    """A behavioural warning rather than a file clash - worth distinguishing so
    the player is not sent hunting for a collision that is not on disk."""
    manifest.mods = [
        _mod("A", "a", ["Override/only_a.tga"], incompat=["Totally Other Mod"]),
        _mod("Totally Other Mod", "b", ["Override/only_b.tga"]),
    ]
    declared = [c for c in compute_conflicts("KOTOR1") if c["type"] == "declared"][0]
    assert declared["shared_files"] == []
    assert declared["shared_file_count"] == 0


def test_shared_file_list_is_capped_but_the_count_is_not(manifest):
    files = [f"Override/f{i}.tga" for i in range(80)]
    manifest.mods = [
        _mod("A", "a", files, incompat=["Totally Other Mod"]),
        _mod("Totally Other Mod", "b", files),
    ]
    declared = [c for c in compute_conflicts("KOTOR1") if c["type"] == "declared"][0]
    assert len(declared["shared_files"]) == 50
    assert declared["shared_file_count"] == 80


@pytest.mark.parametrize("a,b,is_addon", [
    ("Cloaked Jedi Robes", "HD Robe Icons for JC's Cloaked Jedi Robes", True),
    ("Hi-Res Ebon Hawk", "Ebon Hawk Repairs Patch for Hi-Res Ebon Hawk", True),
    ("HD Darth Malak", "CineMalak - HD Darth Malak", True),
    # Two genuinely separate mods that merely share a couple of words.
    ("Blaster Visual Effects", "Realistic Visual Effects", False),
    ("HD Astromech Droids", "Protocol Droids HD", False),
])
def test_addon_naming_is_recognised_without_swallowing_similar_names(a, b, is_addon):
    from installer.mod_manager import _is_addon_of
    assert _is_addon_of(a, b) is is_addon
    assert _is_addon_of(b, a) is is_addon      # order must not matter


def test_an_addon_is_not_reported_as_incompatible_with_what_it_extends(manifest):
    """The icon pack exists to replace the robe mod's icons. A readme scanner
    reading 'for Cloaked Jedi Robes' as an incompatibility gets the
    relationship exactly backwards."""
    manifest.mods = [
        _mod("Cloaked Jedi Robes", "a", ["Override/ia_kghtrobe_001.tpc"],
             incompat=["HD Robe Icons for JC's Cloaked Jedi Robes"]),
        _mod("HD Robe Icons for JC's Cloaked Jedi Robes", "b",
             ["Override/ia_kghtrobe_001.tpc"], load_order=1),
    ]
    assert [c for c in compute_conflicts("KOTOR1") if c["type"] == "declared"] == []


def test_participants_say_whether_they_can_be_switched_off(manifest):
    """Patcher mods bake into shared files. Without this the UI offers a
    Disable button that always fails with not_toggleable."""
    baked = _mod("Cloaked Jedi Robes", "a", [])
    baked.deploy_kind = DeployKind.BAKED.value
    baked.baked_files = []
    manifest.mods = [
        baked,
        _mod("Some Texture Mod", "b", ["Override/x.tga"], incompat=["Cloaked Jedi Robes"]),
    ]
    for c in compute_conflicts("KOTOR1"):
        for p in c["participants"]:
            assert "toggleable" in p
            if p["mod_name"] == "Cloaked Jedi Robes":
                assert p["toggleable"] is False


def test_an_unknown_action_is_rejected(manifest):
    with pytest.raises(ValueError):
        resolve_conflicts("KOTOR1", ["x"], "delete_everything")


def test_dismissals_survive_a_manifest_round_trip(manifest):
    manifest.mods = [
        _mod("A", "a", ["Override/f.tga"]),
        _mod("B", "b", ["Override/f.tga"], load_order=1),
    ]
    ids = [c["id"] for c in compute_conflicts("KOTOR1")]
    resolve_conflicts("KOTOR1", ids, "dismiss")
    assert set(mod_manager.load_manifest("KOTOR1").dismissed_conflicts) == set(ids)
