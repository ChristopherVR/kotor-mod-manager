"""
Offline tests for the build-page instruction parser
(installer/build_directives.py).

These assert the parser turns the real kotor.neocities.org instruction text into
the right structured directives - picking the community-patch-compatible option,
preferring the *recommended* variant (not the rejected "instead" one), honouring
"download only X", selective file copy, patch-first order, and required patches.

The instruction strings below are quoted verbatim from the build pages (captured
in scripts/build_instructions.json).

Run:  python tests/test_build_directives.py
  or:  python -m pytest tests/test_build_directives.py -q
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer.build_directives import parse_directives, match_option_index, select_paths
from scraper.deadlystream import download_name_matches


def _prefers(dirs, token: str) -> bool:
    token = token.lower()
    return any(token in p.lower() for p in dirs.namespace_preferences)


def test_compatible_option_korriban():
    d = parse_directives(
        "Installation Instructions If running the Community Patch (you should be), "
        "install the Community Patch-Compatible install option; otherwise, select Basic."
    )
    assert d.prefer_compatible, "should pick the community-patch-compatible option"
    assert _prefers(d, "community patch") or _prefers(d, "compatible")
    print("PASS: Korriban prefers community-patch-compatible")


def test_compatible_option_sith_uniform():
    d = parse_directives(
        "Installation Instructions When installing, select the Community Patch-compatible "
        "installation, if using the K1CP (you should be). Ignore the other install options."
    )
    assert d.prefer_compatible
    print("PASS: Sith Uniform prefers compatible")


def test_tslrcm_compatible_hk47():
    d = parse_directives(
        "Installation Instructions Select between one of the two TSLRCM-compatible install options."
    )
    assert d.prefer_compatible
    print("PASS: Visually Repair HK-47 prefers TSLRCM-compatible")


def test_senni_vek_recommends_ambush_not_restoration():
    # The KEY bug: old heuristic picked 'restoration' from the description; the
    # guide actually RECOMMENDS the Ambush install ("Restoration ... instead").
    d = parse_directives(
        "Installation Instructions For realism I personally recommend the "
        '"Senni Vek\'s Ambush" install, but if you\'d like to remain as close to '
        "vanilla as possible, choose the Senni Vek Restoration instead."
    )
    assert d.namespace_preferences, "should capture a preference"
    assert _prefers(d, "ambush"), f"expected ambush, got {d.namespace_preferences}"
    # The rejected 'restoration instead' must NOT outrank ambush.
    first = d.namespace_preferences[0].lower()
    assert "ambush" in first or all("restoration" not in p.lower()
                                    for p in d.namespace_preferences[:1])
    print("PASS: Senni Vek prefers Ambush (recommended), not Restoration")


def test_download_only_twilek_females():
    d = parse_directives(
        "Download Instructions Download the 'hd_twilek_female.rar' file, and ignore the other versions."
    )
    assert any("hd_twilek_female" in x.lower() for x in d.download_only), d.download_only
    print("PASS: HD Twi'lek Females downloads only the named file")


def test_selective_except_jc_minor_fixes():
    d = parse_directives(
        'Installation Instructions Move everything from the Straight Fixes folder to your '
        'Override. Move everything from the "Things what bother me" folder as well, EXCEPT '
        "the files for the Sith uniform changes: N_AdmrlSaulKar.mdl, N_AdmrlSaulKar.mdx, "
        "N_SithComF.mdl, N_SithComF.mdx, N_SithComM.mdl, and N_SithComM.mdx."
    )
    names = [x.lower() for x in d.file_except]
    assert "n_admrlsaulkar.mdl" in names and "n_sithcomm.mdx" in names, d.file_except
    print("PASS: JC's Minor Fixes excludes the listed Sith uniform files")


def test_selective_only_dds_hd_visas():
    d = parse_directives(
        "Installation Instructions Only move the four .dds filetype files to your override, "
        "ignore the remainder."
    )
    assert any(".dds" in x.lower() for x in d.file_only), d.file_only
    print("PASS: HD Visas keeps only .dds files")


def test_ignore_folder_atton_scruff():
    d = parse_directives(
        "Installation Instructions Ignore the MacOS folder, only move the .TGA files."
    )
    assert any("macos" in x.lower() for x in d.file_except), d.file_except
    assert any(".tga" in x.lower() for x in d.file_only), d.file_only
    print("PASS: Atton Scruff ignores MacOS folder, keeps .tga")


def test_patch_first_ajunta_pall():
    d = parse_directives(
        "Installation Instructions For this specific mod only, the patch is actually run "
        "first! Run the patch and apply its changes, then open the main mod file."
    )
    assert d.patch_first
    print("PASS: Ajunta Pall runs the patch first")


def test_requires_patch_character_startup():
    d = parse_directives(
        instructions="",
        warnings="Usage Warning It's possible, if using auto level-up, to miss the feats "
        "to equip weapons and basic light armor while using this mod, unless you use the "
        "patch. Make sure to install it!",
    )
    assert d.requires_patch
    print("PASS: Character Startup Changes requires the patch")


def test_multi_run_tslrcm_tweak_pack():
    d = parse_directives(
        "Installation Instructions The installer for this mod will need to be run 6 times, "
        "once to install each of the options we'll be using."
    )
    assert d.multi_run
    print("PASS: TSLRCM Tweak Pack flagged multi-run")


def test_download_ignore_not_captured_as_only():
    # "Ignore the txi.rar file" must NOT become download_only (it's the opposite).
    d = parse_directives(
        "Download Instructions Ignore the txi.rar file. Installation Instructions "
        "Delete n_commm07.tga and N_CommMD01.tga."
    )
    assert not d.download_only, d.download_only
    print("PASS: 'ignore the txi.rar file' is not a download_only target")


def test_descriptive_download_mention_not_captured():
    # Descriptive prose ("the version from the 'X.rar' download") is not a directive.
    d = parse_directives(
        "Download Instructions Which version to use is up to you; the first image is the "
        'version of the texture from the "PLC_CompPnl 2026.rar" download, the second is the original.'
    )
    assert not d.download_only, d.download_only
    print("PASS: descriptive download mention not captured")


def test_do_not_download_tga_not_captured():
    d = parse_directives(
        "Download Instructions Do not download the .tga file. Installation Instructions "
        "select your preferred head texture and move the files to your override."
    )
    assert not d.download_only, d.download_only
    print("PASS: 'do not download the .tga file' not captured")


def test_match_option_index_compatible():
    d = parse_directives(
        "Installation Instructions If running the Community Patch, install the "
        "Community Patch-Compatible install option; otherwise, select Basic."
    )
    names = ["Basic", "Community Patch Compatible"]
    assert match_option_index(names, d) == 1
    print("PASS: match picks the Community Patch Compatible namespace")


def test_match_option_index_senni_vek():
    d = parse_directives(
        'Installation Instructions I personally recommend the "Senni Vek\'s Ambush" '
        "install, but choose the Senni Vek Restoration instead for vanilla."
    )
    names = ["Senni Vek Restoration", "Senni Vek's Ambush"]
    assert match_option_index(names, d) == 1, match_option_index(names, d)
    print("PASS: match picks Ambush (recommended), index 1 not 0")


def test_match_option_index_no_opinion():
    d = parse_directives("Installation Instructions Run the patcher.")
    assert match_option_index(["A", "B"], d) is None
    print("PASS: no directive -> no opinion (caller keeps default)")


def test_select_paths_except_filenames():
    d = parse_directives(
        "Move everything from the folder to your Override, EXCEPT the files for the "
        "Sith uniform changes: N_SithComM.mdl, N_SithComM.mdx."
    )
    paths = ["Things/N_SithComM.mdl", "Things/N_SithComM.mdx", "Things/MAN26aa.utc"]
    kept, dropped = select_paths(paths, d)
    assert "Things/MAN26aa.utc" in kept
    assert "Things/N_SithComM.mdl" in dropped and "Things/N_SithComM.mdx" in dropped
    print("PASS: select_paths drops the named EXCEPT files, keeps the rest")


def test_select_paths_only_extension():
    d = parse_directives("Only move the four .dds filetype files, ignore the remainder.")
    paths = ["P_VisasH01.dds", "P_VisasH01.tpc", "readme.txt"]
    kept, dropped = select_paths(paths, d)
    assert kept == ["P_VisasH01.dds"], kept
    print("PASS: select_paths keeps only .dds")


def test_select_paths_ignore_folder():
    d = parse_directives("Ignore the MacOS folder, only move the .TGA files.")
    paths = ["MacOS/foo.tga", "PFBN01.tga", "notes.txt"]
    kept, dropped = select_paths(paths, d)
    assert "PFBN01.tga" in kept
    assert "MacOS/foo.tga" in dropped  # excluded by folder even though it's .tga
    print("PASS: select_paths excludes the ignored folder")


def test_select_paths_safety_keeps_all_when_no_match():
    d = parse_directives("Only move the files from 'Jedi Robes Override'.")
    paths = ["something/else.tpc", "other.tga"]  # no 'Jedi Robes Override' folder
    kept, dropped = select_paths(paths, d)
    assert kept == paths and dropped == [], (kept, dropped)
    print("PASS: select_paths keeps all when 'only' matches nothing (safety)")


def test_download_name_matches():
    assert download_name_matches("hd_twilek_female.rar", ["hd_twilek_female.rar"])
    assert download_name_matches("HD Twilek Female", ["hd_twilek_female.rar"])
    assert not download_name_matches("hd_twilek_male.rar", ["hd_twilek_female.rar"])
    assert download_name_matches("anything", [])  # empty -> keep all
    print("PASS: download_name_matches handles names, labels, and empty filter")


def test_benign_instruction_is_empty():
    # A plain "move everything to Override" must NOT trigger selective copy etc.
    d = parse_directives(
        "Installation Instructions Move the files from the mod's Override folder to your "
        "game's override folder. Overwrite when prompted."
    )
    assert not d.file_only and not d.file_except, (d.file_only, d.file_except)
    assert not d.download_only
    print("PASS: benign instruction yields no risky directives")


def test_download_ignore_and_only_stunbaton():
    # Verbatim from the k1_full build guide for Stunbaton HD.
    d = parse_directives(
        'do not download the "stunbaton 2025" file; only download "Stun baton HD".'
    )
    assert d.download_ignore and any("stunbaton 2025" in x.lower() for x in d.download_ignore), d.download_ignore
    assert d.download_only and any("stun baton hd" in x.lower() for x in d.download_only), d.download_only
    print("PASS: Stunbaton HD sets download_ignore and download_only")


def test_download_ignore_extension_hd_malak():
    # Verbatim from the build guide for HD Darth Malak.
    d = parse_directives(
        "Download Instructions Do not download the .tga file."
    )
    assert any(".tga" in x.lower() for x in d.download_ignore), d.download_ignore
    assert not d.download_only, d.download_only
    print("PASS: HD Darth Malak sets download_ignore for .tga extension")


def test_file_except_do_not_use_content_of_folder():
    # Verbatim from Transparent Cockpit Windows TSL build guide.
    d = parse_directives(
        "DO NOT USE the content of the \"Korriban Distorted Model Fix\" folder, "
        "even if you are on the Aspyr patch!"
    )
    assert any("korriban distorted model fix" in x.lower() for x in d.file_except), d.file_except
    print("PASS: 'DO NOT USE content of folder' captured in file_except")


def test_file_except_but_not_folder():
    # Parenthetical "but NOT the X folder" exclusion.
    d = parse_directives(
        "Install all subfolders (but NOT the 'M4-78 with HQ Skyboxes II' folder!)."
    )
    assert any("m4-78" in x.lower() for x in d.file_except), d.file_except
    print("PASS: 'but NOT the X folder' captured in file_except")


if __name__ == "__main__":
    failures = 0
    tests = [
        test_compatible_option_korriban,
        test_compatible_option_sith_uniform,
        test_tslrcm_compatible_hk47,
        test_senni_vek_recommends_ambush_not_restoration,
        test_download_only_twilek_females,
        test_selective_except_jc_minor_fixes,
        test_selective_only_dds_hd_visas,
        test_ignore_folder_atton_scruff,
        test_patch_first_ajunta_pall,
        test_requires_patch_character_startup,
        test_multi_run_tslrcm_tweak_pack,
        test_match_option_index_compatible,
        test_match_option_index_senni_vek,
        test_match_option_index_no_opinion,
        test_download_ignore_not_captured_as_only,
        test_descriptive_download_mention_not_captured,
        test_do_not_download_tga_not_captured,
        test_download_ignore_and_only_stunbaton,
        test_download_ignore_extension_hd_malak,
        test_file_except_do_not_use_content_of_folder,
        test_file_except_but_not_folder,
        test_select_paths_except_filenames,
        test_select_paths_only_extension,
        test_select_paths_ignore_folder,
        test_select_paths_safety_keeps_all_when_no_match,
        test_download_name_matches,
        test_benign_instruction_is_empty,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as e:
            failures += 1
            print(f"FAIL: {fn.__name__}: {e}")
    print()
    if failures:
        print(f"{failures} test(s) FAILED")
        sys.exit(1)
    print("ALL DIRECTIVE TESTS PASSED")
