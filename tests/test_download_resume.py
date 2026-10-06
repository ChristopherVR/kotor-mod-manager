"""Downloads carry on from a partial file left by an earlier run (the app was
closed, or the connection dropped), instead of starting again from zero."""
import io
import urllib.error

import pytest

from scraper import hosts, nexus
from scraper.deadlystream import DownloadError
from tests.test_download_pause_resume import PAYLOAD, FakeResp, FakeSession, _CD, _client


# ---------------------------------------------------------------- DeadlyStream

def test_a_partial_from_an_earlier_run_is_continued(tmp_path):
    (tmp_path / "mod.zip.part").write_bytes(PAYLOAD[:1500])
    sess = FakeSession()
    out = _client(sess)._download_from_url("http://x/dl", tmp_path, "1")
    assert out.read_bytes() == PAYLOAD                  # nothing dropped or repeated
    assert sess.range_starts == [1500]                  # only the rest was asked for
    assert not (tmp_path / "mod.zip.part").exists()


def test_a_server_that_ignores_the_range_gets_a_clean_restart(tmp_path):
    (tmp_path / "mod.zip.part").write_bytes(PAYLOAD[:1500])
    out = _client(FakeSession(support_range=False))._download_from_url("http://x/dl", tmp_path, "1")
    assert out.read_bytes() == PAYLOAD                  # not the old bytes plus a whole copy


class _CutShort(FakeSession):
    """The first request delivers only part of the body, then the connection drops."""

    def __init__(self, cut_at):
        super().__init__()
        self.cut_at = cut_at
        self.first = True

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None):
        if self.first and not (headers or {}).get("Range"):
            self.first = False
            return FakeResp(self.payload[:self.cut_at], 200,
                            {**_CD, "Content-Length": str(len(self.payload))})
        return super().get(url, stream, timeout, allow_redirects, headers)


def test_a_dropped_connection_is_not_taken_for_a_finished_download(tmp_path):
    with pytest.raises(DownloadError, match="cut short"):
        _client(_CutShort(2500))._download_from_url("http://x/dl", tmp_path, "1")
    assert not (tmp_path / "mod.zip").exists()
    assert (tmp_path / "mod.zip.part").read_bytes() == PAYLOAD[:2500]   # kept
    out = _client(FakeSession())._download_from_url("http://x/dl", tmp_path, "1")
    assert out.read_bytes() == PAYLOAD


# ---------------------------------------------------------------------- Nexus

class _Resp:
    def __init__(self, body, status=200, total=None):
        self._b, self._status = io.BytesIO(body), status
        self.headers = {"Content-Length": str(len(body))}

    def getcode(self):
        return self._status

    def read(self, n):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture
def nexus_server(monkeypatch):
    """A Nexus CDN holding DATA, with switches for how it treats Range requests."""
    DATA = bytes(range(256)) * 40
    state = {"ranges": [], "mode": "range", "cut": None}
    monkeypatch.setattr(nexus, "file_info", lambda *a, **k: {"file_name": "big.zip"})
    monkeypatch.setattr(nexus, "download_link", lambda *a, **k: "https://cdn/big file.zip")

    def urlopen(req, timeout=0):
        rng = req.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            state["ranges"].append(start)
            if state["mode"] == "416":
                raise urllib.error.HTTPError(req.full_url, 416, "Range", {}, io.BytesIO())
            if state["mode"] == "range":
                return _Resp(DATA[start:], 206)
        body = DATA if state["cut"] is None else DATA[:state["cut"]]
        r = _Resp(body, 200)
        r.headers["Content-Length"] = str(len(DATA))        # promised the whole file
        return r

    monkeypatch.setattr(nexus.urllib.request, "urlopen", urlopen)
    return DATA, state


def test_nexus_continues_a_partial_file(tmp_path, nexus_server):
    DATA, state = nexus_server
    (tmp_path / "big.zip.part").write_bytes(DATA[:3000])
    out = nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY")
    assert out.read_bytes() == DATA
    assert state["ranges"] == [3000]


def test_nexus_restarts_cleanly_when_the_range_is_ignored(tmp_path, nexus_server):
    DATA, state = nexus_server
    state["mode"] = "ignore"
    (tmp_path / "big.zip.part").write_bytes(DATA[:3000])
    assert nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY").read_bytes() == DATA


def test_nexus_restarts_when_the_range_is_refused(tmp_path, nexus_server):
    DATA, state = nexus_server
    state["mode"] = "416"
    (tmp_path / "big.zip.part").write_bytes(b"junk that is not a prefix")
    assert nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY").read_bytes() == DATA


def test_nexus_keeps_the_partial_of_a_cut_off_download_and_finishes_it_later(tmp_path, nexus_server):
    DATA, state = nexus_server
    state["cut"] = 4000
    with pytest.raises(nexus.NexusDownloadError, match="cut short"):
        nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY")
    assert not (tmp_path / "big.zip").exists()
    assert (tmp_path / "big.zip.part").read_bytes() == DATA[:4000]
    state["cut"] = None
    assert nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY").read_bytes() == DATA


def test_nexus_cancel_keeps_the_partial(tmp_path, nexus_server):
    import threading
    DATA, state = nexus_server
    stop = threading.Event()
    stop.set()
    with pytest.raises(nexus.NexusDownloadError, match="cancelled"):
        nexus.download_file("KOTOR1", 1, 2, tmp_path, "KEY", cancel_event=stop)


# ------------------------------------------------------------- direct / GitHub

class _HostResp:
    def __init__(self, body, status, total):
        self._b, self.status_code = body, status
        self.url = "https://x/big.zip"
        self.headers = {"Content-Type": "application/zip", "Content-Length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        for i in range(0, len(self._b), n):
            yield self._b[i:i + n]

    def close(self):
        pass


def test_a_direct_download_continues_a_partial_file(tmp_path, monkeypatch):
    DATA = bytes(range(256)) * 20
    seen = []

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None):
        rng = (headers or {}).get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            seen.append(start)
            return _HostResp(DATA[start:], 206, len(DATA))
        return _HostResp(DATA, 200, len(DATA))

    monkeypatch.setattr(hosts.requests.Session, "get", get)
    (tmp_path / "big.zip.part").write_bytes(DATA[:2000])
    out = hosts.download_direct("https://x/big.zip", tmp_path)
    assert out.read_bytes() == DATA and seen == [2000]


def test_a_cut_off_direct_download_is_not_accepted_and_keeps_its_partial(tmp_path, monkeypatch):
    DATA = bytes(range(256)) * 20

    def get(self, url, stream=False, timeout=None, allow_redirects=True, headers=None):
        r = _HostResp(DATA[:1000], 200, len(DATA))
        r.headers["Content-Length"] = str(len(DATA))
        return r

    monkeypatch.setattr(hosts.requests.Session, "get", get)
    with pytest.raises(hosts.HostDownloadError, match="cut short"):
        hosts.download_direct("https://x/big.zip", tmp_path)
    assert not (tmp_path / "big.zip").exists()
    assert (tmp_path / "big.zip.part").read_bytes() == DATA[:1000]
