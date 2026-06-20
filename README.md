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

To enable it, drop `HoloPatcher.exe` into `tools/HoloPatcher/` next to the app
(or run `python tools/setup_holopatcher.py`), or set the `KOTOR_HOLOPATCHER_EXE`
environment variable. The app shows the shim status in the bottom bar. Without
it, the app automates the TSLPatcher GUI instead.

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

## CI

`.github/workflows/build.yml` builds the Windows exe on every push and attaches a
zipped release on any `v*` tag (e.g. `git tag v1.0.0 && git push --tags`).

## License / disclaimer

This tool automates downloading from your own authenticated DeadlyStream account
and running mod-supplied installers. It bundles no mod content. HoloPatcher and
TSLPatcher are third-party tools owned by their respective authors.
