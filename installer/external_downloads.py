"""Download build entries from their actual host, rather than DeadlyStream."""

import re
from urllib.parse import parse_qs, urlparse

import config as cfg
from scraper import nexus
from scraper.deadlystream import DownloadError, download_name_excluded, select_keep_matches


def download_external(mod, dest_dir, client, progress_callback=None,
                      cancel_event=None, pause_event=None):
    """Use Nexus's API or a direct URL; keep site-only downloads actionable."""
    if mod.source_host == "nexus":
        key = nexus.load_api_key(cfg.load().get("nexus_api_key", ""))
        if not key:
            raise DownloadError("Add a Nexus API key in Settings > Account, or download "
                                f"the archive from {mod.url} into {dest_dir} and retry.")
        match = re.search(r"/mods/(\d+)", urlparse(mod.url).path)
        if not match:
            raise DownloadError("The build guide has an invalid Nexus mod URL.")
        mod_id = int(match.group(1))
        try:
            files = nexus.list_files(mod.game, mod_id, key)
            # Archived files are not offered by the guide's current download page.
            files = [f for f in files if f.get("category_id") not in (6, 7)]
            requested = parse_qs(urlparse(mod.url).query).get("file_id", [])
            if requested:
                files = [f for f in files if str(f.get("file_id")) == requested[0]]
            names = [f.get("file_name") or f.get("name", "") for f in files]
            if mod.directives.download_only:
                kept = select_keep_matches(names, mod.directives.download_only)
                files = [f for f, name in zip(files, names) if name in kept]
            elif not requested:
                files = [f for f in files if f.get("category_id") == 1]
            files = [f for f in files if not download_name_excluded(
                f.get("file_name") or f.get("name", ""), mod.directives.download_ignore)]
            if not files:
                raise DownloadError("No Nexus files match the build guide's download instructions.")
            if len(files) > 1 and not mod.directives.download_only:
                raise DownloadError(f"This Nexus mod offers multiple main files. Download "
                                    f"the guide's recommended files from {mod.url} into "
                                    f"{dest_dir}, then retry.")
            return [nexus.download_file(
                mod.game, mod_id, f["file_id"], dest_dir, key,
                progress_callback=progress_callback, cancel_event=cancel_event,
                pause_event=pause_event) for f in files]
        except (nexus.NexusAuthError, nexus.NexusDownloadError) as e:
            raise DownloadError(f"{e} Download the required archive from {mod.url} "
                                f"into {dest_dir} and retry.") from e

    if mod.source_host in ("direct", "github") and re.search(
            r"\.(zip|7z|rar|exe)(\?|$)", mod.url, re.I):
        path = client._download_from_url(
            mod.url, dest_dir, mod.file_id, progress_callback=progress_callback,
            cancel_event=cancel_event, pause_event=pause_event,
            fallback_name=urlparse(mod.url).path.rsplit("/", 1)[-1],
            keep_names=mod.directives.download_only,
            ignore_names=mod.directives.download_ignore)
        return [path] if path else []

    # Public MEGA/Drive pages need a host-specific transfer, not a request to
    # DeadlyStream with a guide ID. Cached archives are consumed before this call.
    raise DownloadError(f"Download the required archive from {mod.url} into "
                        f"{dest_dir}, then retry. Automatic downloads from this host "
                        "are not supported.")
