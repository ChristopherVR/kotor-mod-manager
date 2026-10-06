"""
URL-shape tests for the DeadlyStream client - confirms the slug is threaded
into every download/CSRF URL and that the HTML-interstitial guard fires.
No network: the session is monkeypatched.

Run:  python -m pytest tests/test_deadlystream_urls.py -q
   or: python tests/test_deadlystream_urls.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.deadlystream import DeadlyStreamClient, DownloadError


class FakeResp:
    def __init__(self, text="", headers=None, content=b"", status=200):
        self.text = text
        self.headers = headers or {}
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield self._content

    def close(self):
        pass


def _client_with_capture(get_handler):
    c = DeadlyStreamClient()
    calls = []

    def fake_get(url, **kw):
        calls.append({"url": url, "headers": kw.get("headers", {})})
        return get_handler(url, kw)

    c._session.get = fake_get  # type: ignore
    return c, calls


def test_csrf_url_includes_slug():
    c, calls = _client_with_capture(
        lambda url, kw: FakeResp(text='var x = {"csrfKey":"deadbeef"};')
    )
    csrf = c._get_csrf_for_file("1313", "kotor-dialogue-fixes")
    assert csrf == "deadbeef"
    assert calls[-1]["url"] == "https://deadlystream.com/files/file/1313-kotor-dialogue-fixes/"
    assert "/files/file/1313/" not in calls[-1]["url"]
    print("PASS: CSRF URL includes slug")


def test_single_file_download_url_and_referer(tmp_dir=None):
    import tempfile
    dest = Path(tempfile.mkdtemp())

    def handler(url, kw):
        if url.endswith("/") and "do=download" not in url:
            return FakeResp(text='{"csrfKey":"abc123"}')
        # download GET
        return FakeResp(
            headers={"Content-Disposition": 'filename="mod.zip"',
                     "Content-Type": "application/zip", "Content-Length": "4"},
            content=b"data",
        )

    c, calls = _client_with_capture(handler)
    c.download_file("1313", dest, slug="kotor-dialogue-fixes")
    dl = [x for x in calls if "do=download" in x["url"]][-1]
    assert dl["url"] == (
        "https://deadlystream.com/files/file/1313-kotor-dialogue-fixes/"
        "?do=download&csrfKey=abc123"
    )
    assert dl["headers"].get("Referer") == \
        "https://deadlystream.com/files/file/1313-kotor-dialogue-fixes/"
    print("PASS: single-file download URL is slugged + carries Referer")


def test_multifile_records_slugged():
    page = (
        "https://deadlystream.com/files/file/2000-multi/"
    )
    html = (
        '<a href="/files/file/2000-multi/?do=download&r=11">Part 1</a>'
        '<a href="/files/file/2000-multi/?do=download&r=12">Part 2</a>'
    )

    def handler(url, kw):
        if "do=download" in url:
            return FakeResp(text=html)
        return FakeResp(text='{"csrfKey":"abcd12"}')

    c, calls = _client_with_capture(handler)
    recs = c.list_download_records("2000", "multi")
    assert len(recs) == 2, recs
    assert {r["record_id"] for r in recs} == {"11", "12"}
    for r in recs:
        assert r["url"].startswith("https://deadlystream.com/files/file/2000-multi/")
        assert "csrfKey=abcd12" in r["url"]
    # the listing page itself was requested slugged
    listing = [x for x in calls if x["url"].endswith("?do=download")][0]
    assert listing["url"] == page + "?do=download"
    print("PASS: multi-file records are slugged with csrf")


def test_html_interstitial_guard():
    import tempfile
    dest = Path(tempfile.mkdtemp())

    def handler(url, kw):
        return FakeResp(text="<html>login</html>", headers={"Content-Type": "text/html"})

    c, _ = _client_with_capture(handler)
    try:
        c._download_from_url("https://x/y?do=download", dest, "1", referer="https://x/")
    except DownloadError as e:
        assert "HTML" in str(e)
        assert not any(dest.iterdir()), "no file should be written on HTML response"
        print("PASS: HTML interstitial raises and writes no file")
        return
    raise AssertionError("expected DownloadError on HTML response")


def test_percent_encoded_filename_is_decoded():
    # DeadlyStream sends percent-encoded names in Content-Disposition. The saved
    # file (and the folder it extracts into) must use the decoded human name,
    # otherwise TSLPatcher mods break on the garbled tslpatchdata path.
    import tempfile
    from scraper.deadlystream import _parse_content_disposition

    # plain quoted form with percent-encoding
    assert _parse_content_disposition(
        'filename="JC%27s%20Jedi%20Tailor%20for%20K1%20v1.4.zip"'
    ) == "JC's Jedi Tailor for K1 v1.4.zip"
    # RFC 5987 extended form
    assert _parse_content_disposition(
        "attachment; filename*=UTF-8''JC%27s%20Jedi%20Tailor.zip"
    ) == "JC's Jedi Tailor.zip"
    # already-clean names pass through unchanged
    assert _parse_content_disposition('filename="normal name.7z"') == "normal name.7z"
    assert _parse_content_disposition("") == ""

    dest = Path(tempfile.mkdtemp())

    def handler(url, kw):
        if url.endswith("/") and "do=download" not in url:
            return FakeResp(text='{"csrfKey":"abc123"}')
        return FakeResp(
            headers={
                "Content-Disposition":
                    'filename="Effixian%27s%20Qel-Droma%20Robes.zip"',
                "Content-Type": "application/zip", "Content-Length": "4",
            },
            content=b"data",
        )

    c, _ = _client_with_capture(handler)
    out = c.download_file("2019", dest, slug="effixians-qel-droma")
    assert out is not None
    assert out.name == "Effixian's Qel-Droma Robes.zip", out.name
    print("PASS: percent-encoded download filename is decoded on disk")


def test_backcompat_no_slug_callable():
    # download_all_files(file_id, dest) without slug must still be callable.
    import inspect
    sig = inspect.signature(DeadlyStreamClient.download_all_files)
    assert sig.parameters["slug"].default == ""
    print("PASS: download_all_files is back-compatible (slug defaults to '')")


def test_record_listing_ignores_file_response():
    # If the ?do=download URL serves the archive itself (single-file
    # submission), the record lister must not read the body into memory -
    # it should fall back to the primary download record.
    def handler(url, kw):
        if "do=download" in url:
            return FakeResp(
                headers={"Content-Type": "application/zip",
                         "Content-Length": "99999999"},
                content=b"ZIPDATA",
            )
        return FakeResp(text='{"csrfKey":"abcd12"}')

    c, calls = _client_with_capture(handler)
    recs = c.list_download_records("2000", "multi")
    assert len(recs) == 1
    assert recs[0]["record_id"] is None
    listing = [x for x in calls if "do=download" in x["url"]][0]
    assert listing.get("headers") is not None
    print("PASS: record listing falls back when served a file")


def test_other_language_records_skipped():
    # In a multi-file submission, translation patches for other languages
    # are skipped for an English game; the main file still downloads.
    import tempfile
    dest = Path(tempfile.mkdtemp())
    served = ["Main_Mod.zip", "Patch_Deutsche_Ubersetzung.zip"]

    def handler(url, kw):
        if "do=download" in url:
            name = served[0] if "r=11" in url else served[1]
            return FakeResp(
                headers={"Content-Disposition": f'filename="{name}"',
                         "Content-Type": "application/zip",
                         "Content-Length": "4"},
                content=b"data",
            )
        return FakeResp(text='{"csrfKey":"abc123"}')

    c, _ = _client_with_capture(handler)
    c.list_download_records = lambda fid, slug="": [
        {"name": "Main", "url": "https://x/?do=download&r=11", "record_id": "11"},
        {"name": "German", "url": "https://x/?do=download&r=12", "record_id": "12"},
    ]
    paths = c.download_all_files("2000", dest, slug="multi", language="en")
    assert [p.name for p in paths] == ["Main_Mod.zip"], paths
    print("PASS: other-language records are skipped for an English game")


if __name__ == "__main__":
    test_csrf_url_includes_slug()
    test_single_file_download_url_and_referer()
    test_multifile_records_slugged()
    test_html_interstitial_guard()
    test_percent_encoded_filename_is_decoded()
    test_backcompat_no_slug_callable()
    test_record_listing_ignores_file_response()
    test_other_language_records_skipped()
    print("\nALL DEADLYSTREAM URL TESTS PASSED")


def test_rejected_login_is_not_reported_as_signed_in():
    """A wrong password re-shows the login form. Guests also get session
    cookies, so the client must not take those as proof of a login."""
    import pytest
    from scraper.deadlystream import AuthError, DeadlyStreamClient

    class Resp:
        status_code = 200
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass

    form = '<form><input name="csrfKey" value="abc"><input name="_processLogin"></form>'
    rejected = ('<div class="ipsMessage_error">The display name, email address or '
                'password was incorrect.</div>' + form)
    c = DeadlyStreamClient()
    c._session.get = lambda *a, **k: Resp(form)
    c._session.post = lambda *a, **k: Resp(rejected)
    c._session.cookies.set("ips4_IPSSessionFront", "guest")
    with pytest.raises(AuthError, match="incorrect"):
        c.login("someone", "wrong")
    assert c._logged_in is False


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code}")

    def close(self):
        pass


def _client(statuses, monkeypatch):
    import scraper.deadlystream as ds
    sleeps, clock = [], [0.0]

    def sleep(s):   # a fake clock, so the result doesn't hang on the OS timer
        sleeps.append(s)
        clock[0] += s
    monkeypatch.setattr(ds.time, "sleep", sleep)
    monkeypatch.setattr(ds.time, "monotonic", lambda: clock[0])
    c = ds.DeadlyStreamClient()
    seq = list(statuses)
    c._session.get = lambda url, **kw: _Resp(seq.pop(0) if len(seq) > 1 else seq[0])
    return c, sleeps


def test_a_403_burst_refusal_is_retried_after_a_pause(monkeypatch):
    c, sleeps = _client([403, 403, 200], monkeypatch)
    assert c._get("https://deadlystream.com/x").status_code == 200
    assert [s for s in sleeps if s >= 3] == [5, 15]   # then got through


def test_a_refusal_that_keeps_coming_is_returned_after_the_retries(monkeypatch):
    c, sleeps = _client([403], monkeypatch)
    assert c._get("https://deadlystream.com/x").status_code == 403
    assert [s for s in sleeps if s >= 3] == [5, 15, 30]


def test_retry_after_from_the_site_is_honoured(monkeypatch):
    import scraper.deadlystream as ds
    sleeps = []
    monkeypatch.setattr(ds.time, "sleep", sleeps.append)
    c = ds.DeadlyStreamClient()
    seq = [_Resp(429, {"Retry-After": "12"}), _Resp(200)]
    c._session.get = lambda url, **kw: seq.pop(0)
    assert c._get("https://deadlystream.com/x").status_code == 200
    assert 12 in sleeps


def test_requests_are_spaced_out_across_threads(monkeypatch):
    import threading
    import scraper.deadlystream as ds
    monkeypatch.setattr(ds, "_MIN_REQUEST_GAP", 0.1)
    c = ds.DeadlyStreamClient()
    starts = []
    c._session.get = lambda url, **kw: (starts.append(ds.time.monotonic()), _Resp(200))[1]
    ts = [threading.Thread(target=c._get, args=("https://deadlystream.com/x",)) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    starts.sort()
    assert all(b - a >= 0.08 for a, b in zip(starts, starts[1:]))


def test_one_downloads_refusal_pauses_every_other_request(monkeypatch):
    """While one download waits out a 403, the others must not keep sending
    requests, or the refusal just goes on longer."""
    import threading
    import scraper.deadlystream as ds
    monkeypatch.setattr(ds, "_RETRY_DELAYS", (0.4,))
    monkeypatch.setattr(ds, "_MIN_REQUEST_GAP", 0.0)
    c = ds.DeadlyStreamClient()
    times = {}
    seq = [_Resp(403), _Resp(200)]

    def get(url, **kw):
        times.setdefault(url, []).append(ds.time.monotonic())
        return seq.pop(0) if url.endswith("/first") else _Resp(200)

    c._session.get = get
    t0 = ds.time.monotonic()
    a = threading.Thread(target=c._get, args=("https://deadlystream.com/first",))
    a.start()
    ds.time.sleep(0.1)                      # the first request has been refused by now
    b = threading.Thread(target=c._get, args=("https://deadlystream.com/second",))
    b.start()
    a.join(); b.join()
    assert times["https://deadlystream.com/second"][0] - t0 >= 0.35
