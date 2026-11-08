# Sign in with Nexus Mods (OAuth 2.0 + PKCE)

Players connect the app to Nexus Mods by signing in with their Nexus account.
It follows the Nexus guide
[Using OAuth 2.0 and PKCE in your application](https://modding.wiki/en/api/oauth2-guide).
The app never asks for a password or a personal API key.

## Registration details for Nexus Mods

| Field | Value |
| --- | --- |
| Application name | KOTOR Mod Installer |
| Short description | Downloads and installs the recommended community mod builds for Knights of the Old Republic 1 and 2 in one go, including Nexus-hosted mods, with automatic patching and conflict checks. |
| Logo | `frontend/src-tauri/icons/icon.png` (works on a dark background) |
| Source code | https://github.com/ChristopherVR/kotor-mod-manager (GPL-3.0-only) |
| Callback URI | `http://127.0.0.1:8756/nexus/oauth/callback` |
| Client type | Public (desktop app, PKCE with S256, no client secret) |
| Scopes | None (empty scope, as in the guide) |

The port never changes. The desktop app always starts its local backend on
`127.0.0.1:8756`, so the callback URI is the same on every machine.

## How it works

| Step | What the app does |
| --- | --- |
| Authorize | Opens `https://users.nexusmods.com/oauth/authorize` in the player's browser with `client_id`, `response_type=code`, `scope=` (empty), `redirect_uri`, a random `state`, `code_challenge_method=S256` and `code_challenge`. |
| Callback | The app's local backend already listens on `127.0.0.1:8756`, so the callback is a route on it. The guide recommends this kind of local listener for desktop apps. The `state` is checked before anything else. |
| Token | POSTs `grant_type=authorization_code`, `redirect_uri`, `scope`, `client_id`, `code` and `code_verifier` to `https://users.nexusmods.com/oauth/token`. |
| Verify | Checks the access token's RS256 signature against the Nexus public key from the guide and the keys at `/oauth/discovery/keys`, then reads `user.username` and `user.membership_roles` from it. |
| API calls | Every v1 request sends `Authorization: Bearer <access token>` along with the `Application-Name` and `Application-Version` headers. |
| Refresh | Before each request, the app checks `expires_in`. Once the token has expired, it swaps the refresh token for a new one. A 4xx response from the token endpoint means the player revoked access, so the app signs them out and asks again. |
| Sign out | Calls `https://users.nexusmods.com/oauth/revoke` (best effort) and deletes the local copy. |
| Storage | Tokens stay in the OS keyring (Windows Credential Manager), never in a file and never on a server. |

Downloads keep the usual Nexus rules. Premium accounts download directly. Free
accounts download only after the player clicks "Mod manager download" on the mod
page, which hands the app an `nxm://` link.

## Turning sign-in on

The **Sign in with Nexus Mods** button (Settings > Account, and the first-run
setup) stays disabled until the app has a client ID. Once Nexus Mods issues
one, set `CLIENT_ID` in `scraper/nexus_oauth.py` and rebuild.

Developers can try a client ID without rebuilding by starting the app with the
`KMI_NEXUS_CLIENT_ID` environment variable set.
