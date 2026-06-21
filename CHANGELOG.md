# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org) and
[Conventional Commits](https://www.conventionalcommits.org).

## [0.1.1] - 2026-06-21

### Bug Fixes
- **ci:** Harden release version handling against shell injection
## [0.1.0] - 2026-06-21

### Features
- Auto-bundle HoloPatcher and add versioned release pipeline- Replace Tkinter UI with Tauri + React + shadcn over a Python backend- **library:** Mod manager with enable/disable, conflicts, and import- **ui:** Claude-desktop-style shell with mod-manager views- **backend:** Add /api/logout and document the mod manager- Single self-contained exe, GitHub update check, declared conflicts- **ui:** Deep-link views via URL hash
### Bug Fixes
- **scraper:** Thread slug through DeadlyStream download URLs- **ci:** Always cut the first release on a tagless repo- **ci:** Use git-cliff --tag instead of --bump for the changelog
### Refactor
- Move dev scripts to scripts/ and remove the legacy Tkinter UI
### Documentation
- Add GitHub Pages usage site with screenshots
### Miscellaneous
- Update Cargo.lock after dropping tauri-plugin-shell

