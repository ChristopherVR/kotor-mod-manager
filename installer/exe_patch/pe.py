"""Windows executable (PE) helpers."""
from __future__ import annotations

import struct

from installer.exe_patch import PatchError

_IMAGE_FILE_32BIT_MACHINE = 0x0100
_IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x0020
_MACHINE_I386 = 0x014C


def _characteristics_offset(data: bytes | bytearray) -> int:
    """File offset of the PE 'characteristics' field; PatchError if not a 32-bit exe."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PatchError("This is not a Windows program file.")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise PatchError("This is not a Windows program file.")
    if struct.unpack_from("<H", data, pe + 4)[0] != _MACHINE_I386:
        raise PatchError("This is not a 32-bit program, so the 4GB setting does not apply.")
    return pe + 22


def is_large_address_aware(data: bytes | bytearray) -> bool:
    off = _characteristics_offset(data)
    return bool(struct.unpack_from("<H", data, off)[0] & _IMAGE_FILE_LARGE_ADDRESS_AWARE)


def set_large_address_aware(data: bytearray) -> bool:
    """Set the 4GB (large address aware) flag. Returns True if it changed anything."""
    off = _characteristics_offset(data)
    flags = struct.unpack_from("<H", data, off)[0]
    if flags & _IMAGE_FILE_LARGE_ADDRESS_AWARE:
        return False
    struct.pack_into("<H", data, off, flags | _IMAGE_FILE_LARGE_ADDRESS_AWARE)
    return True


def has_steam_drm(data: bytes | bytearray) -> bool:
    """True for the Steam release, whose code sits inside a copy-protection wrapper
    (SteamStub adds a '.bind' section to the program)."""
    return b".bind\0\0\0" in bytes(data[:4096])
