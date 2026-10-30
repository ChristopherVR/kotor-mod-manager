# Build download and installation-choice audit

Checked 30 October 2026 against all four live guides:
[K1 full](https://kotor.neocities.org/modding/mod_builds/k1/full),
[K1 spoiler-free](https://kotor.neocities.org/modding/mod_builds/k1/spoiler-free),
[K2 full](https://kotor.neocities.org/modding/mod_builds/k2/full), and
[K2 spoiler-free](https://kotor.neocities.org/modding/mod_builds/k2/spoiler-free).

## Download findings and changes

| Build | Scraped entries | Explicit external patches now retained |
| --- | ---: | ---: |
| K1 full | 200 | 9 |
| K1 spoiler-free | 194 | 10 |
| K2 full | 157 | 4 |
| K2 spoiler-free | 149 | 4 |

These are scraper entry counts, including auxiliary guide links, rather than
counts of independent mods. Patch counts cover links in Name paragraphs and
overlap across builds. Conditional patch links buried in installation instructions
are not newly automated; they need dependency-aware rules before being fetched.

- **A patch is not a mirror.** Ultimate Korriban, Taris Reskin and Ultimate Dxun
  could resolve to only their MEGA patch, skipping their Nexus main download.
  External patches for DeadlyStream mods were omitted altogether. The scraper now
  retains explicit patch links on the primary entry; the pipeline downloads each
  into its own folder. The cache records source URLs and all payloads, so legacy
  patch-only downloads are not reused as complete mods.
- **Offsite instructions were parsed from the wrong element.** Passing the Name
  paragraph to `_gather_block` could read the whole surrounding container instead
  of its labelled sibling fields. Installation methods and download filters now
  come from the actual per-mod block.
- **Dropbox shared pages need download mode.** The Remote Tells Influence TSLRCM
  patch's `dl=0` link is now resolved with `dl=1`, retaining link access parameters.
- **NTCore is a landing page.** The legacy `?page_id=371` URL redirects to the
  [4GB Patch page](https://ntcore.com/4gb-patch/). The new handler follows its
  official archive link. K1's existing built-in executable-patching flow remains
  responsible for its 4GB step; adding download support does not make arbitrary
  executable patchers automatically installable.
- **GameFront remains browser-assisted.** The two affected mods are
  [Vurt's Ebon Hawk](https://www.gamefront.com/games/knights-of-the-old-republic/file/vurt-s-k1-hi-res-ebon-hawk-retexture)
  and [Remote Tells Influence](https://www.gamefront.com/games/knights-of-the-old-republic-ii/file/remote-tells-influence).
  Direct HTTP requests returned 403 and the test browser showed BHB-001,
  “Outdated Browser.” Interactive installs now open the source page and reuse the
  existing settled-file watcher. The player saves the download in the configured
  downloads folder, then installation continues. Unattended GameFront downloading
  was not verified and is not advertised as supported. A future embedded-browser
  integration would need a working, permitted browser download flow and a reliable
  download-completion event before it could remove the save-folder step.

### Follow-up: authenticated GameFront routes

GameFront's [official API](https://www.gamefront.com/api) uses personal bearer
tokens created under [Account API Keys](https://www.gamefront.com/account/api-keys).
Its [OpenAPI contract](https://www.gamefront.com/api-specs/graphql-v1-openapi.yaml)
requires the `graphql:read` ability and a descriptive User-Agent. This route was
missed in the initial browser-download investigation.

Live checks using the user-provided `.env` credentials on 30 October 2026:

- `GAME_FRONT_API_KEY` authenticated successfully: GraphQL returned HTTP 200,
  no query errors, and the expected metadata for Vurt's Ebon Hawk (152846) and
  Remote Tells Influence (72832).
- The live schema rejected `File.download_url` as an unsupported field. Its
  documented `downloads` field is a count; `url` points to the public mod page.
  The exhaustive published schema lists no archive-download operation.
- Supplying the bearer token to the ordinary mod download page still returned
  HTTP 403 and a browser verification page. Successful metadata authentication
  therefore does not establish unattended archive-download support.
- A visible browser reached the login form. The initial `GAME_FRONT_USERNAME`
  was a username, but the form requires an email address and prevented submission.
  After the account email was supplied, the login POST returned HTTP 403 and
  opened an embedded robot-verification check. No authenticated session was
  confirmed by the automated probe; this is not evidence of a bad password.
- A separate signed-out visible browser opened the mod page, but clicking
  Download opened an embedded robot-verification check that remained loading.
  No archive was received during these probes.
- The user subsequently confirmed that signing in and waiting completed the
  browser download. The resulting `vurt_k1_eh_retexture_v10.rar` was found in
  the user's Downloads folder. A copy was placed in the isolated browser-assist
  test folder; the running production download stage detected and filed it,
  then parsed all 11 archive entries (94,724,263 bytes). The smoke test passed;
  no game files were installed and the original download was retained.
- The browser-issued archive URL uses `osiris.gamefront.com` and an AWS SigV4
  query with `X-Amz-Expires=3600` (one hour). A fresh request using the manager's
  direct downloader, without browser cookies, returned HTTP 403 and GameFront's
  HTML Security Check while the link was still within that period. Possessing
  a current signed URL alone did not enable unattended HTTP downloads in this
  test. The URL and its signature are deliberately not stored in this report.

An eventual account integration should use an OS-keyring-backed API token for
documented metadata operations, and clearly distinguish token validity from
download capability. User-driven browser login/download and manager ingestion
are now verified for Vurt's archive; unattended login/download is not verified.
No credentials, cookies or tokens are recorded in this report or committed.

### Implemented: reusable GameFront browser sessions

The desktop app now opens GameFront in a dedicated WebView2 profile at the app's
local data directory, under `gamefront-profile`. Sign in on GameFront and choose
**Stay logged in**. The browser retains authentication and verification state
across app restarts. Settings → Account → GameFront reopens that session; Logout
on GameFront signs it out. The regular-browser fallback remains available.

Downloads stay in that authenticated browser. The Python pipeline publishes one
active GameFront job at a time; the frontend opens or reopens it by stable ID.
The native download callback accepts GameFront's archive host, stages the file
inside the matching mod folder, checks successful completion and archive magic,
then moves it into the folder watched by the installer. Cancelled/stale jobs do
not promote files. Cookies, passwords and signed URLs never cross the app's
frontend/backend bridge. The remote window has no main-window IPC privileges.

Live Windows verification on 2026-10-30 used the Rust example, which imports the
production browser module with the same persistent profile:

- The user signed in once with **Stay logged in**. The app was closed and
  restarted between downloads; no further credentials were entered.
- **Remote Tells Influence:** `remote_influence.zip`, 10,088 bytes, three entries,
  full ZIP CRC check passed.
- **Vurt's Ebon Hawk:** RAR, 94,724,263 bytes, eleven entries. SHA-256 matched the
  original successful regular-Chrome download byte for byte.
- Both completed archives reached their final test folders through the native
  download callback. Nothing was installed into a game.
- Testing found and fixed Windows path normalization at both download start and
  completion: WebView2 rejects mixed separators and strips the extended-path
  prefix when reporting completion. A regression test also covers failed
  transfers whose partial file has already been removed.

There are separate lifetimes for account authentication, browser verification
and the signed archive URL. The observed archive URL expires after one hour;
that is not the login lifetime. Cookie metadata showed a two-hour session cookie
plus persistent remember-login and verification cookies. Server invalidation
and future verification requirements remain under GameFront's control. Session
reuse is verified across immediate restarts, not guaranteed for a fixed number
of days. Cookie replay into Python is not needed or claimed.

The earlier API-key test succeeded for metadata but did not provide an archive
endpoint. Direct HTTP password/archive requests did not pass the access check.
Those results are separate from this successful native-browser route.

Sources: [Tauri browser profile and download APIs](https://docs.rs/tauri/2.12.2/tauri/webview/struct.WebviewWindowBuilder.html),
[Tauri cookie API](https://docs.rs/tauri/2.12.2/tauri/webview/struct.WebviewWindow.html#method.cookies_for_url),
and [WebView2 profile persistence](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/overview-features-apis).
See `scripts/README.md` for the repeatable download-only test procedure.

## Cutscene choices implemented

[K1 Cutscenes Rescaled](https://deadlystream.com/files/file/2380-k1-cutscenes-rescaled/)
currently lists eight resolution/frame-rate files, approximately 15–16 GB each.
[K2 Cutscenes Rescaled](https://deadlystream.com/files/file/2503-k2-cutscenes-rescaled/)
lists four main packs around 22 GB and four corresponding `_mods` packs around
2.3 GB. Sizes were read from the live download pickers, without fetching these
large payloads.

- The existing K1 resolution/frame-rate picker remains in use.
- K2's prose parser previously produced `download_only=["_mods"]`, dropping the
  main movies and bypassing the resolution picker. Curated rules now clear that
  filter. The picker offers main resolutions and downloads exactly the selected
  main pack plus its same-resolution/frame-rate add-on. A missing companion is
  an error; it does not silently install an incomplete selection.
- After extraction, the Rescaled packs get a dedicated install plan. Files with
  identical destinations are grouped by their source folders. The player picks
  one folder for each group, covering subtitle and legal-screen alternatives
  without silently overwriting one style with another.
- K2 add-on component folders are opt-in. Players choose which installed mods'
  replacement movies to apply. Selected replacements take precedence over main
  movies. Movies go to `Movies`; legal-screen textures go to `Override`.
- All choices finish before copying any cutscene files. Skipping a question skips
  the pack. Synthetic archive tests verify destination paths, replacement order,
  group selection and cancellation without game-file writes.

## Other choices identified for a later implementation

These have live guide evidence, but were not given new option controls in this
change. They need verified archive/namespace metadata and, where relevant,
cross-mod compatibility rules rather than interpreting free-form prose alone.

| Mods | Choice | Implementation consideration |
| --- | --- | --- |
| KOTOR Dialogue Fixes | Corrections only / PC Response Moderation | The pipeline currently uses guide preferences for TLK replacement; expose the real TLK variants. |
| Better Twi'lek Heads (K1/K2) | Slim / original necks | Dependent NPC-diversity patches must follow the same choice. |
| Ajunta Pall Unique Appearance | Transparent / opaque; optional Sith eyes | Preserve patch-first ordering, then choose texture folders. |
| HD Darth Malak; Ithorians HD | Eye colour / base versus Vurt texture | Some are archive choices and others are folders inside an archive. |
| HQ Skyboxes II; HQ Cockpit Skyboxes | Texture size | Unlike screen-resolution movie packs, filenames may use `1k` or folders such as Medium; dependent Yavin files must match. |
| Taris Rapid Transit; Swoop Platform Model Repair | Full / light variants | Nexus currently defaults to a primary/newest file; explicit alternative selection needs a separate file-choice model. |
| Senni Vek; Thematic KOTOR 2 Companions; Thematic Sith Lords | Gameplay/namespace options | Do not replace compatibility requirements with an arbitrary namespace choice. Some require multiple ordered patcher runs. |
| Yavin Station Hangar; Main Menu Fix for Widescreen | Optional forcefield / logo | Combine the main install with selected add-ons, rather than treating every option as mutually exclusive. |

The existing high-resolution menu/executable patch flow already uses the selected
screen resolution. This work does not replace it or expose every optional patcher
namespace as a free choice.

## Validation and limits

- Fresh HTTP scrape of all four guides and live DeadlyStream download-record lists.
- Live downloads of NTCore's 21,464-byte ZIP and the Dropbox patch's 10,766-byte
  ZIP; both parsed successfully as archives. Nothing was executed or installed.
- Full Python suite: 367 passed, 13 skipped. Native Rust: four tests passed.
  Frontend: `npm run build` passed, including TypeScript checking.
- Follow-up cache tests cover mismatched K2 add-ons and newly arrived browser
  downloads for a mod with linked patches.
- Full-size cutscene archives were not downloaded or installed into a real game.
  The option planner is tested with synthetic layouts based on the authors'
  published alternatives and reads the actual folder choices at install time.
- GameFront's user-driven signed-in download and real-archive ingestion passed
  the isolated smoke test. API authentication passed for metadata; automatic
  password login and direct HTTP archive download did not pass the access check.
- The production native browser module passed live downloads of both GameFront
  archives across process restarts after one login. The complete packaged
  installer was not run against a game; pipeline handoff/cancellation were
  checked by automated tests.
