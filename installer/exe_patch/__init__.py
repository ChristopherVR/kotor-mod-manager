"""
Editing the game executable for widescreen, without touching the original.

Each patch works on an in-memory copy of the bytes and either applies in full
or raises PatchError, so a file that is not the expected executable is never
half-written. engine.build_patched_exe() runs them in the one order that works.
"""


class PatchError(Exception):
    """The executable is not the one this patch expects, or the input is bad."""
