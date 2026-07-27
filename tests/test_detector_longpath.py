"""Detection must not have a MAX_PATH blind spot.

Windows stops enumerating below 260 characters silently rather than raising, so
a mod wrapped in a few long-named folders looked empty and was reported as
needing a manual install. Effixian's Qel-Droma Robes hit this: triple-nested
under a 60-character folder name, its textures sit at 287 characters.
"""

import sys

import pytest

from installer.detector import InstallMethod, _long, detect, walk_files


def _deep_mod(tmp_path, depth=3, folder="A Rather Long Mod Folder Name For KOTOR Robes"):
    """
    Build a mod nested deep enough to cross MAX_PATH.

    Creating the fixture needs the same long-path handling as reading it: plain
    open() past 260 characters fails with FileNotFoundError on Windows, which is
    the very limitation under test.
    """
    d = tmp_path
    for _ in range(depth):
        d = d / folder
    _long(d).mkdir(parents=True, exist_ok=True)
    for name, body in (("PMBI55.tga", b"texture"),
                       ("g_a_jedirobe06.uti", b"item"),
                       ("readme.txt", b"read me")):
        (_long(d) / name).write_bytes(body)
    return d


def test_files_past_max_path_are_still_found(tmp_path):
    leaf = _deep_mod(tmp_path)
    assert len(str(leaf)) > 200  # the case we care about
    found = {rel.name for _abs, rel in walk_files(tmp_path)}
    assert "PMBI55.tga" in found
    assert "g_a_jedirobe06.uti" in found


def test_a_deeply_nested_mod_is_installable_not_manual(tmp_path):
    _deep_mod(tmp_path)
    plan = detect(tmp_path)
    assert plan.method is not InstallMethod.MANUAL
    dests = [m.dest_relative for m in plan.file_mappings]
    assert "Override/PMBI55.tga" in dests
    assert "Override/g_a_jedirobe06.uti" in dests


def test_walk_files_returns_usable_relative_paths(tmp_path):
    _deep_mod(tmp_path, depth=2)
    for abs_path, rel in walk_files(tmp_path):
        assert not str(rel).startswith("\\\\?\\")
        assert abs_path.name == rel.name


@pytest.mark.skipif(sys.platform != "win32", reason="MAX_PATH is Windows-only")
def test_plain_rglob_would_have_missed_it(tmp_path):
    """
    Documents the bug: the naive traversal genuinely loses these files, so this
    is not a theoretical guard.

    Depth is derived from the temp directory's own length rather than hardcoded,
    because pytest's tmp_path varies between machines and a fixed nesting can
    land under 260 characters, making the assertion pass for the wrong reason.
    """
    folder = "A Rather Long Mod Folder Name For KOTOR Robes"
    depth = (280 - len(str(tmp_path))) // (len(folder) + 1) + 1
    leaf = _deep_mod(tmp_path, depth=max(depth, 2), folder=folder)
    assert len(str(leaf / "PMBI55.tga")) > 260, "fixture failed to cross MAX_PATH"

    plain = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    walked = {rel.name for _a, rel in walk_files(tmp_path)}
    assert "PMBI55.tga" in walked
    assert "PMBI55.tga" not in plain


def test_shallow_mods_still_work(tmp_path):
    (tmp_path / "n_carth.tga").write_bytes(b"x")
    plan = detect(tmp_path)
    assert plan.method is not InstallMethod.MANUAL
    assert [m.dest_relative for m in plan.file_mappings] == ["Override/n_carth.tga"]
