# Nexus Mods listing and publishing

This folder keeps the manager's Nexus listing text alongside the release pipeline.
It follows the `kotor-coop` setup: paste the page BBCode manually, then let GitHub
Actions upload each new file version to separate Windows and Linux file groups.

## Page checklist

| Field | Value |
| --- | --- |
| Name | KOTOR Mod Installer |
| Summary | Download, install and manage recommended community mod builds for KOTOR 1 and 2 from one standalone app. Includes automatic patching, conflict checks and updates. |
| Game | Knights of the Old Republic, with KOTOR 2 support explained in the description |
| Category | Utilities, or the nearest available tools category |
| Description | Paste `description.bbcode` into the BBCode editor |
| Version | The version of the first uploaded release, without the leading `v` |
| Primary image | `../docs/images/01-builds.png` |
| Gallery | `../docs/images/02-library.png` through `06-activity.png` |
| Source / support | `https://github.com/ChristopherVR/kotor-mod-manager` |
| Requirements | A copy of KOTOR 1 and/or KOTOR 2, 64-bit Windows or an x86_64 Linux desktop, and internet access |
| Permissions | GPL-3.0-only, see `../LICENSE` and the source repository |
| Adult content | No |

The BBCode embeds existing screenshots and GIFs from the public repository. Push
those files before pasting the description. Upload gallery images separately.
The page description and gallery are not updated by the release action.

This is a standalone application, not a game-directory mod. Use **Manual
download**, extract it into its own folder, then run the app. The workflow
explicitly disables mod-manager downloads so Vortex does not deploy it as a mod.

## One-time setup

1. Create a **new manager listing** on Nexus Mods. Do not reuse the co-op listing.
2. From a GitHub release with Nexus packaging, download both packages:
   - Windows: `kotor-mod-installer-<version>-nexus.zip`
   - Linux: `kotor-mod-installer-<version>-linux-nexus.zip`
   Upload them manually as **two separate Main files** on the same listing to
   create two file groups. Disable mod-manager downloads for both initial files.
3. Find each numeric **file ID** using the Advanced option on the public Files tab
   or the edit menu on Manage Files. This is the file group ID, not the mod page
   ID and not a file version ID. See the
   [official upload action instructions](https://github.com/Nexus-Mods/upload-action#how-to-find-the-file-id--mod-id).
4. In this GitHub repository, open **Settings > Secrets and variables > Actions**:
   - Add repository **variable** `NEXUS_FILE_ID` with the Windows file group ID.
   - Add repository **variable** `NEXUS_LINUX_FILE_ID` with the Linux file group ID.
     These must be different IDs so an update never archives the other platform.
   - Add repository **secret** `NEXUSMODS_API_KEY` with an API key for the Nexus
     account that can upload to this listing. Never commit the key.
5. Paste `description.bbcode` into the listing and add the gallery images.
6. The next release publishes to both GitHub and Nexus. If its Nexus job already
   failed because configuration was missing, use **Re-run failed jobs** instead.

The first manual uploads bootstrap the groups. Configure the workflow for the next
version rather than re-uploading that same version through Actions.

## Release pipeline

The existing versioning and build triggers are unchanged:

1. A releasable push to `main` computes the version, updates the changelog and
   project versions, and pushes the release commit and tag.
2. `_build.yml` builds and tests Windows and Linux, then scans both downloads
   with ClamAV. A failed build, test or scan prevents publication.
3. `tools/package_nexus.py` wraps each scanned executable without modifying its
   contents. Each platform gets its own ZIP containing:
   - `KOTOR-Mod-Installer.exe` or `KOTOR-Mod-Installer-linux-x86_64`
   - `READ-ME-FIRST.txt` with player setup and standalone-app instructions
   - `virus-scan.txt`, the same report attached to the GitHub release
   - `LICENSE`
   - `SHA256SUMS.txt` for the other files inside the ZIP
   The Linux ZIP sets executable permissions and explains `chmod +x` for archive
   tools that do not preserve them. Linux requires GTK 3 and WebKitGTK 4.1 runtime
   libraries provided by the player's distribution.
4. The GitHub release carries the Windows and Linux executables, scan report,
   both Nexus ZIPs, and `description.txt` / `description-linux.txt` containing
   platform-specific instructions and this version's release notes.
5. The `nexus` matrix job in `release.yml` downloads each published ZIP and description
   from that exact GitHub release, then uses
   `Nexus-Mods/upload-action@v1.0.0-beta.11` to create a **Main** file version,
   archive the previous version of that platform and update the mod page version.
   Uploads run sequentially, with fail-fast disabled so a failure on one platform
   does not prevent the other from publishing.
6. Each platform attaches its own marker (`nexus-published.json` for Windows,
   `nexus-published-linux.json` for Linux) to the GitHub release after success so
   a completed upload is skipped when the job is rerun. The release workflow's
   existing concurrency group serializes GitHub and Nexus publication together.

Both platforms are published on Nexus and GitHub. Pull-request and manual
**CI Build** runs never publish to Nexus and do not receive Nexus credentials.
The app's existing GitHub updater is unchanged.

## Failures and retries

Missing credentials or an invalid file ID fail the Nexus job visibly. The
already published GitHub release stays available. Fix the settings and select
**Re-run failed jobs** on that Release run; no build artifact retention is needed
because the ZIP and description are GitHub release assets.

The publication marker protects completed jobs, not the small interval between
the Nexus upload succeeding and the marker reaching GitHub. If an upload times
out, or the marker step fails, inspect the Nexus Files tab before retrying. Do
not blindly upload the same version twice. This limitation also exists in the
co-op pipeline. Keep the release assets until any pending Nexus retry is resolved
(the repository separately prunes older GitHub releases).

Nothing in this setup publishes or edits the live Nexus page until the workflow
runs with the configured credentials. There is no hardcoded co-op mod or file ID.

## Local checks

Run the packaging and release-notes tests without building the desktop app:

```powershell
python -m pytest tests/test_package_nexus.py tests/test_release_notes.py -q
```

After preparing real release downloads, notes and a successful scan report:

```powershell
python tools/package_nexus.py v1.2.3 --repository ChristopherVR/kotor-mod-manager
python tools/package_nexus.py v1.2.3 --repository ChristopherVR/kotor-mod-manager --platform linux
```

The packaging tool requires all inputs but does not run or interpret the antivirus
scan itself. In CI it only runs after the existing scan step succeeds.
