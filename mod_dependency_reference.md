# KOTOR 1 & 2 Mod Dependency and Conflict Reference

Synthesised from all four build guides on kotor.neocities.org (K1 Full, K1 Spoiler-Free, K2 Full, K2 Spoiler-Free).
Source: https://kotor.neocities.org/modding/mod_builds/

---

## KOTOR 1

### Install Layer Order

Mods must be installed in layer order. Within a layer the guide's listed sequence should be followed unless noted otherwise.

| Layer | Description | Example mods |
|-------|-------------|--------------|
| 0 | Immersion / dialogue fixes | KOTOR Dialogue Fixes, Character Startup Changes |
| 1 | **K1CP (Community Patch)** - master for most later mods | K1CP (#6) |
| 2 | Area texture packs | Ultimate Korriban/Kashyyyk/Tatooine/Dantooine/Manaan/Taris/Character Overhaul/Unknown World |
| 3 | NPC appearance mods | Gammorean Reskin, War Droids HD, Better Twi'lek Heads, HD NPC characters |
| 4 | Player character cosmetics | HD PC Portraits, PMHA/PFHC head textures |
| 5 | Key antagonist textures | HD Darth Malak, CineMalak, Darth Bandon HD, HD Vrook |
| 6 | Clothing / armour appearance | Male NPC Clothing, Sith Uniform Reformation Revised |
| 7 | Jedi robes chain | Cloaked Jedi Robes, JC's Jedi Tailor, Cloaks with Shadows, Qel-Droma Reskin |
| 8 | Companion appearance | HD Carth, HD Canderous, Jolee HD, Zaalbar HD, Juhani appearance mods |
| 9 | Ebon Hawk - base textures | Hi-Res Ebon Hawk, Ebon Hawk Repairs |
| 10 | Ebon Hawk - skyboxes / cockpit | HQ Cockpit Skyboxes, Yavin Station Hangar, HQ Skyboxes II, Transparent Cockpit Windows |
| 11 | Effects - pick ONE chain | **Chain A:** Hires Beam Effects → HD Fire & Ice **OR** **Chain B:** Revamped FX |
| 12 | Animated / UI cosmetics | Animated Energy Shields, Terminal Texture, Loadscreens in Color |
| 13 | Lightsaber / weapon appearance | Reflective Lightsaber Blades, Darth Malak's Lightsaber, HQ Blasters |
| 14 | Added content / gameplay mods | All TSLPatcher content mods, restored content, mechanics changes |
| 15 | Late dependencies | HD Grenades & Mines (requires High-Poly Grenades from earlier), Male Twi'lek Diversity (requires Better Twi'lek Heads) |

---

### K1 Hard Install-Order Constraints

These pairs/chains must be installed in the order shown. Installing them out of order causes visual glitches or broken patching.

