"""File operations should survive a brief Windows lock (WinError 32) by retrying."""
import pytest

from installer.fs_retry import is_lock_error, with_lock_retry


def _winerror(code: int) -> OSError:
    e = OSError("locked")
    e.winerror = code
    return e


def test_is_lock_error_only_for_sharing_violations():
    assert is_lock_error(_winerror(32))
    assert is_lock_error(_winerror(33))
    assert not is_lock_error(_winerror(2))      # file-not-found is not a lock
    assert not is_lock_error(ValueError("nope"))


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _winerror(32)
        return "ok"

    assert with_lock_retry(flaky, attempts=5, delay=0) == "ok"
    assert calls["n"] == 3


def test_gives_up_after_attempts():
    def always_locked():
        raise _winerror(32)

    with pytest.raises(OSError):
        with_lock_retry(always_locked, attempts=3, delay=0)


def test_non_lock_errors_propagate_immediately():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise _winerror(2)  # not a lock - should not be retried

    with pytest.raises(OSError):
        with_lock_retry(boom, attempts=5, delay=0)
    assert calls["n"] == 1
