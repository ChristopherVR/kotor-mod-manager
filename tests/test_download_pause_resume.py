"""
Pause/resume and cancel behaviour for downloads.

A paused download must stop in place and keep its partial file, then continue
from exactly where it left off (via an HTTP range request) when resumed - never
re-downloading from scratch and never dropping bytes. A cancelled download must
leave no partial file behind.

These drive the real download loop with a fake HTTP session so they're fast and
deterministic (no network).
"""
import threading

import pytest

from scraper.deadlystream import DeadlyStreamClient, DownloadError


PAYLOAD = bytes((i * 7 + 3) % 256 for i in range(4000))
_CD = {
    "Content-Disposition": 'attachment; filename="mod.zip"',
    "Content-Type": "application/zip",
}


class FakeResp:
    def __init__(self, body, status, headers, chunk=16, on_bytes=None, offset=0):
        self._body = body
        self.status_code = status
        self.headers = headers
        self._chunk = chunk
        self.closed = False
        self._on_bytes = on_bytes
        self._offset = offset  # absolute position of body[0] in the payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), self._chunk):
            chunk = self._body[i:i + self._chunk]
            yield chunk
            # Report the absolute byte position AFTER the chunk was delivered.
            # Tests use this to pause/cancel deterministically mid-stream: the
            # download loop's progress callback is throttled to ~3/s, so a
            # callback-based trigger never fires on an instant fake stream.
            if self._on_bytes:
                self._on_bytes(self._offset + i + len(chunk))

    def close(self):
        self.closed = True


class FakeSession:
    """Serves PAYLOAD, honouring (or ignoring) Range requests on demand."""

    def __init__(self, payload=PAYLOAD, support_range=True, on_bytes=None):
        self.payload = payload
        self.support_range = support_range
        self.range_starts = []
        self.calls = 0
        self.on_bytes = on_bytes

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None):
        self.calls += 1
        headers = headers or {}
        rng = headers.get("Range")
        if rng and self.support_range:
            start = int(rng.split("=", 1)[1].split("-", 1)[0])
            self.range_starts.append(start)
            body = self.payload[start:]
            return FakeResp(body, 206, {**_CD, "Content-Length": str(len(body))},
                            on_bytes=self.on_bytes, offset=start)
        return FakeResp(self.payload, 200, {**_CD, "Content-Length": str(len(self.payload))},
                        on_bytes=self.on_bytes)


class AutoResume(threading.Event):
    """A pause flag that resumes itself the moment the download waits on it,
    so tests stay single-threaded and deterministic."""

    def __init__(self):
        super().__init__()
        self.set()          # start un-paused
        self.resume_count = 0

    def wait(self, timeout=None):
        self.resume_count += 1
        self.set()
        return True


def _client(session):
    c = DeadlyStreamClient()
    c._session = session
    return c


def test_plain_download_writes_whole_file(tmp_path):
    c = _client(FakeSession())
    out = c._download_from_url("http://x/dl", tmp_path, "1")
    assert out.read_bytes() == PAYLOAD
    # No leftover .part file once finished.
    assert not (tmp_path / "mod.zip.part").exists()


def test_pause_then_resume_continues_via_range(tmp_path):
    ev = AutoResume()
    state = {"paused": False}

    def on_bytes(downloaded):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()      # pause once, mid-stream

    sess = FakeSession(on_bytes=on_bytes)
    c = _client(sess)

    out = c._download_from_url("http://x/dl", tmp_path, "1", pause_event=ev)

    assert out.read_bytes() == PAYLOAD          # nothing dropped or duplicated
    assert ev.resume_count >= 1                 # we really paused and resumed
    assert sess.range_starts                    # resumed with a range request
    assert sess.range_starts[0] >= 1500         # continued from where it stopped


def test_cancel_removes_partial_file(tmp_path):
    cancel = threading.Event()

    def on_bytes(downloaded):
        if downloaded >= 1000:
            cancel.set()

    c = _client(FakeSession(on_bytes=on_bytes))

    with pytest.raises(DownloadError):
        c._download_from_url("http://x/dl", tmp_path, "1", cancel_event=cancel)

    assert not (tmp_path / "mod.zip").exists()
    assert not (tmp_path / "mod.zip.part").exists()


def test_resume_restarts_when_server_ignores_range(tmp_path):
    # Some servers send the whole file again (HTTP 200) instead of a 206 range.
    # The download must restart cleanly rather than appending a second copy.
    ev = AutoResume()
    state = {"paused": False}

    def on_bytes(downloaded):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()

    sess = FakeSession(support_range=False, on_bytes=on_bytes)
    c = _client(sess)

    out = c._download_from_url("http://x/dl", tmp_path, "1", pause_event=ev)

    assert out.read_bytes() == PAYLOAD          # exactly one copy, intact
    assert sess.calls >= 2                       # initial + resume attempt


def test_pause_keeps_partial_until_resumed(tmp_path):
    # While paused, the bytes downloaded so far must be safe on disk (a .part),
    # so a resume can pick them up.
    seen = {}

    class Pause(threading.Event):
        def __init__(self):
            super().__init__()
            self.set()

        def wait(self, timeout=None):
            # First time we're asked to wait (i.e. paused), record the partial
            # file size, then resume.
            if "part_size" not in seen:
                part = tmp_path / "mod.zip.part"
                seen["part_size"] = part.stat().st_size if part.exists() else -1
            self.set()
            return True

    ev = Pause()
    state = {"paused": False}

    def on_bytes(downloaded):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()

    sess = FakeSession(on_bytes=on_bytes)
    c = _client(sess)

    out = c._download_from_url("http://x/dl", tmp_path, "1", pause_event=ev)

    assert out.read_bytes() == PAYLOAD
    assert seen.get("part_size", 0) >= 1500     # partial really was on disk
