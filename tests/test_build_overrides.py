"""Tests for the curated build rules and the pipeline behaviours they need."""

from pathlib import Path

import pytest

from installer import build_overrides
from installer.build_directives import Directives, parse_directives
from installer.detector import InstallMethod, InstallPlan, ModFileMapping
from installer.pipeline import Pipeline
from scraper.build_scraper import BuildMod


# ---------------------------------------------------------------------------
# The curated layer
# ---------------------------------------------------------------------------

def test_curated_rules_replace_parsed_lists_rather_than_merging():
    """A curated list is the audited answer; a stray regex capture must not
    survive alongside it."""
    dirs = Directives(file_except=["a bad regex capture"])
    out = build_overrides.apply(dirs, "k1_spoilerfree", "1333")
    assert "a bad regex capture" not in out.file_except
    assert "N_AdmrlSaulKar.mdl" in out.file_except
    assert "Bugfix" in out.file_except


def test_unknown_mod_is_left_untouched():
    dirs = Directives(file_only=["keep me"])
    out = build_overrides.apply(dirs, "k1_spoilerfree", "does-not-exist")
    assert out.file_only == ["keep me"]


def test_unknown_build_is_left_untouched():
    dirs = Directives(file_only=["keep me"])
    assert build_overrides.apply(dirs, "k2_full", "1333").file_only == ["keep me"]


def test_non_deadlystream_mods_are_keyed_by_guide_position():
    """Nexus/MEGA-hosted mods carry rules even though they have no file id."""
    out = build_overrides.apply(Directives(), "k1_spoilerfree", "", guide_index=15)
    assert out.pre_install_delete == ["LSI_win01.tpc", "LSI_box01.tpc"]


def test_hq_blasters_renames_the_rifle_model_instead_of_deleting_it():
    """The guide says rename w_ionrfl_04 to w_ionrfl_004. Reading that as a
    delete list loses the model and breaks the mod."""
    # The guide's own wording, verbatim - the paraphrase does not reproduce the
    # misreading this rule exists to correct.
    raw = parse_directives(
        "Extract the mod, navigate to the 'TSLPatchdata' folder, and delete the "
        "file 'keblastore.utm'. Run the installer—it will give you a single "
        "error, this is intended. After the install has completed, rename the "
        "files 'w_ionrfl_04.mdl' and 'w_ionrfl_04.mdx' to 'w_ionrfl_004.mdl' and "
        "'w_ionrfl_004.mdx'. Delete the following files from your override "
        "directory: w_rptnblstr_004.mdl, w_rptnblstr_004.mdx, "
        "w_blstrpstl_006.mdl, w_blstrpstl_006.mdx and g1_w_rptnblstr01.uti")
    # Without the curated rule the renamed-to file is on the delete list.
    assert "w_ionrfl_004.mdl" in raw.post_install_delete

    out = build_overrides.apply(raw, "k1_spoilerfree", "861")
    assert ("w_ionrfl_04.mdl", "w_ionrfl_004.mdl") in out.rename_after
    assert "w_ionrfl_004.mdl" not in out.post_install_delete
    assert "w_ionrfl_04.mdl" not in out.post_install_delete
    assert out.pre_patch_delete == ["keblastore.utm"]
    assert out.tolerate_patcher_errors


def test_jedi_tailor_does_not_install_the_brown_compatibility_patch():
    """That patch is only right with Cloaked Jedi Robes' 100% Brown option,
    which this build does not use."""
    out = build_overrides.apply(
        Directives(prefer_compatible=True, multi_run=True),
        "k1_spoilerfree", "1477")
    assert not out.prefer_compatible
    assert not out.multi_run
    assert "100% Brown" in out.file_except
    assert out.requires == ["1378"]


@pytest.mark.parametrize("file_id,expected", [
    ("723", ["m36aa_01_lm0.tga", "m36aa_01_lm1.tga", "m36aa_01_lm2.tga"]),
    ("2409", ["ii_trapkit_001.tga", "ii_trapkit_002.tga",
              "ii_trapkit_003.tga", "ii_trapkit_004.tga"]),
])
def test_delete_ranges_are_expanded_in_full(file_id, expected):
    """'delete X through Y' must cover the middle files, not just the ends."""
    out = build_overrides.apply(Directives(), "k1_spoilerfree", file_id)
    assert out.pre_install_delete == expected


