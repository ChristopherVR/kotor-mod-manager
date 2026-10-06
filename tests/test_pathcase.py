"""Game-folder lookups must reuse the casing already on disk.

On a Linux (Steam Proton) install the filesystem is case-sensitive, so writing
"Override/Foo.tga" next to an existing "override/foo.tga" would leave two
competing files instead of replacing one.
"""

import pytest

from installer import pathcase
from installer.installer import _copy_files
from installer.detector import InstallMethod, InstallPlan, ModFileMapping
from installer.pathcase import CaseResolver, resolve_ci, rglob_ci

pytestmark = pytest.mark.skipif(
    not pathcase._CASE_SENSITIVE_FS, reason="only meaningful on a case-sensitive filesystem")


def test_resolve_uses_existing_casing(tmp_path):
    (tmp_path / "override").mkdir()
    (tmp_path / "override" / "foo.tga").write_bytes(b"x")
    assert resolve_ci(tmp_path, "Override/Foo.TGA") == tmp_path / "override" / "foo.tga"


def test_resolve_keeps_caller_casing_for_new_names(tmp_path):
    assert resolve_ci(tmp_path, "Override/New.tga") == tmp_path / "Override" / "New.tga"


def test_copy_overwrites_instead_of_duplicating(tmp_path):
    game = tmp_path / "game"
    (game / "override").mkdir(parents=True)
    (game / "override" / "foo.tga").write_bytes(b"old")
    src = tmp_path / "Foo.tga"
    src.write_bytes(b"new")
    plan = InstallPlan(method=InstallMethod.OVERRIDE_COPY, mod_root=tmp_path,
                       file_mappings=[ModFileMapping(source=src, dest_relative="Override/Foo.tga")])
    _copy_files(plan, game, lambda _m: None)
    assert sorted(p.name for p in game.iterdir()) == ["override"]
    assert [p.name for p in (game / "override").iterdir()] == ["foo.tga"]
    assert (game / "override" / "foo.tga").read_bytes() == b"new"


def test_resolver_remembers_files_it_just_named(tmp_path):
    r = CaseResolver(tmp_path)
    assert r.resolve("Override/A.tga") == r.resolve("override/a.TGA")


def test_rglob_ci_finds_shouting_extensions(tmp_path):
    (tmp_path / "Mod").mkdir()
    (tmp_path / "Mod" / "Setup.EXE").write_bytes(b"MZ")
    assert [p.name for p in rglob_ci(tmp_path, "*.exe")] == ["Setup.EXE"]
