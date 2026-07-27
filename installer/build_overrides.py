"""
Verified, hand-checked install rules for the curated mod builds.

Why this exists
---------------
`build_directives.parse_directives` reads the build guide's prose with regexes.
That is the right default for 190-odd mods, but prose is ambiguous and a wrong
guess here does not produce a tidy error - it produces a broken game. Auditing
the KOTOR 1 Spoiler-Free guide line by line turned up cases where the parser is
actively harmful, for example:

* High Quality Blasters: the guide says to RENAME w_ionrfl_04 to w_ionrfl_004.
  The parser read the sentence as a delete list and would have deleted both the
  original and the renamed file.
* JC's Jedi Tailor: the parser saw "compatibility patch" and would have installed
  the 100% Brown patch, which is only correct if you picked Cloaked Jedi Robes'
  100% Brown option. The guide recommends Brown-Red-Blue Alternative.
* Ranges ("delete m36aa_01_lm0 through m36aa_01_lm2") only ever yielded the
  first and last file, silently leaving the middle ones in place.

So: every entry below is transcribed from the guide by hand and supersedes the
parsed value for the fields it names. Fields it does not name keep whatever the
parser produced. Anything the guide leaves to player taste (robe colour, neck
style) is set to the guide's own stated recommendation, and anything the guide
does not state is left alone rather than guessed at.

Keys are DeadlyStream file ids. Mods hosted elsewhere use "guide:<n>", where <n>
is the mod's position in the build page, so they can carry rules even though the
app cannot download them automatically yet.

Source: https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free
"""

from dataclasses import replace

# Layer numbers mirror the guide's own ordering. They exist so a partial install
# (some mods missing) still applies what it has in the right sequence.
LAYER_FIXES        = 0    # dialogue/bugfix groundwork
LAYER_COMMUNITY    = 1    # K1CP - the master dependency for most later mods
LAYER_AREA         = 2    # area/environment texture packs
LAYER_NPC          = 3    # NPC and creature appearance
LAYER_PC           = 4    # player character cosmetics
LAYER_ANTAGONIST   = 5    # key antagonist textures
LAYER_CLOTHING     = 6    # clothing and armour
LAYER_ROBES        = 7    # the Jedi robes chain
LAYER_COMPANION    = 8    # companion appearance
LAYER_HAWK         = 9    # Ebon Hawk base textures
LAYER_SKYBOX       = 10   # skyboxes and cockpit
LAYER_EFFECTS      = 11   # beam/fire/ice effects
LAYER_UI_COSMETIC  = 12   # animated and UI cosmetics
LAYER_WEAPONS      = 13   # lightsaber and weapon appearance
LAYER_CONTENT      = 14   # gameplay and restored-content mods
LAYER_LATE         = 15   # mods that depend on earlier ones
LAYER_PATCHES      = 16   # cross-mod compatibility patch packs
LAYER_WIDESCREEN   = 17   # widescreen and menu work
LAYER_CLEANUP      = 18   # duplicate-texture cleanup, must be last


def _r(*pairs):
    """Readability helper for rename pairs."""
    return list(pairs)


# ---------------------------------------------------------------------------
# KOTOR 1 Spoiler-Free build
# ---------------------------------------------------------------------------
# Each value is a dict of Directives field names -> verified value, plus the
# optional pseudo-field "note" (free text shown to the player, never acted on).

