# KOTOR Mod Installer

A one-click downloader and **auto-installer** for the recommended KOTOR 1 & KOTOR 2
mod builds from [kotor.neocities.org](https://kotor.neocities.org). It scrapes the
recommended build in install order, downloads every mod from DeadlyStream, unpacks
it, detects how each mod installs, and installs them sequentially with as little
interaction as possible.

## Features

- **Ordered, sequential install** following the neocities build order.
- **Headless TSLPatcher installs** via a universal HoloPatcher shim (see below) —
  no per-mod clicking. Falls back to automating the TSLPatcher GUI, then to a
  manual one-click prompt.
- **HoloPatcher** mods run fully headless via CLI.
- Handles Override copies, `dialog.tlk` replacement, multi-variant mods, and
  multi-file submissions.
- Live per-mod download **and** install progress, activity log, pause/stop.
- DeadlyStream login with credentials stored in Windows Credential Manager.
- Data-driven installer config (`installer/installer_config.json`) — add new
  patcher types / legacy exe names without code changes.

## Download & run (no Python needed)

Grab the latest `KOTOR-Mod-Installer-windows.zip` from the
[Releases](../../releases) page, unzip, and run `KOTOR-Mod-Installer.exe`.

## The HoloPatcher shim ("dynamic patcher")

TSLPatcher has no command line, and there are many legacy builds. Rather than
patching each `TSLPatcher.exe`, the app uses **HoloPatcher** — a headless,
open-source reimplementation that reads the *identical* `tslpatchdata` /
`changes.ini` / `namespaces.ini` format. One HoloPatcher engine installs **any**
TSLPatcher mod with no GUI.

**HoloPatcher is bundled inside the released exe automatically** — you don't need
to download or drop in anything. The build fetches it via
`tools/setup_holopatcher.py` and embeds it. The bottom bar shows the shim status.
You can still override the bundled copy with the `KOTOR_HOLOPATCHER_EXE`
environment variable or a `tools/HoloPatcher/HoloPatcher.exe` next to the app.

## Run from source

```bash
pip install -r requirements.txt
python main.py
```

## Build the executable locally

```bash
pip install pyinstaller
pyinstaller kotor_mod_installer.spec --noconfirm
# → dist/KOTOR-Mod-Installer.exe
```

## Versioning & releases

Versioning is automatic and driven by [Conventional Commits](https://www.conventionalcommits.org):

- Every push to `main` runs `.github/workflows/release.yml`, which uses
  [git-cliff](https://git-cliff.org) (`cliff.toml`) to compute the next semver
  (`feat:` → minor, `fix:`/other → patch, `BREAKING CHANGE` → major),
  regenerate `CHANGELOG.md`, bump `installer/_version.py`, tag it, and build +
  publish the GitHub Release.
- If a push contains no release-worthy commits, no version is cut.
- Pull requests and manual runs build a validation artifact via
  `.github/workflows/build.yml` (no release).
- Both paths share `.github/workflows/_build.yml`, so CI builds match released
  ones exactly. The released exe is fully self-contained (HoloPatcher bundled).

Commit messages should follow Conventional Commits, e.g. `feat: add pause/resume`,
`fix(pipeline): handle multi-file mods`, or `feat!: ...` / a `BREAKING CHANGE:`
footer for a major bump.

## License / disclaimer

This tool automates downloading from your own authenticated DeadlyStream account
and running mod-supplied installers. It bundles no mod content. HoloPatcher and
TSLPatcher are third-party tools owned by their respective authors.