def test_cutscene_filter_names_one_archive_not_two_loose_tokens():
    """download_only is OR-matched. A ["1920x1080", "30fps"] pair keeps every
    30fps variant AND every 1080p variant - four archives at 8-15 GB each."""
    from scraper.deadlystream import select_keep_matches
    variants = ["k1rs_30fps_1920x1080.7z", "k1rs_30fps_2560x1440.7z",
                "k1rs_60fps_1920x1080.7z", "k1rs_30fps_3840x2160.7z"]
    assert len(select_keep_matches(variants, ["1920x1080", "30fps"])) == 4

    keep = build_overrides.apply(Directives(), "k1_spoilerfree", "2380").download_only
    assert select_keep_matches(variants, keep) == ["k1rs_30fps_1920x1080.7z"]


def test_kebla_yurt_deletes_the_txi_alongside_the_texture():
    out = build_overrides.apply(Directives(), "k1_spoilerfree", "2471")
    assert out.pre_install_delete == ["N_CommF02.tga", "N_CommF02.txi"]


def test_galaxy_map_installs_its_base_mod_rather_than_asking_the_player():
    """The guide's non-widescreen path is 'install the base mod only', which is
    automatable - so this must not sit as a manual step."""
    out = build_overrides.apply(Directives(), "k1_spoilerfree", "", guide_index=174)
    assert not out.manual_only
    assert "HR Menu Patch" in out.file_except


def test_steam_breaking_4gb_patcher_is_forced_to_manual():
    out = build_overrides.apply(Directives(), "k1_spoilerfree", "", guide_index=180)
    assert out.manual_only
    assert "Steam" in out.manual_reason


def test_duplicate_texture_cleanup_sorts_last():
    cleanup = build_overrides.apply(Directives(), "k1_spoilerfree", "", guide_index=175)
    k1cp = build_overrides.apply(Directives(), "k1_spoilerfree", "1258")
    assert cleanup.layer > k1cp.layer
    assert cleanup.layer == max(
        build_overrides.apply(Directives(), "k1_spoilerfree", fid).layer
        for fid in build_overrides.K1_SPOILERFREE
        if not fid.startswith("guide:")
    ) or cleanup.layer == build_overrides.LAYER_CLEANUP


def test_curated_notes_reach_the_player():
    out = build_overrides.apply(Directives(), "k1_spoilerfree", "1815")
    assert out.no_overwrite
    assert any("do not overwrite" in n.lower() for n in out.manual_notes)


def test_every_declared_prerequisite_exists_in_the_table():
    """A typo'd prerequisite would silently hold a mod back forever."""
    table = build_overrides.K1_SPOILERFREE
    for mod_id, rule in table.items():
        for req in rule.get("requires", []):
            assert req in table, f"{mod_id} requires unknown entry {req}"


# ---------------------------------------------------------------------------
# Pipeline behaviours
# ---------------------------------------------------------------------------

def _mod(file_id="1", name="Test Mod", guide_index=1, build_key="k1_spoilerfree"):
    return BuildMod(
        install_order=guide_index, file_id=file_id, slug="slug", name=name,
        url="", game="KOTOR1", section="", category="", note="",
        option_hint="", install_method_hint="", build_key=build_key,
        guide_index=guide_index,
    )


def _pipeline(mods, game_path, tmp_path):
    return Pipeline(mods=mods, game_path=game_path, download_dir=tmp_path / "dl",
                    client=None, record_to_library=False)


def test_layer_order_puts_the_cleanup_step_after_the_community_patch(tmp_path):
    # Deliberately listed in the wrong order.
    cleanup = _mod(file_id="x", name="Remove Duplicate TGA/TPC", guide_index=175)
    k1cp = _mod(file_id="1258", name="KOTOR Community Patch", guide_index=6)
    p = _pipeline([cleanup, k1cp], tmp_path, tmp_path)
    p._apply_layer_order()
    assert [pm.build_mod.name for pm in p.mods][0] == "KOTOR Community Patch"


def test_a_mod_is_held_back_when_its_prerequisite_is_absent(tmp_path):
    tailor = _mod(file_id="1477", name="JC's Jedi Tailor", guide_index=52)
    p = _pipeline([tailor], tmp_path, tmp_path)
    assert p._unmet_requirements(p.mods[0]) == ["1378"]