K1_SPOILERFREE: dict[str, dict] = {

    # -- Layer 0: dialogue and bugfix groundwork ---------------------------

    # [1] dialog.tlk goes to the GAME ROOT, not Override. The guide recommends
    # the PC Response Moderation variant.
    "1313": {
        "layer": LAYER_FIXES,
        "namespace_preferences": ["PC Response Moderation", "Response Moderation"],
        "note": "dialog.tlk is replaced at the game root, not in Override.",
    },

    # [2] Ships a separate loose-file patch that must also be applied.
    "349": {"layer": LAYER_FIXES, "requires_patch": True},

    # [4] Everything from Straight Fixes / Resolution Fixes / Aesthetic
    # Improvements, plus "Things what bother me" EXCEPT the Sith uniform files.
    # The Bugfix folder is deliberately skipped - a later mod applies it.
    "1333": {
        "layer": LAYER_FIXES,
        "file_except": [
            "N_AdmrlSaulKar.mdl", "N_AdmrlSaulKar.mdx",
            "N_SithComF.mdl", "N_SithComF.mdx",
            "N_SithComM.mdl", "N_SithComM.mdx",
            "Bugfix",
        ],
    },

    # [5] The one mod where the patch runs BEFORE the main files. Only the
    # Transparent / Non-Transparent texture folders are installed; the loose
    # files sitting in the main mod folder must not be copied.
    "824": {
        "layer": LAYER_FIXES,
        "patch_first": True,
        "file_only": ["Transparent", "Non-Transparent"],
        "file_except": [],
        "note": "Patch runs first, then only the Transparent/Non-Transparent "
                "textures are copied. Files in the mod's root folder are skipped.",
    },

    # -- Layer 1: the community patch, master dependency -------------------

    # [6] K1CP. HoloPatcher, then its loose-file patch on top.
    "1258": {
        "layer": LAYER_COMMUNITY,
        "requires_patch": True,
        "note": "K1CP is the master dependency - almost every later mod's "
                "'community patch compatible' option assumes it is installed.",
    },

    "2456": {"layer": LAYER_COMMUNITY, "requires": ["1258"]},

    # [8] Main install, then re-run for the K1CP compatibility option.
    "1426": {
        "layer": LAYER_COMMUNITY,
        "requires": ["1258"],
        "multi_run_options": ["", "K1CP compatibility"],
        "multi_run": True,
        "prefer_compatible": False,
    },

    # -- Layer 2: area texture packs (Nexus-hosted) ------------------------
    # All of these want the .tpc variant, not .tga.

    "guide:9":  {"layer": LAYER_AREA, "download_only": ["tpc"], "requires_patch": True,
                 "note": "Download the .tpc variant. The 'requires Kexikus's "
                         "skyboxes' warning is fine - HQ Skyboxes II is installed later."},
    "guide:10": {"layer": LAYER_AREA, "download_only": ["tpc"]},
    "guide:11": {"layer": LAYER_AREA, "download_only": ["tpc"]},
    "guide:12": {"layer": LAYER_AREA, "download_only": ["tpc"]},
    "guide:13": {"layer": LAYER_AREA, "download_only": ["tpc"]},
    "guide:14": {"layer": LAYER_AREA, "download_only": ["tpc"]},

    # [15] Ultimate Taris - two files must go before the copy, and the guide
    # notes visual bugs unless Quanon's Taris reskin (entry 91) is also used.
    "guide:15": {
        "layer": LAYER_AREA,
        "download_only": ["tpc"],
        "pre_install_delete": ["LSI_win01.tpc", "LSI_box01.tpc"],
        "note": "Known visual bugs unless Taris Reskin (entry 91) is also installed.",
    },

    # [16] Ultimate Character Overhaul - 2x .tpc build, patches come later (176).
    "guide:16": {
        "layer": LAYER_AREA,
        "download_only": ["2x", "tpc"],
        "note": "Main package only - the UCO compatibility patches are entry 176.",
    },

    "guide:17": {
        "layer": LAYER_AREA,
        "download_only": ["tpc"],
        "pre_install_delete": ["LUN_blst01.tpc", "LUN_blst02.tpc"],
    },

    "guide:18": {"layer": LAYER_AREA, "note": "Download and install both files."},
    "guide:19": {"layer": LAYER_AREA},

    # -- Layer 3-4: NPC and player cosmetics -------------------------------

    "2013": {"layer": LAYER_UI_COSMETIC},

    # [21] Optional green KOTOR 2-style specialty cards - guide leaves it to
    # taste, so the optional folder is not auto-applied.
    "1361": {"layer": LAYER_UI_COSMETIC, "file_except": ["green"],
             "note": "The 'green' KOTOR 2-style card folder is optional; not applied."},

    "1547": {"layer": LAYER_PC},
    "1857": {"layer": LAYER_PC},
    "1843": {"layer": LAYER_PC},
    "1837": {"layer": LAYER_PC},
    "1738": {"layer": LAYER_PC},
    "1762": {"layer": LAYER_PC, "namespace_preferences": ["upscale"]},

    "guide:28": {"layer": LAYER_NPC,
                 "note": "Required by Grenades and Mines HD (entry 122)."},

    # [29] Readme is wrong; copy the Creatures folder, previews excluded.
    "1190": {"layer": LAYER_NPC, "file_only": ["Creatures"],
             "file_except": ["Gizka.jpg"]},

    "1023": {"layer": LAYER_NPC},
    "2188": {"layer": LAYER_NPC},
    "2220": {"layer": LAYER_NPC},
    "2517": {"layer": LAYER_NPC},

    # [34] This one wants .tga, NOT .tpc - the opposite of the Ultimate packs.
    "2514": {"layer": LAYER_NPC, "download_only": [".tga"],
             "download_ignore": [".tpc"], "requires_patch": True},

    # [35] Slim vs original necks is player taste. Slim is the installer
    # default; the choice cascades to entry 111's "Original Necks" folder.
    "1430": {"layer": LAYER_NPC,
             "note": "Neck style is player preference. Using the default (slim) "
                     "means entry 111's 'Optional - Original Necks' folder is skipped."},

    "982":  {"layer": LAYER_NPC, "download_only": ["hd_twilek_female.rar"]},

    # [37] Only the six NPC Replacement files - the Optional subfolder is left
    # out here, but IS applied later by the UCO patches (entry 176).
    "1087": {"layer": LAYER_NPC, "file_only": ["NPC Replacement"],
             "file_except": ["optional"]},

    "1480": {"layer": LAYER_NPC},
    "guide:39": {"layer": LAYER_NPC},

    # -- Layer 5: antagonists ---------------------------------------------

    # [40] Skip the .tga download entirely, and skip N_DarthMalak01.tga because
    # CineMalak (entry 41) supplies that texture.
    "980": {
        "layer": LAYER_ANTAGONIST,
        "download_ignore": [".tga"],
        "file_except": ["N_DarthMalak01.tga"],
        "note": "N_DarthMalak01.tga is deliberately not installed - CineMalak "
                "provides it in the next step.",
    },

    # [41] A bare .tga, not an archive. Must land after HD Darth Malak.
    "2787": {"layer": LAYER_ANTAGONIST, "requires": ["980"]},

    "2350": {"layer": LAYER_ANTAGONIST, "rename_base_copies": "PMBJ01"},
    "2164": {"layer": LAYER_ANTAGONIST},
    "1962": {"layer": LAYER_ANTAGONIST},
    "guide:45": {"layer": LAYER_UI_COSMETIC},
    "1213": {"layer": LAYER_PC, "download_only": ["V2"], "file_except": ["V1 Looks"]},

    # -- Layer 6: clothing --------------------------------------------------

    # [47] Delete three textures, then duplicate N_CommM0801 as N_CommM08.
    "2516": {
        "layer": LAYER_CLOTHING,
        "download_ignore": ["txi.rar"],
        "pre_install_delete": ["n_commm07.tga", "N_CommMD01.tga", "N_CommM08.tga"],
        "rename_copies": [("N_CommM0801", "N_CommM08.tga")],
    },

    "guide:48": {"layer": LAYER_CLOTHING, "requires_patch": True},
    "702": {"layer": LAYER_NPC},

    # [50] K1CP-compatible option. The Uthar/Yuthura alternate outfits are an
    # optional extra re-run the guide leaves to taste, so it is not automated.
    "1293": {
        "layer": LAYER_CLOTHING,
        "requires": ["1258"],
        "prefer_compatible": True,
        "multi_run": False,
        "multi_run_options": [],
        "note": "Optional: re-run for Master Uthar / Yuthura Ban alternate "
                "outfits if you want them. Not applied automatically.",
    },

    # -- Layer 7: the Jedi robes chain -------------------------------------

    # [51] The guide strongly recommends Brown-Red-Blue Alternative. This choice
    # drives entries 52 and 186, so it must be pinned rather than defaulted.
    "1378": {
        "layer": LAYER_ROBES,
        "namespace_preferences": ["Brown-Red-Blue Alternative", "Brown-Red-Blue"],
        "note": "Guide recommends the Brown-Red-Blue Alternative robe style. "
                "Entry 186's icon set must match this choice.",
    },

    # [52] The 100% Brown compatibility patch applies ONLY if 100% Brown was
    # chosen above. It was not, so the patch is explicitly suppressed.
    "1477": {
        "layer": LAYER_ROBES,
        "requires": ["1378"],
        "prefer_compatible": False,
        "namespace_preferences": [],
        "multi_run": False,
        "multi_run_options": [],
        "file_except": ["100% Brown", "100 Brown"],
        "note": "The 100% Brown compatibility patch is skipped on purpose - it "
                "is only correct with Cloaked Jedi Robes' 100% Brown option.",
    },

    "2357": {"layer": LAYER_ROBES, "requires": ["1378"],
             "file_only": ["Jedi Robes Override"]},
    "2019": {"layer": LAYER_ROBES, "requires": ["1378"]},

    # -- Layer 8: companions and props -------------------------------------

    "1001": {"layer": LAYER_COMPANION, "pre_install_delete": ["PO_phk47.tga"]},
    "2442": {"layer": LAYER_NPC},
    "2277": {"layer": LAYER_NPC, "download_only": ["Kiosk HD 15.03.2024"],
             "requires_patch": True},
    "2909": {"layer": LAYER_NPC, "requires": ["2277"]},
    "2441": {"layer": LAYER_NPC},
    "2435": {"layer": LAYER_NPC},
    "2434": {"layer": LAYER_WEAPONS},
    "2729": {"layer": LAYER_NPC},

    "2430": {"layer": LAYER_WEAPONS, "download_only": ["Stun baton HD"],
             "download_ignore": ["stunbaton 2025"]},

    "2302": {"layer": LAYER_NPC,
             "note": "Crashes on MacOS and possibly Linux. Fine on Windows."},

    "2382": {"layer": LAYER_NPC,
             "note": "Base install vs Vurt retexture is player preference; "
                     "the base install is used."},

    "2252": {"layer": LAYER_NPC},
    "2383": {"layer": LAYER_NPC, "requires": ["1258"]},
    "2371": {"layer": LAYER_NPC},
    "2475": {"layer": LAYER_NPC},

    # [69] Both the texture and its .txi must go - the parser only caught the .tga.
    "2471": {"layer": LAYER_NPC,
             "pre_install_delete": ["N_CommF02.tga", "N_CommF02.txi"]},

    "2801": {"layer": LAYER_NPC},
    "2806": {"layer": LAYER_NPC},
    "1894": {"layer": LAYER_NPC, "pre_install_delete": ["po_pt3m33.tga"]},
    "2056": {"layer": LAYER_NPC},
    "2559": {"layer": LAYER_NPC},

    # [75] The "new clothes" download only - the other version changes the head.
    "1133": {
        "layer": LAYER_COMPANION,
        "download_only": ["Carth Onasi (new clothes)"],
        "pre_install_delete": ["PO_pcarth3.tga"],
    },

    # [76] "new clothes" version plus its patch; the head comes from entry 77.
    "1123": {"layer": LAYER_COMPANION, "download_only": ["new clothes"],
             "requires_patch": True},

    # [77] Only the head texture, so it does not undo entry 76's clothing.
    "941": {"layer": LAYER_COMPANION, "requires": ["1123"],
            "file_only": ["P_CandH01.tga"]},

    "1935": {"layer": LAYER_COMPANION},
    "guide:79": {"layer": LAYER_COMPANION,
                 "download_ignore": ["iconic", "recolor"],
                 "file_only": ["P_joleeh01.tga", "P_joleeh01.txi"]},

    "2031": {"layer": LAYER_COMPANION,
             "download_ignore": ["Vurt", "Visual Resurgence"],
             "pre_install_delete": ["po_pzaalbar3.tga"]},

    "2808": {"layer": LAYER_CLOTHING, "requires": ["1258"], "prefer_compatible": True},
    "1262": {"layer": LAYER_UI_COSMETIC},
    "1125": {"layer": LAYER_AREA,
             "download_only": ["hd_kt_400_military_droid_carrier_and_lethisk_class_armed_freighter.rar"]},
    "2785": {"layer": LAYER_NPC},

    # -- Layer 9-10: Ebon Hawk, skyboxes, cockpit --------------------------

    "guide:85": {"layer": LAYER_HAWK,
                 "rename_copies": [("LDA_EHawk01", "M36_EHawk01.tga")]},

    # [86] "to override" first, then Animated Monitors overwrites it.
    "2036": {"layer": LAYER_HAWK,
             "note": "Copy 'to override' first, then 'Animated Monitors' over the top."},

    # [87] Medium textures - the guide warns large ones risk save corruption.
    "938": {
        "layer": LAYER_SKYBOX,
        "namespace_preferences": ["Medium"],
        "download_only": ["Medium"],
        "note": "Medium textures recommended: very large cockpit textures slow "
                "Ebon Hawk loads and risk save corruption.",
    },

    # [88] Main option first. The visible-forcefield re-run is optional taste.
    # The resolution folder must match the HQ Cockpit Skyboxes size (Medium),
    # after which five vanilla textures are removed.
    "2068": {
        "layer": LAYER_SKYBOX,
        "requires": ["938"],
        "namespace_preferences": [],
        "multi_run": False,
        "multi_run_options": [],
        "file_only": ["Medium"],
        "post_install_delete": ["ebo_yab.tga", "ebo_yaf.tga", "ebo_yal.tga",
                                "ebo_yar.tga", "ebo_yat.tga"],
        "note": "Optional: re-run for the visible hangar forcefield. Also apply "
                "the Vurt Ebon Hawk patch if entry 85 is installed.",
    },

    "2258": {"layer": LAYER_HAWK},
    "2247": {"layer": LAYER_HAWK,
             "note": "The version without overlays is recommended."},

    # [91] Only Part 1 and Part 2, and seven sky textures must go first.
    "guide:91": {
        "layer": LAYER_AREA,
        "file_only": ["Part 1", "Part 2"],
        "file_except": ["Dantooine Estates", "Sith Base",
                        "LTS_Bsky01.tga", "LTS_Bsky02.tga",
                        "LTS_sky0001.tga", "LTS_sky0002.tga", "LTS_sky0003.tga",
                        "LTS_sky0004.tga", "LTS_sky0005.tga"],
        "requires_patch": True,
    },

    "guide:92": {"layer": LAYER_SKYBOX},

    # [93] The plain K1 archive only. All three lightmap textures go, not just
    # the endpoints of the range. Then the model-fix patch (2796).
    "723": {
        "layer": LAYER_SKYBOX,
        "download_only": ["HQSkyboxesII_K1.7z"],
        "pre_install_delete": ["m36aa_01_lm0.tga", "m36aa_01_lm1.tga",
                               "m36aa_01_lm2.tga"],
        "requires_patch": True,
    },
    "2796": {"layer": LAYER_SKYBOX, "requires": ["723"]},

    # [94] Main install, then only the compat folders that apply to this build:
    # K1CP forcefield, HQ Skyboxes, Yavin Station Hangar.
    "2354": {
        "layer": LAYER_SKYBOX,
        "requires": ["723", "2068", "1258"],
        "prefer_compatible": False,
        "namespace_preferences": [],
        "note": "Apply the main install, then the 'Leviathan - K1CP Forcefield', "
                "HQ Skyboxes and Yavin Station Hangar compatibility folders.",
    },

    # -- Layer 11: effects --------------------------------------------------
    # Note: the Spoiler-Free guide lists Hi-Res Beam Effects, HD Fire and Ice
    # AND Revamped FX together. They are NOT mutually exclusive in this build.

    "260": {"layer": LAYER_EFFECTS},
    "455": {"layer": LAYER_EFFECTS, "requires": ["260"]},
    "2193": {"layer": LAYER_EFFECTS},
    "1129": {"layer": LAYER_UI_COSMETIC},
    "2581": {"layer": LAYER_EFFECTS, "file_except": ["optional", "Optional"],
             "note": "Guide recommends against all of the included optional files."},

    "1925": {"layer": LAYER_UI_COSMETIC},
    "2222": {"layer": LAYER_UI_COSMETIC},
    "1398": {"layer": LAYER_UI_COSMETIC},
    "916":  {"layer": LAYER_UI_COSMETIC},

    # -- Layer 13: weapons --------------------------------------------------

    "1846": {"layer": LAYER_WEAPONS, "namespace_preferences": ["standard"],
             "note": "Only the standard install option is tested by the build."},
    "2506": {"layer": LAYER_WEAPONS, "requires": ["1846"]},

    # [106] Override folder first; the yellow/green disruptor optional folder is
    # player taste and is not applied.
    "1271": {"layer": LAYER_EFFECTS, "file_except": ["optional"],
             "note": "Optional yellow/green disruptors not applied."},

    "1899": {"layer": LAYER_WEAPONS},

    # -- Layer 14: content and gameplay ------------------------------------

    "1856": {"layer": LAYER_CONTENT, "note": "English only."},
    "375":  {"layer": LAYER_CONTENT},
    "guide:110": {"layer": LAYER_CONTENT},

    # [111] Installer, then upscaled textures. The Original Necks folder only
    # applies if entry 35's original-necks option was chosen (it was not). The
    # Senni Vek compat patch is for the Restoration mod, not Senni Vek's Ambush.
    "2228": {
        "layer": LAYER_LATE,
        "requires": ["1430"],
        "file_except": ["Optional - Original Necks"],
        "multi_run_options": ["", "Senni Vek Restoration"],
        "multi_run": True,
        "prefer_compatible": False,
        "note": "Compat patch is for Senni Vek RESTORATION, not Senni Vek's "
                "Ambush. Original Necks folder skipped (slim necks used).",
    },

    "2108": {"layer": LAYER_CONTENT},
    "908":  {"layer": LAYER_CONTENT},
    "2473": {"layer": LAYER_CONTENT},
    "guide:115": {"layer": LAYER_CONTENT, "file_only": ["dan13_dorak.dlg"],
                  "note": "English only. Only dan13_dorak.dlg is installed."},
    "guide:116": {"layer": LAYER_CONTENT},
    "1402": {"layer": LAYER_CONTENT,
             "note": "Incompatible with Steam Deck. Fine on desktop."},
    "guide:118": {"layer": LAYER_CONTENT, "note": "English only."},
    "1270": {"layer": LAYER_CONTENT},
    "827":  {"layer": LAYER_CONTENT},
    "2522": {"layer": LAYER_CONTENT},

    # [122] The full 001-004 range, not just the endpoints.
    "2409": {
        "layer": LAYER_LATE,
        "requires": ["guide:28"],
        "pre_install_delete": ["ii_trapkit_001.tga", "ii_trapkit_002.tga",
                               "ii_trapkit_003.tga", "ii_trapkit_004.tga"],
    },

    "2281": {"layer": LAYER_CONTENT},
    "2284": {"layer": LAYER_CONTENT, "requires": ["1258"], "prefer_compatible": True},
    "2225": {"layer": LAYER_CONTENT},
    "1487": {"layer": LAYER_CONTENT},
    "324":  {"layer": LAYER_CONTENT, "note": "English only."},
    "2214": {"layer": LAYER_CONTENT, "namespace_preferences": ["option 2", "2"],
             "note": "Guide recommends option 2."},
    "guide:129": {"layer": LAYER_CONTENT, "note": "English only."},
    "2739": {"layer": LAYER_CONTENT},
    "1439": {"layer": LAYER_CONTENT},

    # [132] The most fiddly mod in the build:
    #   1. delete keblastore.utm from the mod's own tslpatchdata first
    #   2. the patcher reports exactly one error - that is expected
    #   3. rename w_ionrfl_04.* to w_ionrfl_004.* afterwards (NOT delete)
    #   4. then remove five superseded files from Override
    "861": {
        "layer": LAYER_LATE,
        "pre_patch_delete": ["keblastore.utm"],
        "tolerate_patcher_errors": True,
        "rename_after": _r(("w_ionrfl_04.mdl", "w_ionrfl_004.mdl"),
                           ("w_ionrfl_04.mdx", "w_ionrfl_004.mdx")),
        "post_install_delete": ["w_rptnblstr_004.mdl", "w_rptnblstr_004.mdx",
                                "w_blstrpstl_006.mdl", "w_blstrpstl_006.mdx",
                                "g1_w_rptnblstr01.uti"],
        "note": "One patcher error is expected. w_ionrfl_04 is RENAMED to "
                "w_ionrfl_004 - it must not be deleted.",
    },

    # [133] Main install plus two optional re-runs, both of which apply here
    # (Loadscreens in Color and HQ Blasters are both in this build).
    "1878": {
        "layer": LAYER_LATE,
        "requires": ["916", "861"],
        "multi_run": True,
        "note": "English only. Re-run twice more for the Loadscreens in Color "
                "and High Quality Blasters optional installs.",
    },

    "947":  {"layer": LAYER_CONTENT},
    "1555": {"layer": LAYER_CONTENT},
    "2379": {"layer": LAYER_CONTENT, "note": "English only."},
    "1124": {"layer": LAYER_CONTENT},
    "guide:138": {"layer": LAYER_CONTENT},
    "guide:139": {"layer": LAYER_CONTENT},
    "guide:140": {"layer": LAYER_CONTENT, "requires_patch": True,
                  "note": "Install the base mod, then copy the patch file to Override."},
    "2792": {"layer": LAYER_CONTENT},
    "guide:142": {"layer": LAYER_CONTENT},
    "guide:143": {"layer": LAYER_CONTENT},
    "1404": {"layer": LAYER_CONTENT},
    "guide:145": {"layer": LAYER_CONTENT,
                  "note": "English only. A single loose file - copy it straight to Override."},
    "1427": {"layer": LAYER_CONTENT},
    "2723": {"layer": LAYER_CONTENT,
             "note": "Full / lite / ultra lite is player preference; Full is used."},
    "1747": {"layer": LAYER_CONTENT},

    # [149] With K1CP installed, only the pillar facing fix is wanted - K1CP
    # already contains the lighting fix.
    "1545": {
        "layer": LAYER_LATE,
        "requires": ["1258"],
        "namespace_preferences": ["pillar facing", "pillar"],
        "multi_run": False,
        "multi_run_options": [],
        "note": "Only the pillar facing fix - K1CP already includes the lighting fix.",
    },

    # [150] The Ithorian patch applies because Dark Hope's Ithorians HD (64) is
    # in this build.
    "2309": {"layer": LAYER_LATE, "requires": ["2382"], "requires_patch": True},

    "1289": {"layer": LAYER_CLOTHING},
    "1179": {"layer": LAYER_NPC},
    "guide:153": {"layer": LAYER_CONTENT},
    "guide:154": {"layer": LAYER_CONTENT},
    "guide:155": {"layer": LAYER_CONTENT,
                  "namespace_preferences": ["Revisited"]},
    "guide:156": {"layer": LAYER_CONTENT,
                  "note": "Crashes on MacOS and possibly Linux. Fine on Windows."},
    "1736": {"layer": LAYER_CONTENT},
    "guide:158": {"layer": LAYER_CONTENT},
    "guide:159": {"layer": LAYER_CONTENT},

    # [160]/[161] Ajunta Pall's sword chain.
    "541": {"layer": LAYER_WEAPONS,
            "file_except": ["Weapon Model Overhaul"],
            "note": "Use the version that is NOT for the Weapon Model Overhaul."},
    "1338": {"layer": LAYER_WEAPONS, "requires": ["541"],
             "namespace_preferences": ["VarsityPuppet", "Rece"],
             "prefer_compatible": False},

    # [162] Option A only. The extra-textures re-run is explicitly discouraged
    # because UCO's upscales are better.
    "1454": {
        "layer": LAYER_CONTENT,
        "namespace_preferences": ["Option A"],
        "multi_run": False,
        "multi_run_options": [],
        "note": "Option A only - do NOT re-run for the extra textures; UCO's "
                "upscaled versions are higher quality.",
    },

    # [163]/[164] The blaster pair. The guide's recommended Multifire option is
    # 2 or 3, which makes "Blaster Pistol & Blaster Rifle + Critical" the
    # matching JC's Blaster Adjustment option.
    "guide:163": {"layer": LAYER_CONTENT,
                  "namespace_preferences": ["option 2", "option 3"],
                  "note": "Guide recommends option 2 or 3."},
    "2827": {
        "layer": LAYER_LATE,
        "namespace_preferences": ["Blaster Pistol & Blaster Rifle + Critical",
                                  "Blaster Pistol and Blaster Rifle"],
        "note": "Chosen to match Multifire and Autofire option 2/3. With "
                "option 1 the correct pick would be 'Blaster Pistol + Critical'; "
                "with no Multifire at all, the full install.",
    },

    "312":  {"layer": LAYER_WEAPONS},
    "2231": {"layer": LAYER_WEAPONS},
    "guide:167": {"layer": LAYER_CONTENT},
    "2008": {"layer": LAYER_CONTENT, "note": "English only."},
    "681":  {"layer": LAYER_EFFECTS},
    "2321": {"layer": LAYER_CONTENT},
    "1866": {"layer": LAYER_CONTENT},
    "2502": {"layer": LAYER_CONTENT},

    # [173] Combined install; the Patch folder is only for K2 Force Powers for K1.
    "2759": {"layer": LAYER_CONTENT,
             "namespace_preferences": ["combined", "Treat Injury"],
             "file_except": ["Patch"],
             "note": "Combined 'Alignment Affects Force Powers + Treat Injury "
                     "Affects Force Healing' install. Patch folder skipped."},

    # [174] The guide gives two paths. Widescreen: install last, after the
    # widescreen menus, plus the HR Menu Patch matching your resolution.
    # Not widescreen: "install the base mod only at this point" - which is
    # automatable, so it is not left as a manual step. The HR Menu Patch is
    # excluded because it is meaningful only alongside the widescreen menus.
    "guide:174": {
        "layer": LAYER_WIDESCREEN,
        "file_except": ["HR Menu Patch"],
        "note": "Base mod only (no widescreen menus installed). If you later "
                "apply the UniWS widescreen patch and the HR Menus mod, also "
                "copy the HR Menu Patch file for your resolution to Override.",
    },

    # -- Layer 16: cross-mod patch packs -----------------------------------

    # [176] The UCO patch set, applied in the guide's stated order and only for
    # the mods actually in this build.
    "guide:176": {
        "layer": LAYER_PATCHES,
        "requires": ["guide:16"],
        "file_except": ["Better Twi'lek Male Heads", "Republic Soldier's New Shade",
                        "JC's Mandalorian Armor", "Mandalorian"],
        "note": "Order: JC's Minor Fixes compatch (delete N_CommM02-N_CommM08 "
                "from Aesthetics Improvements), then K1CP (delete PLC_SSldCrps.tpc), "
                "then the remaining patches matching mods in this build. Skip the "
                "Better Twi'lek Male Heads and Republic Soldier's New Shade "
                "patches, and JC's Mandalorian Armor (entry 179 covers it better). "
                "For Thigh-High Boots, apply both NPC Replacement and Optional.",
    },

    # [177] Both components: the Override folder, plus only the PFBBL/PMBBL
    # player clothing files.
    "1180": {
        "layer": LAYER_PATCHES,
        "file_only": ["Override", "PFBBL", "PMBBL"],
        "note": "Both components installed, so entry 178 must use Options 3 and 5.",
    },

    # [178] Follows directly from entry 177 using both components.
    "1365": {
        "layer": LAYER_PATCHES,
        "requires": ["1180"],
        "multi_run_options": ["Option 3", "Option 5"],
        "multi_run": True,
        "namespace_preferences": [],
        "note": "Options 3 and 5, because both components of JC's Republic "
                "Soldier Fix are installed.",
    },

    # [179] 2x .tpc, and the cleaner.bat/cleanlist step is a manual pre-step.
    "2659": {
        "layer": LAYER_PATCHES,
        "download_only": ["2x", "tpc"],
        "manual_only": True,
        "manual_reason": "Needs the mod's cleaner.bat plus cleanlist_k1_sf.txt run "
                         "against the 'Copy contents to KotOR's Override folder' "
                         "folder to strip files that clash with the rest of the "
                         "build, before anything is copied to Override.",
    },

    # -- Layer 17: widescreen ----------------------------------------------

    # [180] Hard stop on Steam: the 4GB patcher breaks Steam's encrypted
    # executable unless the widescreen .exe replaced it first.
    "guide:180": {
        "layer": LAYER_WIDESCREEN,
        "manual_only": True,
        "manual_reason": "Do NOT apply to the Steam version unless the UniWS "
                         "widescreen patch has already replaced swkotor.exe - it "
                         "will break the encrypted Steam executable and the game "
                         "will not launch.",
    },

    "guide:181": {"layer": LAYER_WIDESCREEN},
    "1159": {"layer": LAYER_WIDESCREEN, "manual_only": True,
             "manual_reason": "Needs a copy of swkotor.exe placed in the mod folder "
                              "and the .bat (not the .exe) run interactively, after "
                              "the UniWS widescreen patch."},
    "1226": {"layer": LAYER_WIDESCREEN},
    "1742": {"layer": LAYER_UI_COSMETIC},

    # [185] The one mod that must never overwrite existing files.
    "1815": {"layer": LAYER_UI_COSMETIC,
             "namespace_preferences": [".tpc", "tpc"],
             "no_overwrite": True,
             "note": "For this mod only: do not overwrite existing files."},

    # [186] Icons must match the robe style chosen at entry 51.
    "2303": {"layer": LAYER_UI_COSMETIC,
             "requires": ["1378"],
             "file_only": ["JC's Cloaked Jedis", "Brown-Red-Blue"],
             "file_except": ["Effix"],
             "note": "Icon set matches Cloaked Jedi Robes' Brown-Red-Blue "
                     "Alternative. The Effix folder is for a mod not in this build."},

    "2025": {"layer": LAYER_UI_COSMETIC},
    "1792": {"layer": LAYER_WIDESCREEN},
    "1173": {"layer": LAYER_WIDESCREEN},

    # [190]/[191] Two cutscene packs - the guide says use one or the other.
    # download_only is OR-matched, so it must name the ONE archive wanted. A
    # loose ["1920x1080", "30fps"] pair matches every 30fps variant, and each
    # resolution of this pack is 8-15 GB.
    "2380": {
        "layer": LAYER_CONTENT,
        "download_only": ["k1rs_30fps_1920x1080"],
        "skip_if": ["KOTOR Remastered Cutscenes"],
        "note": "30fps strongly recommended - crashes are linked to the 60fps "
                "versions. Files go to the movies folder, not Override.",
    },
    "guide:191": {
        "layer": LAYER_CONTENT,
        "skip_if": ["K1 Cutscenes Rescaled"],
        "note": "Alternative to entry 190 - use one cutscene pack, not both. "
                "The title crawl movie does not play with this pack.",
    },

    # -- Layer 18: cleanup, must be last -----------------------------------

    # [175] Critical: duplicate .tga/.tpc pairs crash the game. Interactive .bat,
    # so it cannot be run unattended.
    "guide:175": {
        "layer": LAYER_CLEANUP,
        "manual_only": True,
        "manual_reason": "CRITICAL final step. Put DelDuplicateTGA-TPC.bat in the "
                         "GAME folder (not Override), run it, and choose to delete "
                         "the TPC duplicates. If it reports no deleted files it did "
                         "not work, and the game will crash. Run this only after "
                         "every other mod is installed.",
    },
}


