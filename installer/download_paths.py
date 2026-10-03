"""Shared Windows-safe folder names for downloaded build mods."""

import re
from urllib.parse import quote


def download_folder_name(file_id: str, slug: str = "") -> str:
    """Keep logical IDs intact while encoding characters Windows rejects.

    External hosts use IDs such as ``guide:9``. Percent-encoding avoids both
    invalid paths and collisions with otherwise-valid IDs such as ``guide-9``.
    Existing numeric DeadlyStream IDs keep their original folder names.
    """
    reference = quote(file_id, safe="")
    safe_slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", slug[:30]).rstrip(" .")
    return f"{reference}_{safe_slug}"
