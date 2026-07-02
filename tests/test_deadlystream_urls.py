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