def test_a_prerequisite_queued_in_the_same_run_counts_as_met(tmp_path):
    robes = _mod(file_id="1378", name="Cloaked Jedi Robes", guide_index=51)
    tailor = _mod(file_id="1477", name="JC's Jedi Tailor", guide_index=52)
    p = _pipeline([robes, tailor], tmp_path, tmp_path)
    target = next(pm for pm in p.mods if pm.build_mod.file_id == "1477")
    assert p._unmet_requirements(target) == []


def test_a_failing_log_callback_never_fails_the_install(tmp_path):
    """_log runs inside the per-mod try block. A consumer that raises - e.g.
    print() hitting UnicodeEncodeError on a cp1252 console - must not take the
    mod down with it."""
    p = _pipeline([_mod()], tmp_path, tmp_path)

    def exploding_log(msg, tag=""):
        raise UnicodeEncodeError("charmap", "──", 0, 2, "boom")

    p._on_log = exploding_log
    p._log("── [1] Some Mod")  # must not raise


def test_rename_after_moves_the_file_in_override(tmp_path):
    override = tmp_path / "Override"
    override.mkdir()
    (override / "w_ionrfl_04.mdl").write_text("model")
    p = _pipeline([_mod()], tmp_path, tmp_path)
    p._apply_rename_after(Directives(
        rename_after=[("w_ionrfl_04.mdl", "w_ionrfl_004.mdl")]))
    assert not (override / "w_ionrfl_04.mdl").exists()
    assert (override / "w_ionrfl_004.mdl").read_text() == "model"


def test_rename_after_ignores_path_traversal(tmp_path):
    (tmp_path / "Override").mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("keep")
    p = _pipeline([_mod()], tmp_path, tmp_path)
    p._apply_rename_after(Directives(rename_after=[("../secret.txt", "stolen.mdl")]))
    assert outside.read_text() == "keep"


def test_pre_patch_delete_strips_the_file_from_the_mod_folder(tmp_path):
    mod_root = tmp_path / "mod" / "tslpatchdata"
    mod_root.mkdir(parents=True)
    (mod_root / "keblastore.utm").write_text("x")
    (mod_root / "keep.utm").write_text("x")
    p = _pipeline([_mod()], tmp_path, tmp_path)
    pm = p.mods[0]
    pm.extracted_paths = [tmp_path / "mod"]
    p._apply_pre_patch_delete(pm, Directives(pre_patch_delete=["keblastore.utm"]))
    assert not (mod_root / "keblastore.utm").exists()
    assert (mod_root / "keep.utm").exists()


def test_main_archive_installs_before_its_patch(tmp_path):
    """JAO downloaded as [saber_replacement, main]. Installing the patch first
    fails: it edits a .utc the main mod has not written yet."""
    p = _pipeline([_mod()], tmp_path, tmp_path)
    pm = p.mods[0]
    pm.archive_paths = [tmp_path / "JAO_Saber_Replacement.7z", tmp_path / "JAO.7z"]
    p._order_main_before_patch(pm)
    assert [a.name for a in pm.archive_paths] == ["JAO.7z", "JAO_Saber_Replacement.7z"]


def test_ordering_left_alone_when_every_archive_is_a_main(tmp_path):
    p = _pipeline([_mod()], tmp_path, tmp_path)
    pm = p.mods[0]
    original = [tmp_path / "PartTwo.7z", tmp_path / "PartOne.7z"]
    pm.archive_paths = list(original)
    p._order_main_before_patch(pm)
    assert pm.archive_paths == original


def test_ordering_left_alone_for_a_single_archive(tmp_path):
    p = _pipeline([_mod()], tmp_path, tmp_path)
    pm = p.mods[0]
    pm.archive_paths = [tmp_path / "OnlyPatch.7z"]
    p._order_main_before_patch(pm)
    assert [a.name for a in pm.archive_paths] == ["OnlyPatch.7z"]


@pytest.mark.parametrize("name,is_patch", [
    ("K1CP Patch", True), ("HR Menu Patch", True), ("SAWL Patch", True),
    ("JAO_Saber_Replacement", True), ("Taris Reskin Patch", True),
    ("JAO", False), ("Ultimate Korriban High Resolution", False),
])
def test_patch_detection_needs_a_whole_word(name, is_patch):
    """Whole-word matching, so 'Replacement' counts but a name merely containing
    the letters does not."""
    assert Pipeline._looks_like_patch(name) is is_patch


