# KOTOR Mod Installer

A one-click downloader and **auto-installer** for the recommended KOTOR 1 & KOTOR 2
mod builds from [kotor.neocities.org](https://kotor.neocities.org). It scrapes the
recommended build in install order, downloads every mod from DeadlyStream, unpacks
it, detects how each mod installs, and installs them sequentially with as little
interaction as possible.

## Features

- **Full mod manager** - a persistent per-game library of every installed mod:
  enable/disable (files move in/out of the game tree), uninstall, load order,
  and **file-level conflict detection** across enabled mods. Import **any** KOTOR
  mod (arbitrary archive or folder), not just the curated builds.
- **Ordered, sequential install** following the neocities build order.
- **Headless TSLPatcher installs** via a universal HoloPatcher shim (see below) -
  no per-mod clicking. Falls back to automating the TSLPatcher GUI, then to a
  manual one-click prompt.
- **HoloPatcher** mods run fully headless via CLI.
- Handles Override copies, `dialog.tlk` replacement, multi-variant mods, and
  multi-file submissions.
- Live per-mod download **and** install progress, activity log, pause/stop.
- DeadlyStream login with credentials stored in Windows Credential Manager.
- Data-driven installer config (`installer/installer_config.json`) - add new
  patcher types / legacy exe names without code changes.
- **Claude-desktop-style UI**: a left sidebar (Mod Builds · Library · Conflicts ·
  Activity · Settings), warm charcoal/clay theme, settings as a dedicated view.
  Built with **Tauri + React + shadcn/ui** over a **Python (FastAPI)** backend.

## Mod manager

Loose-file mods (Override/Modules/`dialog.tlk`) are fully reversible - disabling
moves their exact deployed files into a per-mod disabled store and restores them
on enable. TSLPatcher/HoloPatcher mods *patch shared files in place*, so they are
recorded as **baked** (captured via a before/after snapshot delta) and flagged as
not cleanly toggleable. Conflicts are computed from file overlap across enabled
mods: loose-vs-loose overwrites are warnings; baked-vs-baked merges are info.
State lives under `~/.kotor_mod_installer/` (`library/`, `disabled/`, `backups/`).

## Architecture

```
Tauri shell (Rust, single .exe)  ──embeds + spawns──▶  Python backend
  React + shadcn UI                    FastAPI: REST + WebSocket
       │  http/ws 127.0.0.1:8756              │
       └─────────────────────────────────────┘
                                   pipeline / scraper / detector /
                                   patcher_strategy / mod_manager
                                   (+ bundled HoloPatcher)
```

The backend exe is **embedded inside the main `.exe`** (`include_bytes!`),
extracted to a temp dir and launched on startup, then killed on exit. The whole
app ships as one self-contained file.

- `frontend/` - Tauri v2 app (React, Vite, Tailwind, shadcn/ui). `src-tauri/` is
  the Rust shell that embeds + spawns the backend and kills it on exit.
- `backend/server.py` - FastAPI wrapper exposing the pipeline + mod manager;
  streams live status/log/progress over a WebSocket.
- `installer/`, `scraper/`, `config.py` - Python backend logic.
- `scripts/` - one-off dev/analysis scripts (not part of the app).

## Download & run (no dependencies needed)

Grab the latest `KOTOR-Mod-Installer.exe` from the [Releases](../../releases)
page and run it - that's the whole app. It is a single self-contained file: the
Python backend and HoloPatcher are embedded; no Python, Node, Rust, or installer
needed. The app checks GitHub for newer releases on startup and can **update
itself with one click** (Settings → Updates → Download & install - it downloads
the new exe, swaps itself, and relaunches).

📖 **Usage guide & screenshots:** see the [project site](https://christophervr.github.io/kotor-mod-manager/)
(published from `docs/` via GitHub Pages).

## The HoloPatcher shim ("dynamic patcher")

TSLPatcher has no command line, and there are many legacy builds. Rather than
patching each `TSLPatcher.exe`, the app uses **HoloPatcher** - a headless,
open-source reimplementation that reads the *identical* `tslpatchdata` /
`changes.ini` / `namespaces.ini` format. One HoloPatcher engine installs **any**
TSLPatcher mod with no GUI.

**HoloPatcher is bundled inside the released exe automatically** - you don't need
to download or drop in anything. The build fetches it via
`tools/setup_holopatcher.py` and embeds it. The bottom bar shows the shim status.
You can still override the bundled copy with the `KOTOR_HOLOPATCHER_EXE`
environment variable or a `tools/HoloPatcher/HoloPatcher.exe` next to the app.

## Run from source (dev)

Prerequisites: Python 3.12, Node 20+, Rust (stable).

```bash
# 1. Python backend
pip install -r requirements.txt
python tools/setup_holopatcher.py          # fetch the headless shim once
python -m backend.server --port 8756       # runs the API (leave running)

# 2. Frontend (in another terminal)
cd frontend
npm install
npm run tauri dev                          # spawns its own backend + opens the app
```

`npm run tauri dev` launches the Rust shell, which embeds + spawns the backend -
so for a pure dev loop you usually only need step 2. Run the backend manually
(step 1) when iterating on Python, or to use the UI in a plain browser at
`http://localhost:5173`. (The Rust build embeds the backend exe at compile time,
so `frontend/src-tauri/binaries/kotor-backend.exe` must exist before building -
see below.)

## Build the single .exe locally

```bash
# 1. Build the Python backend exe and stage it for embedding.
pip install pyinstaller
python tools/setup_holopatcher.py
pyinstaller backend.spec --noconfirm
mkdir -p frontend/src-tauri/binaries
cp dist/kotor-backend.exe frontend/src-tauri/binaries/kotor-backend.exe

# 2. Build the Tauri app - the backend is embedded into the single .exe.
cd frontend && npm install && npx tauri build
# → frontend/src-tauri/target/release/kotor-mod-installer.exe   (one self-contained file)
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
- Both paths share `.github/workflows/_build.yml`, which builds the Python
  sidecar then the Tauri installer, so CI builds match released ones exactly.
  The released installer is fully self-contained (Python backend + HoloPatcher
  bundled). The release bump also syncs the version into `tauri.conf.json`,
  `frontend/package.json`, and `Cargo.toml`.

Commit messages should follow Conventional Commits, e.g. `feat: add pause/resume`,
`fix(pipeline): handle multi-file mods`, or `feat!: ...` / a `BREAKING CHANGE:`
footer for a major bump.

## License / disclaimer

This tool automates downloading from your own authenticated DeadlyStream account
and running mod-supplied installers. It bundles no mod content. HoloPatcher and
TSLPatcher are third-party tools owned by their respective authors.
