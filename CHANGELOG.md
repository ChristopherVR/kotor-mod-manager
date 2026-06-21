# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org) and
[Conventional Commits](https://www.conventionalcommits.org).

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

