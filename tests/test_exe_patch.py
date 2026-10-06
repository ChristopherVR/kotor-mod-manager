"""Widescreen executable patches: all-or-nothing, fixed order, base file untouched."""
import struct

import pytest

from installer.exe_patch import PatchError, engine, hrmenus, pe, uniws

INI = """free text before any section
[Star Wars: KOTOR (800x600 interface)] 
details=ignored
sig=3D20030000EFEFEFEFEFEF58020000 
sigwild=000001111110000 
xoffset=1 
yoffset=11 
"""
SIG = bytes.fromhex("3D20030000") + b"\x01" * 6 + bytes.fromhex("58020000")


def _fake_exe(size=0x360000, steam=False) -> bytearray:
    d = bytearray(size)
    d[:2] = b"MZ"
    struct.pack_into("<I", d, 0x3C, 0x80)
    d[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", d, 0x84, 0x014C)
    struct.pack_into("<H", d, 0x96, 0x0102)
    if steam:
        d[0x200:0x208] = b".bind\0\0\0"
        struct.pack_into("<I", d, 0x3C, 0x180)
        d[0x180:0x184] = b"PE\0\0"
        struct.pack_into("<H", d, 0x184, 0x014C)
    for offs, val in ((hrmenus._NEG_X, -640), (hrmenus._NEG_Y, -480),
                      (hrmenus._POS_X, 640), (hrmenus._POS_Y, 480)):
        for o in offs:
            struct.pack_into("<h", d, o, val)
    struct.pack_into("<I", d, hrmenus._LETTERBOX, hrmenus._LETTERBOX_STOCK)
    d[0x1000:0x1000 + len(SIG)] = SIG
    return d


def test_full_chain_changes_expected_values():
    base = bytes(_fake_exe())
    out, applied = engine.patch_bytes(base, ["laa", "hrmenus", "uniws"], 1920, 1080, INI)
    assert applied == ["uniws", "hrmenus", "laa"]
    assert struct.unpack_from("<I", out, 0x1001)[0] == 1920
    assert struct.unpack_from("<I", out, 0x1000 + 11)[0] == 1080
    assert struct.unpack_from("<h", out, hrmenus._NEG_X[0])[0] == -1920
    assert struct.unpack_from("<h", out, hrmenus._POS_Y[2])[0] == 1080
    assert pe.is_large_address_aware(out)
    assert base == bytes(_fake_exe())          # input untouched


def test_laa_changes_one_byte_and_is_idempotent():
    base = bytes(_fake_exe())
    out, _ = engine.patch_bytes(base, ["laa"], 0, 0)
    assert sum(a != b for a, b in zip(base, out)) == 1
    again, _ = engine.patch_bytes(bytes(out), ["laa"], 0, 0)
    assert again == out


def test_mismatch_aborts_whole_build(tmp_path):
    base = _fake_exe()
    struct.pack_into("<h", base, hrmenus._POS_X[1], 123)      # one offset is off
    src, dest = tmp_path / "base.exe", tmp_path / "swkotor.exe"
    src.write_bytes(base)
    dest.write_bytes(b"old")
    with pytest.raises(PatchError):
        engine.build_patched_exe(src, dest, ["uniws", "hrmenus", "laa"], 1920, 1080, INI)
    assert dest.read_bytes() == b"old"
    assert not (tmp_path / "swkotor.exe.tmp").exists()


def test_uniws_needs_exactly_one_match():
    d = _fake_exe()
    d[0x2000:0x2000 + len(SIG)] = SIG
    with pytest.raises(PatchError):
        uniws.apply(d, uniws.parse_recipe(INI), 1920, 1080)


def test_steam_exe_is_refused_and_detected(tmp_path):
    steam = bytes(_fake_exe(steam=True))
    with pytest.raises(PatchError):
        engine.patch_bytes(steam, ["laa"], 0, 0)
    p = tmp_path / "swkotor.exe"
    p.write_bytes(steam)
    assert engine.exe_kind(p) == "steam"
    p.write_bytes(bytes(_fake_exe()))
    assert engine.exe_kind(p) == "plain"
    p.write_bytes(b"not an exe")
    assert engine.exe_kind(p) == "unknown"


def test_4_by_3_skips_letterbox():
    d = _fake_exe()
    struct.pack_into("<I", d, hrmenus._LETTERBOX, 0)           # would fail if checked
    hrmenus.apply(d, 1024, 768)
    assert struct.unpack_from("<h", d, hrmenus._POS_X[0])[0] == 1024
