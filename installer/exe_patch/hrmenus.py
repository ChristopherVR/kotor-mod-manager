"""
High Resolution Menus patch for swkotor.exe (port of the mod's hires_patcher.pl).

The original script writes the file even when its checks fail. This one checks
every location first and changes nothing unless all of them match.
"""
from __future__ import annotations

import struct

from installer.exe_patch import PatchError

# Offsets in the v1.03 executable, each holding a signed 16-bit menu limit.
_NEG_X = (0xB6C7, 0xBA6C)
_NEG_Y = (0xB6DA, 0xBA83)
_POS_X = (0xAA65, 0x292959, 0x2928B3)
_POS_Y = (0xAA85, 0x29296B, 0x2928C3)
# Dialog letterbox scale (a 32-bit float; stock value 0.42857149).
_LETTERBOX = 0x355788
_LETTERBOX_STOCK = 0x3EDB6DB9


def apply(data: bytearray, width: int, height: int, letterbox: bool = True) -> None:
    checks = [(o, -640) for o in _NEG_X] + [(o, -480) for o in _NEG_Y] \
        + [(o, 640) for o in _POS_X] + [(o, 480) for o in _POS_Y]
    try:
        ok = all(struct.unpack_from("<h", data, o)[0] == v for o, v in checks)
        if letterbox and (width * 3) != (height * 4):
            ok = ok and struct.unpack_from("<I", data, _LETTERBOX)[0] == _LETTERBOX_STOCK
    except struct.error:
        ok = False
    if not ok:
        raise PatchError(
            "The high resolution menus patch does not fit this copy of the game "
            "(it needs the unprotected version 1.03 program file).")
    for offs, val in ((_NEG_X, -width), (_NEG_Y, -height), (_POS_X, width), (_POS_Y, height)):
        for o in offs:
            struct.pack_into("<h", data, o, val)
    if letterbox and (width * 3) != (height * 4):
        struct.pack_into("<f", data, _LETTERBOX, 1.0 / ((width / height) * 1.75))