| Install first | Then install | Reason |
|---------------|-------------|--------|
| K1CP (#6) | All K1CP-dependent mods | K1CP must exist before TSLPatcher-based mods patch its files |
| Ajunta Pall Appearance - run PATCH | Ajunta Pall Appearance - textures | Patch writes .2da entries the textures depend on |
| High-Poly Grenades (#28) | HD Grenades & Mines (#123) | HD Grenades requires the mesh from High-Poly |
| Cloaked Jedi Robes (#51) | JC's Jedi Tailor (#52) | Jedi Tailor patches Cloaked Jedi Robes files |
| Cloaked Jedi Robes (#51) | Cloaks with Shadows (#53) | Cloaks with Shadows copies Cloaked Robes files |
| Cloaked Jedi Robes (#51) | Qel-Droma Reskin (#54) | Qel-Droma reskins Cloaked Robes textures |
| Hi-Res Ebon Hawk (#85) | Ebon Hawk Repairs (#86) | Repairs patching assumes Hi-Res textures are present |
| HQ Cockpit Skyboxes (#87) | Transparent Cockpit Windows (#94) | TCW has a patch folder for HQ Cockpit Skyboxes |
| Hires Beam Effects (#95) | HD Fire & Ice (#96) | HD Fire & Ice supplements Hires Beam Effects |
| Reflective Lightsaber Blades (#104) | Darth Malak's Lightsaber (#105) | Malak's Lightsaber extends the Reflective Blades framework |
| Better Twi'lek Heads (#35) | Male Twi'lek Diversity (#111) | Diversity has a compatch for Better Twi'lek Heads |
| HD Darth Malak (#40) | CineMalak (#41) | CineMalak layers its TGA on top of HD Darth Malak textures |

---

### K1 Mutual Exclusions and Hard Conflicts

| Conflict | Notes |
|----------|-------|
| Revamped FX vs Hires Beam Effects + HD Fire & Ice | Choose one or the other - mixing creates visual overlap. Revamped FX replaces both. |
| HD Darth Malak TGA vs CineMalak TGA | Install both mods but use CineMalak's N_DarthMalak01.tga instead of HD Darth Malak's. Not a hard conflict - requires careful file management. |

---

### K1 Platform Incompatibilities

| Mod | Platform | Issue |
|-----|----------|-------|
| Unique Sith Governor | MacOS, possibly Linux | Causes game crashes |
| Vision Enhancement | Steam Deck | Architecture incompatibility |

---

### K1 Language Restrictions (English only)

JC's Jedi Tailor, Kill The Czerka Guard, JCDE (Dorak dialogue), Taris Rapid Transit, Sunry Enhancement, LDD, Crashed Republic Cruiser.

HQ Blasters has partial non-English support (some text blanks in other languages).

---

### K1 Compatibility Patches Required

| Mod | Patch needed for |
|-----|-----------------|
| Ebon Hawk Transparent Cockpit Windows | K1CP folder, HQ Skyboxes folder, Yavin Station Hangar folder - apply all that apply |
| Yavin Station Hangar | Patches for HQ Cockpit Skyboxes and Hi-Res Ebon Hawk available |
| Ported VO Replacements | K1CP compatibility patch must run after main mod |
| Male Twi'lek Diversity | Compatibility patches for original necks option and Senni Vek Restoration |
| HQ Skyboxes II | CaptainSpoque patch required after main install; delete m36aa files first |
| HQ Blasters | Delete keblastore.utm from TSLPatchdata; rename ionrfl files; delete specified blaster files after install |

---

### K1 Pre-Install File Deletions Required

| Mod | Files to delete before installing |
|-----|----------------------------------|
| Ultimate Taris | LSI_win01.tpc, LSI_box01.tpc |
| Ultimate Unknown World | LUN_blst01.tpc, LUN_blst02.tpc |
| HD Astromech Droids | po_pt3m33.tga |
| Quanon's HK-47 | PO_phk47.tga |
| HD Carth Onasi | PO_pcarth3.tga |
| Zaalbar HD | po_pzaalbar3.tga |
| Kebla Yurt HD | N_CommF02.tga, N_CommF02.txi |
| Male NPC Clothing | n_commm07.tga, N_CommMD01.tga, N_CommM08.tga (then duplicate and rename N_CommM0801.tga as N_CommM08.tga) |
| HD Grenades & Mines | ii_trapkit files |
| HQ Cockpit Skyboxes | m36aa_01_lm0.tga through m36aa_01_lm2.tga |

---

### K1 Topological Dependency Tree

```
K1CP
 ├── Droid Claw Fix
 ├── Ported VO Replacements (+ K1CP compatch after)
 ├── HD Quarren
 ├── Male NPC Clothing
 ├── Korriban Back in Black (K1CP variant)
 ├── Sith Uniform Reformation Revised
 └── Party Conversations on the Ebon Hawk

High-Poly Grenades
 └── HD Grenades & Mines

Cloaked Jedi Robes
 ├── JC's Jedi Tailor
 ├── Cloaks with Shadows
 └── Qel-Droma Reskin

Hi-Res Ebon Hawk
 └── Ebon Hawk Repairs

Better Twi'lek Heads
 └── Male Twi'lek Diversity (+ compatch)

HD Darth Malak
 └── CineMalak (use CineMalak's TGA, not Malak's)

Reflective Lightsaber Blades
 └── Darth Malak's Lightsaber

HQ Cockpit Skyboxes
 └── Transparent Cockpit Windows (+ HQ Cockpit patch folder)

Hires Beam Effects     [OR pick Revamped FX - not both]
 └── HD Fire & Ice
```

---

---

## KOTOR 2

### Install Layer Order

| Layer | Description | Example mods |
|-------|-------------|--------------|
| 0 | **System patchers** - must be first, pick one | 3C-FD Patcher OR 4GB Patcher (mutually exclusive) |
| 0b | Essential bugfixes (Aspyr version only) | Water Restoration, Stutter Fix and Force Cage Update |
| 1 | **TSLRCM** - master dependency for virtually everything | TSLRCM (#5) |
| 2 | **TSLRCM Tweak Pack** - 6 separate installer runs | Kaevee Removal Pts 1-2, Saedhe's Head, Dialogue Tweak, Mandalore Conv., Extra 1 SLM |
| 3 | **K2CP (K2 Community Patch)** - second master dependency | K2CP (#12) |
| 4 | Area / environment textures | Ultimate HR Textures, Ultimate Nar Shaddaa/D2/Dxun/Onderon/K2/M |
| 5 | Ultimate Character Overhaul (delete conflicting files first) | UCO (#16) |
| 6 | NPC / companion appearance | Better Twi'lek Heads, TSL Twi'lek Male NPC Diversity, HD Vrook, HD DN, Darth Sion Remake |
| 7 | Ebon Hawk graphics base | HQ Skyboxes II (+ K2CP re-extract step), Spark Effect |
| 8 | Cockpit windows | Transparent Cockpit Windows + patches in order; HD Cockpit Skyboxes |
| 9 | Effects | Hi-Res Beam Effects, Fire And Ice HD, Blaster Visual Effects |
| 10 | Gameplay / content mods | All TSLPatcher content mods, mechanics changes, restored content |
| 11 | Late multi-mod chains | Better JJT Thugs before Logical JJT (+ compatch); SAwL before True SA (+ compatch) |
| 12 | High Quality Blasters (late, patches weapon files) | HQ Blasters |

---

### K2 Hard Install-Order Constraints

| Install first | Then install | Reason |
|---------------|-------------|--------|
| 3C-FD Patcher OR 4GB Patcher | Everything else | Must be the very first thing applied to the game |
| Water Restoration, Stutter Fix | Everything else (Aspyr only) | Core game fix before any mods |
| TSLRCM (#5) | All TSLRCM-dependent mods | All content mods assume TSLRCM files are present |
| TSLRCM Tweak Pack (#6) | Everything after | Patches TSLRCM files |
| K2CP (#12) | All K2CP-dependent mods | K2CP patching must precede its dependents |
| HQ Skyboxes II (#77) | Then: re-extract K2CP zip and move 231teld.mdl + 231teld.mdx to override | HQ Skyboxes overwrites K2CP files; K2CP's fixed version must be restored after |
| Spark Effect (#80) | Transparent Cockpit Windows (#81) | TCW has a Spark Effect compatibility patch |
| Better JJT Thugs (#104) | Logical JJT (#105) | Then install Logical JJT/Better JJT compatch |
| SAwL (#111) | True SA (#112) | Run True SA then immediately apply SAwL compatch |
| JCS Lightsaber Visual Effects (#66) | Enhanced Lightsaber Hilt Variety (#67) | Hilt Variety builds on the Lightsaber VFX framework |

---

### K2 Mutual Exclusions and Hard Conflicts

| Conflict | Notes |
|----------|-------|
| 3C-FD Patcher vs 4GB Patcher | **Hard conflict - use exactly one.** 3C-FD already applies the 4GB patch; using both breaks the executable. |
| M4-78 EP | No version of M4-78 is compatible with this build. Do not install. |
| Transparent Cockpit Windows - Korriban Distorted Model Fix folder | Do NOT apply this folder. It is unnecessary when using 3C-FD Patcher and causes problems. |
| Atton at the End (TSLRCM Tweak Pack option) | Completely incompatible with other mods in this build. Do not select during Tweak Pack install. |

---

### K2 Platform Incompatibilities

| Variant | Restriction |
|---------|-------------|
| TSLRCM Steam Workshop version | Forbidden - do not use. Download the standalone installer. |
| Legacy game version (not Aspyr) | Cannot use 3C-FD Patcher. Cannot use widescreen. Use 4GB Patcher instead. |
| Mac App Store version | Incompatible with both 3C-FD Patcher and 4GB Patcher. |

---

### K2 Language Restrictions

**English only:** Remote Tells Influence, Droid Special Weapons Fix, Aleema Keto's Robe Description Correction, Onderon News Make Sense, Ebon Hawk Downloadable Map, Kill the Ithorian, RFL, DSME, Better Disciple Meditation, JCS Crystal Attunement, Logical JJT, Mira's Vanilla Escape, N-V Tweak, For Mandalore!

**Partial support (some text blank):** HQ Blasters.

TSLRCM Tweak Pack: skip the Mandalore Conversation run for non-English installs.

---

### K2 Compatibility Patches Required

| Mod | Patch needed for |
|-----|-----------------|
| Transparent Cockpit Windows (#81) | Apply in order: K2CP/Nar Shaddaa compatch, HQ Skyboxes II compatch (NOT M4-78 folder), Spark Effect compatch |
| HD Cockpit Skyboxes (#82) | If using HQ Skyboxes II, use "With Nar Realistic Skybox" folder instead of base folder |
| HQ Skyboxes II (#77) | After install, re-extract K2CP (do not re-run TSLPatcher), copy 231teld.mdl and 231teld.mdx to override |
| TSL Twi'lek Male NPC Diversity (#39) | If using original necks option from Better Twi'lek Heads, also install "Optional - Original Necks" folder |
| Logical JJT (#105) | Run Part 1, then Part 2, then compatch only if Better JJT Thugs is installed |
| True SA (#112) | Apply SAwL compatch immediately after if using SAwL |
| Ultimate Dxun (#19) | Apply patch after main mod install |

---

### K2 Pre-Install File Deletions Required

| Mod | Files to delete before installing |
|-----|----------------------------------|
| Ultimate HR Textures (#15) | PER_Gr01.tpc, TEL_rock.tpc through TEL_rock07.tpc, TEL_wl05.tpc |
| Ultimate Character Overhaul (#16) | N_OndSoldMH1.tpc, PMBJ02.tpc, PMHC03.tpc, PMHC03D1.tpc, PMHC03D2.tpc |
| Ultimate Nar Shaddaa (#17) | NAR_fl01.tpc, NAR_Met4.tpc, NAR_wl07.tpc |
| Ultimate D2 (#18) | DAN_birds.tpc, DAN_MWFl.tpc, DAN_NEW1.tpc, DAN_wall03.tpc |
| Ultimate Dxun (#19) | DXN_BWa1 through DXN_BWa8.tpc |
| Ultimate Onderon (#20) | OND_dor1.tpc, OND_dor3.tpc |
| Ultimate K2 (#21) | KOR_water01.tpc |
| JC's Minor Fixes (#26) | If using K2CP: skip "Straight Fixes" folder; also delete DXn_grassfx.tga, DXN_jungfx.tga from Aesthetic Improvements |
| T3M4 HD 2K (#59) | P_t3m4_01.tpc and P_t3m4_01.tga if present |
| HD VM / HD Visas Marr (#57) | If using K2CP or UCO: delete P_VisasBB.tpc, P_VisasH01.tpc/.tga, P_VisasHD01.tpc/.tga, P_VisasHD02.tpc/.tga |

---

### K2 Topological Dependency Tree

```
3C-FD Patcher [XOR] 4GB Patcher       <- Layer 0, pick exactly one
 └── Water Restoration (Aspyr only)
 └── Stutter Fix (Aspyr only)

TSLRCM
 ├── TSLRCM Tweak Pack (6 runs)
 ├── K2CP
 │    ├── (many content mods depend on K2CP)
 │    └── HQ Skyboxes II
 │         └── [re-extract K2CP 231teld files after]
 │         └── HD Cockpit Skyboxes (use Nar Realistic Skybox folder)
 ├── Better JJT Thugs
 │    └── Logical JJT Part 1
 │         └── Logical JJT Part 2
 │              └── Better JJT / Logical JJT compatch
 ├── Extended Enclave (EE 2.5)
 └── SAwL
      └── True SA (+ SAwL compatch)

Better Twi'lek Heads
 └── TSL Twi'lek Male NPC Diversity (+ original necks compatch if needed)

Spark Effect
 └── Transparent Cockpit Windows (+ K2CP patch, HQ Skyboxes patch, Spark patch in order)

JCS Lightsaber Visual Effects
 └── Enhanced Lightsaber Hilt Variety
```

---

---

## Cross-Game Shared Mods

These mods appear in both K1 and K2 build guides and behave similarly in both:

| Mod | Notes |
|-----|-------|
| Hi-Res Beam Effects | Same mod, same loose-file install in both games |
| HD Fire & Ice | Same mod, supplements Beam Effects in both |
| Animated Energy Shields | Listed for K1; confirmed working in K2 |
| War Droids HD | Listed for K1; confirmed working in K2 |
| HD Vrook | Same mod usable in both games |
| HD NPC Portraits | Separate K1 and K2 versions exist |
| Better Twi'lek Heads | HoloPatcher mod, separate but similar installs per game |
| Thigh-High Boots for Twi'lek | NPC Replacement folder only in both games |
| Terminal Texture | Slightly different file handling per game |
| HD Sign Placeable / HD Desk / HD Kiosk | Same mods, same install in both |

---

## Common Installer Types Reference

| Type | Install method | Notes |
|------|---------------|-------|
| Loose-File | Copy files to Override folder | Simplest; just move files |
| TSLPatcher | Run Setup.exe | Modifies .2da and .tlk; must run in correct order |
| HoloPatcher | Run HoloPatcher.exe | Modern successor to TSLPatcher; safer conflict handling |
| Executable | Run installer (3C-FD, 4GB, TSLRCM) | System-level patchers; must run before game mods |

---

## Summary of Critical Rules

1. **K2 only:** 3C-FD Patcher XOR 4GB Patcher - pick one, never both.
2. **K2 only:** TSLRCM must install before K2CP, which must install before everything else.
3. **K2 only:** After HQ Skyboxes II, manually restore K2CP's 231teld.mdl/mdx files.
4. **K1 only:** K1CP installs at position 6 and must precede all K1CP-dependent mods.
5. **Both games:** Cloaked Jedi Robes (K1) / robes chain must precede its compatch mods.
6. **Both games:** Area texture packs install before NPC mods, which install before effects mods.
7. **Both games:** "Hires Beam Effects + HD Fire & Ice" and "Revamped FX" (K1) are alternatives, not additive.
8. **Both games:** Multiple texture mods require specific files to be deleted from Override before copying new files in.
9. **Both games:** M4-78 is incompatible with the K2 build. No version works.
10. **Both games:** Mac/Linux players should avoid Unique Sith Governor (K1); Steam Workshop TSLRCM (K2) is forbidden.
