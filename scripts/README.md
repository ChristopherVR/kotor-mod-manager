# Dev / analysis scripts

One-off scripts used while building and analysing the KOTOR mod data. They are
**not** part of the shipped app — the application scrapes live at runtime.

| Script | Purpose |
|---|---|
| `explore_sites.py` | Probe the neocities build-guide pages. |
| `lookup_urls.py` | Resolve build-page URLs. |
| `scrape_order.py` | Scrape mods in recommended install order. |
| `scrape_build_detail.py` | Scrape full per-mod notes + option hints. |
| `analyze_mods.py` / `deep_analyze.py` | Classify install methods across the mod set. |
| `sample_download.py` | Download/unpack sample mods to inspect their structure. |
| `sample_results.json` | Captured structure analysis of sample mods. |

Run from the project root, e.g. `python scripts/scrape_order.py`.