# Mutual exclusions and cross-mod facts that are not per-mod directives.
K1_SPOILERFREE_NOTES = {
    "effects_not_exclusive": (
        "Unlike the K1 Full build, the Spoiler-Free build installs Hi-Res Beam "
        "Effects, HD Fire and Ice AND Revamped FX together. They are not "
        "mutually exclusive here."
    ),
    "cutscenes_exclusive": (
        "K1 Cutscenes Rescaled (190) and KOTOR Remastered Cutscenes (191) are "
        "alternatives. Install one only."
    ),
    "final_step": (
        "Remove Duplicate TGA/TPC (175) must be the very last step, after every "
        "other mod including widescreen. Skipping it can crash the game."
    ),
    "steam_4gb": (
        "The 4GB Patcher (180) must not be applied to a Steam install unless the "
        "widescreen .exe replaced swkotor.exe first."
    ),
}


BUILD_OVERRIDES = {
    "k1_spoilerfree": K1_SPOILERFREE,
}

BUILD_NOTES = {
    "k1_spoilerfree": K1_SPOILERFREE_NOTES,
}

# Field names that replace the parsed value outright rather than merging.
_SCALAR_FIELDS = {
    "prefer_compatible", "patch_first", "requires_patch", "multi_run",
    "rename_base_copies", "tolerate_patcher_errors", "no_overwrite",
    "layer", "manual_only", "manual_reason",
}


def lookup(build_key: str, file_id: str = "", guide_index: int = 0) -> dict:
    """Return the curated rule dict for a mod, or {} when there is none."""
    table = BUILD_OVERRIDES.get(build_key or "")
    if not table:
        return {}
    if file_id and file_id in table:
        return table[file_id]
    if guide_index and f"guide:{guide_index}" in table:
        return table[f"guide:{guide_index}"]
    return {}


def apply(dirs, build_key: str, file_id: str = "", guide_index: int = 0):
    """
    Overlay the curated rules for a mod onto parsed directives.

    List fields are REPLACED, not appended: the whole point of a curated entry
    is that the audited list is the correct one, and merging would let a bad
    regex capture back in. Scalars are replaced too. Fields the entry does not
    mention keep their parsed value.
    """
    rule = lookup(build_key, file_id, guide_index)
    if not rule:
        return dirs
    changes = {}
    for key, value in rule.items():
        if key == "note":
            continue
        if not hasattr(dirs, key):
            continue
        changes[key] = list(value) if isinstance(value, list) else value
    if not changes:
        return dirs
    updated = replace(dirs, **changes)
    note = rule.get("note")
    if note and note not in updated.manual_notes:
        updated.manual_notes = [*updated.manual_notes, note]
    return updated
