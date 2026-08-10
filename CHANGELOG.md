# Changelog

## [0.16.4] - 2026-08-10

### Bug Fixes

- Build the mod patcher from source so releases stop failing
## [0.16.3] - 2026-08-10

### Bug Fixes

- Keep a settings reset from picking up leftovers

### Testing

- Fix the long path check failing on machines that allow long paths
## [0.16.2] - 2026-08-10

### Bug Fixes

- Stop a damaged settings file from breaking the app for good

### Miscellaneous

- Bump actions/setup-node from 6 to 7
- Bump actions/setup-python from 6 to 7
- Bump taiki-e/install-action from 2 to 2.85.5
- Bump the cargo-minor-and-patch group across 1 directory with 4 updates
- Bump the npm-minor-and-patch group across 1 directory with 11 updates
- Update pillow requirement from >=12.2.0 to >=12.3.0
- Update fastapi requirement from >=0.138.1 to >=0.141.1
- Update uvicorn requirement from >=0.49.0 to >=0.52.1
- Update cryptography requirement from >=49.0.0 to >=50.0.0
- Update rarfile requirement from >=4.2 to >=4.5
- Clear a security warning and a build warning after the dependency updates
## [0.16.1] - 2026-07-27

### Bug Fixes

- Show every mod in a build, not just the ones from DeadlyStream
## [0.16.0] - 2026-07-27

### Features

- Follow the mod build guide's fine print automatically
- Download Nexus mods without leaving the app
- Clear conflicts and remove mods in bulk, and show what actually clashes
- Reset your game back to clean, and stop offering removals that cannot work
- Manage your downloaded mods, see where each comes from, and quieten the conflicts list
- Open your downloads folder from Settings
- Remember mod lists between visits, and flag mods you must fetch yourself
- Work out where each mod is downloaded from

### Bug Fixes

- Install mods buried inside long or nested folders
- Clear duplicate textures that can crash the game
- Stop a mod's patch installing before the mod itself
- Stop the conflicts list crying wolf, and let you clear it in bulk
- Stop flagging a mod's own add-on as incompatible with it
- Show what each mod changes instead of an unexplained conflict warning
- Make bulk uninstall actually run, and show it working

### Miscellaneous

- Build guide accuracy, conflict clarity, and mod management
## [0.15.8] - 2026-07-02

### Bug Fixes

- UI automation issues
## [0.15.7] - 2026-07-02

### Miscellaneous

- Update fastapi requirement from >=0.138.0 to >=0.138.1
- Update requests requirement from >=2.31.0 to >=2.34.2
- Bump actions/setup-python from 5 to 6
- Bump actions/upload-artifact from 4 to 7
- Bump softprops/action-gh-release from 2 to 3
- Bump the npm-minor-and-patch group across 1 directory with 7 updates
## [0.15.6] - 2026-07-02

### Bug Fixes

- Stop double installs, wrong-language patches, and reinstall crashes

### Build & CI

- Run the full offline test suite on every build

### Testing

- Add a test that installs every mod in a build guide
## [0.15.5] - 2026-06-27

### Bug Fixes

- Mod download and compatibility issues
## [0.15.4] - 2026-06-27

### Bug Fixes

- Hide no-action conflicts, skip installed mods on Select All, and cache mod details to disk
## [0.15.3] - 2026-06-27

### Bug Fixes

- Extract archives with very long paths and fix the pywinauto fallback crash
## [0.15.2] - 2026-06-27

### Bug Fixes

- Stream HoloPatcher logs live and stop it immediately when you cancel
## [0.15.1] - 2026-06-27

### Bug Fixes

- Prevent path traversal in build-guide file deletion
## [0.15.0] - 2026-06-27

### Features

- Automatically handle mod conflicts, ordering rules, and pre-install cleanup
## [0.14.6] - 2026-06-26

### Bug Fixes

- Stop the installer crashing when a mod includes a loose texture file
## [0.14.5] - 2026-06-26

### Bug Fixes

- Stop the installer showing Finished with 0 mods done when something went wrong mid-run
## [0.14.4] - 2026-06-26

### Bug Fixes

- Add disable buttons to file-conflict cards in the Conflicts tab
## [0.14.3] - 2026-06-26

### Bug Fixes

- Stop conflicts count from growing and remove duplicate mod names
## [0.14.2] - 2026-06-26

### Bug Fixes

- Remove encoding error in mod manager that blocked app startup
## [0.14.1] - 2026-06-26

### Testing

- Add coverage for download filtering and folder exclusion parsing
## [0.14.0] - 2026-06-26

### Features

- Auto-apply compat patches and multi-run patcher options during install
- Automate all known mods so none require manual installation steps
## [0.13.0] - 2026-06-26

### Features

- Read more install details from the build guide automatically
## [0.12.0] - 2026-06-26

### Features

- Automatically handle most mods that previously needed manual install
## [0.11.0] - 2026-06-26

### Features

- Fix download restarts, show manual install readme, and overhaul the conflicts page
## [0.10.1] - 2026-06-26

### Bug Fixes

- Build error caused by TypeScript narrowing in library event handler
- Show friendly install method names in the mod library
## [0.10.0] - 2026-06-26

### Features

- Download up to 3 mods at the same time to save waiting

### Bug Fixes

- App build error after adding library change detection
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
- Show which mods are already installed when you load a mod list

### Bug Fixes

- Stop installs failing when antivirus briefly locks a file
- Keep the conflicts list from vanishing after you resolve one
- Make "Open download folder" actually open a folder
- Keep the conflicts badge in sync and make conflicts easier to understand
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

