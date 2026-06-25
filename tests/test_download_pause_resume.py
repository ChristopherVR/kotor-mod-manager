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
    def __init__(self, body, status, headers, chunk=16):
        self._body = body
        self.status_code = status
        self.headers = headers
        self._chunk = chunk
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), self._chunk):
            yield self._body[i:i + self._chunk]

    def close(self):
        self.closed = True


class FakeSession:
    """Serves PAYLOAD, honouring (or ignoring) Range requests on demand."""

    def __init__(self, payload=PAYLOAD, support_range=True):
        self.payload = payload
        self.support_range = support_range
        self.range_starts = []
        self.calls = 0

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None):
        self.calls += 1
        headers = headers or {}
        rng = headers.get("Range")
        if rng and self.support_range:
            start = int(rng.split("=", 1)[1].split("-", 1)[0])
            self.range_starts.append(start)
            body = self.payload[start:]
            return FakeResp(body, 206, {**_CD, "Content-Length": str(len(body))})
        return FakeResp(self.payload, 200, {**_CD, "Content-Length": str(len(self.payload))})


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
    sess = FakeSession()
    c = _client(sess)
    ev = AutoResume()
    state = {"paused": False}

    def cb(downloaded, total, name):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()      # pause once, mid-stream

    out = c._download_from_url("http://x/dl", tmp_path, "1",
                               progress_callback=cb, pause_event=ev)

    assert out.read_bytes() == PAYLOAD          # nothing dropped or duplicated
    assert ev.resume_count >= 1                 # we really paused and resumed
    assert sess.range_starts                    # resumed with a range request
    assert sess.range_starts[0] >= 1500         # continued from where it stopped


def test_cancel_removes_partial_file(tmp_path):
    c = _client(FakeSession())
    cancel = threading.Event()

    def cb(downloaded, total, name):
        if downloaded >= 1000:
            cancel.set()

    with pytest.raises(DownloadError):
        c._download_from_url("http://x/dl", tmp_path, "1",
                             progress_callback=cb, cancel_event=cancel)

    assert not (tmp_path / "mod.zip").exists()
    assert not (tmp_path / "mod.zip.part").exists()


def test_resume_restarts_when_server_ignores_range(tmp_path):
    # Some servers send the whole file again (HTTP 200) instead of a 206 range.
    # The download must restart cleanly rather than appending a second copy.
    sess = FakeSession(support_range=False)
    c = _client(sess)
    ev = AutoResume()
    state = {"paused": False}

    def cb(downloaded, total, name):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()

    out = c._download_from_url("http://x/dl", tmp_path, "1",
                               progress_callback=cb, pause_event=ev)

    assert out.read_bytes() == PAYLOAD          # exactly one copy, intact
    assert sess.calls >= 2                       # initial + resume attempt


def test_pause_keeps_partial_until_resumed(tmp_path):
    # While paused, the bytes downloaded so far must be safe on disk (a .part),
    # so a resume can pick them up.
    sess = FakeSession()
    c = _client(sess)
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

    def cb(downloaded, total, name):
        if not state["paused"] and downloaded >= 1500:
            state["paused"] = True
            ev.clear()

    out = c._download_from_url("http://x/dl", tmp_path, "1",
                               progress_callback=cb, pause_event=ev)

    assert out.read_bytes() == PAYLOAD
    assert seen.get("part_size", 0) >= 1500     # partial really was on disk