def test_a_mod_whose_archives_all_look_like_patches_keeps_its_order(tmp_path):
    """K1CP's own archives are 'K1_Community_Patch', 'K1CP_..._Hotfix' and
    'K1CP Patch' - every one trips the patch marker. Name-level classification
    cannot separate them, so the guard is: reorder only when the set splits
    cleanly into main(s) and patch(es). Otherwise leave the given order alone."""
    p = _pipeline([_mod()], tmp_path, tmp_path)
    pm = p.mods[0]
    original = [tmp_path / "K1_Community_Patch_v1.10.0.zip",
                tmp_path / "K1CP_v1.10.1_Starmap_Hotfix.zip",
                tmp_path / "K1CP Patch.rar"]
    pm.archive_paths = list(original)
    p._order_main_before_patch(pm)
    assert pm.archive_paths == original


def test_pre_delete_also_excludes_the_mods_own_copy(tmp_path):
    """Quanon's HK-47 ships PO_phk47.tga and the guide says delete it before
    moving to Override. Clearing Override alone is useless - the copy step puts
    the mod's own PO_phk47.tga right back."""
    plan = InstallPlan(
        method=InstallMethod.OVERRIDE_COPY, mod_root=tmp_path,
        file_mappings=[
            ModFileMapping(source=tmp_path / "PO_phk47.tga",
                           dest_relative="Override/PO_phk47.tga"),
            ModFileMapping(source=tmp_path / "P_hk47.tga",
                           dest_relative="Override/P_hk47.tga"),
        ],
    )
    p = _pipeline([_mod()], tmp_path, tmp_path)
    p._apply_file_selection(plan, Directives(pre_install_delete=["PO_phk47.tga"]))
    assert [m.dest_relative for m in plan.file_mappings] == ["Override/P_hk47.tga"]


def test_pre_delete_exclusion_leaves_a_rename_source_alone(tmp_path):
    """NPC Clothing M deletes N_CommM08.tga but then recreates it from
    N_CommM0801, so the rename source must survive the exclusion."""
    plan = InstallPlan(
        method=InstallMethod.OVERRIDE_COPY, mod_root=tmp_path,
        file_mappings=[
            ModFileMapping(source=tmp_path / "N_CommM08.tga",
                           dest_relative="Override/N_CommM08.tga"),
            ModFileMapping(source=tmp_path / "N_CommM0801.tga",
                           dest_relative="Override/N_CommM0801.tga"),
        ],
    )
    p = _pipeline([_mod()], tmp_path, tmp_path)
    dirs = Directives(pre_install_delete=["N_CommM08.tga"],
                      rename_copies=[("N_CommM0801", "N_CommM08.tga")])
    p._apply_file_selection(plan, dirs)
    p._apply_renames(plan, dirs)
    dests = [m.dest_relative for m in plan.file_mappings]
    assert "Override/N_CommM0801.tga" in dests
    assert "Override/N_CommM08.tga" in dests  # recreated from the 0801 copy


def test_no_overwrite_keeps_files_an_earlier_mod_installed(tmp_path):
    override = tmp_path / "Override"
    override.mkdir()
    (override / "taken.tpc").write_text("from an earlier mod")
    plan = InstallPlan(
        method=InstallMethod.OVERRIDE_COPY, mod_root=tmp_path,
        file_mappings=[
            ModFileMapping(source=tmp_path / "taken.tpc", dest_relative="Override/taken.tpc"),
            ModFileMapping(source=tmp_path / "fresh.tpc", dest_relative="Override/fresh.tpc"),
        ],
    )
    skipped = Pipeline._apply_no_overwrite(plan, Directives(no_overwrite=True), tmp_path)
    assert skipped == 1
    assert [m.dest_relative for m in plan.file_mappings] == ["Override/fresh.tpc"]


def test_no_overwrite_is_off_by_default(tmp_path):
    plan = InstallPlan(
        method=InstallMethod.OVERRIDE_COPY, mod_root=tmp_path,
        file_mappings=[ModFileMapping(source=tmp_path / "a.tpc",
                                      dest_relative="Override/a.tpc")],
    )
    assert Pipeline._apply_no_overwrite(plan, Directives(), tmp_path) == 0
    assert len(plan.file_mappings) == 1
