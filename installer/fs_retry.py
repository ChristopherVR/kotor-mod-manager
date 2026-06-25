"""
Retry helper for transient Windows file locks.

On Windows, antivirus and the search indexer briefly hold a just-written file
open, so opening/extracting/renaming it immediately can fail with
"[WinError 32] The process cannot access the file because it is being used by
another process". The lock clears within a moment, so we retry a few times
before giving up.
"""
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# WinError 32 = sharing violation, 33 = lock violation.
_LOCK_WINERRORS = (32, 33)


def is_lock_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in _LOCK_WINERRORS


def with_lock_retry(fn: Callable[[], T], *, attempts: int = 10, delay: float = 0.3) -> T:
    """Call fn(), retrying only on a Windows file-lock error (WinError 32/33)."""
    last: BaseException | None = None
    for _ in range(attempts):
        try:
            return fn()
        except OSError as e:
            if not is_lock_error(e):
                raise
            last = e
            time.sleep(delay)
    assert last is not None
    raise last
