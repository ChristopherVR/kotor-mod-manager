"""Tests for the duplicate texture cleanup (build guide's mandatory final step)."""

from installer import texture_dedupe


def _touch(d, name, body="x"):
    p = d / name
    p.write_text(body)
    return p


def test_removes_the_tpc_side_and_keeps_the_tga(tmp_path):
    _touch(tmp_path, "n_carth.tga")
    _touch(tmp_path, "n_carth.tpc")
    res = texture_dedupe.dedupe(tmp_path)
    assert res.removed == ["n_carth.tpc"]
    assert (tmp_path / "n_carth.tga").exists()
    assert not (tmp_path / "n_carth.tpc").exists()
    assert res.ok


def test_leaves_unpaired_textures_alone(tmp_path):
    _touch(tmp_path, "only_tpc.tpc")
    _touch(tmp_path, "only_tga.tga")
    res = texture_dedupe.dedupe(tmp_path)
    assert res.removed == []
    assert (tmp_path / "only_tpc.tpc").exists()
    assert (tmp_path / "only_tga.tga").exists()


def test_matching_is_case_insensitive(tmp_path):
    """KOTOR mods are inconsistent about casing, so PO_Carth.tga and
    po_carth.tpc are the same texture as far as the engine is concerned."""
    _touch(tmp_path, "PO_Carth.tga")
    _touch(tmp_path, "po_carth.tpc")
    res = texture_dedupe.dedupe(tmp_path)
    assert res.removed == ["po_carth.tpc"]
    assert (tmp_path / "PO_Carth.tga").exists()


def test_dry_run_reports_without_deleting(tmp_path):
    _touch(tmp_path, "a.tga")
    _touch(tmp_path, "a.tpc")
    res = texture_dedupe.dedupe(tmp_path, dry_run=True)
    assert res.removed == ["a.tpc"]
    assert (tmp_path / "a.tpc").exists()


def test_ignores_non_texture_files(tmp_path):
    _touch(tmp_path, "script.ncs")
    _touch(tmp_path, "script.nss")
    assert texture_dedupe.dedupe(tmp_path).removed == []


def test_tga_and_dds_together_are_left_alone(tmp_path):
    """Only the .tpc side is ever removed."""
    _touch(tmp_path, "b.tga")
    _touch(tmp_path, "b.dds")
    assert texture_dedupe.dedupe(tmp_path).removed == []


def test_tpc_with_a_dds_twin_is_removed(tmp_path):
    _touch(tmp_path, "c.dds")
    _touch(tmp_path, "c.tpc")
    assert texture_dedupe.dedupe(tmp_path).removed == ["c.tpc"]
    assert (tmp_path / "c.dds").exists()


def test_tpc_with_both_twins_goes_in_one_pass(tmp_path):
    """The guide's script needs running twice for this case."""
    for n in ("d.tga", "d.dds", "d.tpc"):
        _touch(tmp_path, n)
    assert texture_dedupe.dedupe(tmp_path).removed == ["d.tpc"]
    assert texture_dedupe.dedupe(tmp_path).removed == []


def test_recognises_the_guide_step_by_name_in_every_build():
    name = "Remove Duplicate TGA/TPC , OR an .sh script for Linux users"
    assert texture_dedupe.is_cleanup_step(name)
    assert not texture_dedupe.is_cleanup_step("Ultimate Taris High Resolution")


def test_missing_override_folder_is_not_an_error(tmp_path):
    res = texture_dedupe.dedupe(tmp_path / "nope")
    assert res.removed == [] and res.ok


def test_find_duplicates_reports_each_clashing_stem_once(tmp_path):
    for n in ("x.tga", "x.tpc", "y.tga", "y.tpc", "z.tga"):
        _touch(tmp_path, n)
    assert sorted(texture_dedupe.find_duplicates(tmp_path)) == ["x", "y"]
