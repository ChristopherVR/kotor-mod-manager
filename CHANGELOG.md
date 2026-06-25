# Changelog

## [0.9.0] - 2026-06-25

### Features

- Guide you through mods that need a manual install
- Check your KOTOR folder before installing anything
- Pause a download and pick up right where it left off
- Open account settings by clicking your profile
- Make the menu click sound closer to KOTOR's
- Delete a mod from your library in one click
- Show why a mod failed to install
- Add your own mod builds, not just the built-in ones
- Configure the mod build source site in Account settings

### Bug Fixes

- Stop installs failing when antivirus briefly locks a file
- Keep the conflicts list from vanishing after you resolve one
- Make "Open download folder" actually open a folder
## [0.8.1] - 2026-06-22

### Miscellaneous

- Update the app's libraries and tools to their latest versions
- Merge dependency updates (23 Dependabot PRs)
## [0.8.0] - 2026-06-22

### Features

- Install each mod the way the build guide actually says
- Show each mod's install steps and what the app handles for you

### Testing

- Cover build-guide instruction parsing and selective install

### Miscellaneous

- Add build-guide audit and live-verification tooling
## [0.7.2] - 2026-06-21

### Documentation

- Show the app in action with fresh screenshots and demo clips

### Build & CI

- Keep the app's dependencies up to date automatically
- Tidy the Releases page each week, keeping the 5 newest downloads
## [0.7.1] - 2026-06-21

### Bug Fixes

- **security:** Avoid building a command string from a path in reveal_path
## [0.7.0] - 2026-06-21

### Features

- Simpler install screen and a peek button for your Nexus key
- Optional KOTOR menu click sound (off by default)
- **ui:** Library filters/thumbnails/context menus, log export, surface patcher errors
## [0.6.1] - 2026-06-21

### Build & CI

- Run the offline test suite before building

### Testing

- E2e download/install suite + fixes it surfaced
## [0.6.0] - 2026-06-21

### Features

- Nexus Mods API integration for accurate mod links
## [0.5.0] - 2026-06-21

### Features

- Cleaner screenshots, real Nexus links, folder import, mod selection
- **ui:** Conflict resolution actions, folder drag-drop, mod toggles

### Bug Fixes

- **scraper:** Keep only the real screenshot gallery
## [0.4.0] - 2026-06-21

### Features

- What's New panel and localization (en/es/de)

### Bug Fixes

- Image proxy, reliable external links, custom patcher, scraper names
- **ui:** Clickable build mods, screenshot lightbox, links, patcher, sidebar
- **ui:** Render inline bold in What's New; refresh screenshots
## [0.3.0] - 2026-06-21

### Features

- One-click self-update (download + swap + relaunch)
## [0.2.0] - 2026-06-21

### Features

- Game profiles, mod details, and explained conflicts
- **ui:** Sectioned settings, profile switcher, and mod detail panel

### Bug Fixes

- **changelog:** Render one bullet per line in cliff.toml template
## [0.1.1] - 2026-06-21

### Bug Fixes

- **ci:** Harden release version handling against shell injection
## [0.1.0] - 2026-06-21

### Features

- Auto-bundle HoloPatcher and add versioned release pipeline
- Replace Tkinter UI with Tauri + React + shadcn over a Python backend
- **library:** Mod manager with enable/disable, conflicts, and import
- **ui:** Claude-desktop-style shell with mod-manager views
- **backend:** Add /api/logout and document the mod manager
- Single self-contained exe, GitHub update check, declared conflicts
- **ui:** Deep-link views via URL hash

### Bug Fixes

- **scraper:** Thread slug through DeadlyStream download URLs
- **ci:** Always cut the first release on a tagless repo
- **ci:** Use git-cliff --tag instead of --bump for the changelog

### Refactor

- Move dev scripts to scripts/ and remove the legacy Tkinter UI

### Documentation

- Add GitHub Pages usage site with screenshots

### Miscellaneous

- Update Cargo.lock after dropping tauri-plugin-shell

