# Dev / analysis scripts

One-off scripts used while building and analysing the KOTOR mod data. They are
**not** part of the shipped app - the application scrapes live at runtime.

| Script | Purpose |
|---|---|
| `explore_sites.py` | Probe the neocities build-guide pages. |
| `lookup_urls.py` | Resolve build-page URLs. |
| `scrape_order.py` | Scrape mods in recommended install order. |
| `scrape_build_detail.py` | Scrape full per-mod notes + option hints. |
| `analyze_mods.py` / `deep_analyze.py` | Classify install methods across the mod set. |
| `sample_download.py` | Download/unpack sample mods to inspect their structure. |
| `sample_results.json` | Captured structure analysis of sample mods. |
| `test_gamefront_assist.py` | Interactive GameFront browser handoff test; downloads only, with results in a separate Downloads subfolder. |

### GameFront persistent-session test (desktop)

The Rust example uses the production browser module and the desktop app's
isolated GameFront profile. It never starts the installer or changes game files.
From `frontend/src-tauri`, run:

```powershell
cargo run --example gamefront_session -- signin
```

Sign in, choose **Stay logged in**, and close the window. Restart with
`cargo run --example gamefront_session -- vurt`, then `remote`, closing the
window between runs. Each should retain the account without entering credentials
again. Click the site's Download button if shown. Archives go under
`~/Downloads/KOTOR_GameFront_Session_Test/{vurt,remote}`. Inspect the archives
after completion; files in hidden `.gamefront-*` staging folders are incomplete.
The probe prints cookie names/expiry flags only, never token values. It does not
enable browser debugging or copy cookies from regular Chrome.

Run from the project root, e.g. `python scripts/scrape_order.py`.
