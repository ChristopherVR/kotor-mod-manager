"""
A mod with no recognised auto-install method should be flagged as a MANUAL
step the player can finish by hand - never reported as a failed install.
"""
from pathlib import Path

from installer.detector import InstallMethod, InstallPlan
from installer.pipeline import (
    ManualInstallRequired,
    ModStatus,
    Pipeline,
    PipelineMod,
)
from scraper.build_scraper import BuildMod


def _pipeline() -> Pipeline:
    return Pipeline(mods=[], game_path=Path("."), download_dir=Path("."), client=None)


def _manual_mod() -> PipelineMod:
    bm = BuildMod(
        install_order=1, file_id="123", slug="some-mod", name="Some Mod",
        url="", game="KOTOR1", section="", category="",
        note="", option_hint="", install_method_hint="", build_key="k1_full",
    )
    return PipelineMod(bm)


def test_manual_plan_raises_manual_required(tmp_path):
    pl = _pipeline()
    pm = _manual_mod()
    plan = InstallPlan(
        method=InstallMethod.MANUAL, mod_root=tmp_path,
        readme_text="Copy these files into Override.",
    )
    try:
        pl._install_one(pm, plan)
        assert False, "expected ManualInstallRequired"
    except ManualInstallRequired as m:
        assert m.mod_root == tmp_path
        assert "Override" in m.readme


def test_flag_manual_sets_status_and_notifies(tmp_path):
    events = []
    pl = _pipeline()
    pl._on_manual = lambda *a: events.append(a)
    pm = _manual_mod()

    pl._flag_manual(pm, ManualInstallRequired(tmp_path, "Read me first."))

    assert pm.status == ModStatus.MANUAL
    # status carries the folder so the UI can offer "open folder"
    assert events and events[0] == ("123", "Some Mod", str(tmp_path), "Read me first.")


def test_manual_is_not_an_error_status():
    # MANUAL must be distinct from ERROR so summaries never count it as a failure.
    assert ModStatus.MANUAL != ModStatus.ERROR
