"""The build list must include mods hosted away from DeadlyStream.

Only DeadlyStream anchors used to be matched, so roughly a quarter of the
KOTOR 1 Spoiler-Free build never appeared: every area texture pack, Ultimate
Character Overhaul, and the duplicate-texture cleanup the guide calls critical.
The app showed 149 of the guide's 191 entries with nothing to say the rest
existed.
"""

from bs4 import BeautifulSoup

from scraper.build_scraper import (AUTO_HOSTS, _scrape_other_hosts, host_of)

PAGE = """
<main>
  <h2>Mod List</h2>
  <p><strong>Name:</strong> <a href="https://deadlystream.com/files/file/1258-k1cp/">K1CP</a></p>
  <p><strong>Installation Method:</strong> HoloPatcher Mod</p>
  <div class="callout note">Installation Instructions Run the installer.</div>

  <p><strong>Name:</strong> <a href="https://www.nexusmods.com/kotor/mods/1360">Ultimate Taris</a></p>
  <p><strong>Installation Method:</strong> Loose-File Mod</p>
  <div class="callout note">Installation Instructions Download the .tpc variant.</div>

  <p><strong>Name:</strong> <a href="https://mega.nz/file/abc#key">Senni Vek</a></p>

  <!-- The guide writes a mod plus its patch as one entry with two links, and
       the entry's name is the whole line: "... High Resolution and Patch". -->
  <p><strong>Name:</strong> <a href="https://www.nexusmods.com/kotor/mods/1367">Ultimate Korriban High Resolution</a> and <a href="https://mega.nz/file/xyz#key2">Patch</a></p>
</main>
"""


def _soup():
    return BeautifulSoup(PAGE, "lxml").find("main")


def test_blocks_without_a_deadlystream_link_are_still_returned():
    # guide position 1 is the DeadlyStream entry, already emitted elsewhere.
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree", claimed={1})
    assert [m.guide_index for m in out] == [2, 3, 4]
    assert [m.name for m in out] == [
        "Ultimate Taris", "Senni Vek",
        "Ultimate Korriban High Resolution and Patch",
    ]


def test_a_block_already_covered_is_not_duplicated():
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree",
                              claimed={1, 2, 3, 4})
    assert out == []


def test_entries_are_keyed_the_way_the_curated_rules_expect():
    """build_overrides.py keys non-DeadlyStream mods on their page position."""
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree", claimed={1})
    assert [m.file_id for m in out] == ["guide:2", "guide:3", "guide:4"]


def test_the_host_is_recorded_for_each():
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree", claimed={1})
    assert [m.source_host for m in out] == ["nexus", "mega", "nexus"]


def test_a_patch_is_additional_content_not_a_mirror():
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree", claimed={1})
    korriban = out[-1]
    assert korriban.source_host == "nexus"
    assert korriban.patch_urls == ["https://mega.nz/file/xyz#key2"]
    assert korriban.auto_downloadable


def test_instructions_are_captured_for_these_too():
    """These carry the same guide nuance as DeadlyStream mods - 'download the
    .tpc variant' decides which of six files to fetch."""
    out = _scrape_other_hosts(_soup(), "KOTOR1", "k1_spoilerfree", claimed={1})
    taris = out[0]
    assert "tpc" in taris.instructions.lower()
    assert taris.install_method == "Loose-File Mod"


def test_auto_hosts_are_the_ones_with_a_downloader():
    for h in ("deadlystream", "nexus", "mega", "github", "googledrive", "direct"):
        assert h in AUTO_HOSTS


def test_a_bare_archive_url_counts_as_directly_downloadable():
    assert host_of("https://www.darthparametric.com/files/kotor/k1/x.7z") == "direct"
    assert host_of("https://ntcore.com/?page_id=371") == "ntcore"


def test_an_explicit_mirror_still_wins_over_nexus():
    soup = BeautifulSoup(PAGE.replace('>Patch</a>', '>Mirror</a>'), "lxml").find("main")
    mod = _scrape_other_hosts(soup, "KOTOR1", "k1_full", {1})[-1]
    assert mod.source_host == "mega" and mod.patch_urls == []


def test_hosts_are_identified_by_hostname_not_query_text():
    assert host_of("https://example.com/?url=https://mega.nz/file/abc") == "unknown"
    assert host_of("https://notgithub.com/a/b") == "unknown"
    assert host_of("https://www.dropbox.com/s/abc/patch.zip?dl=0") == "dropbox"


def test_real_guide_wrapper_preserves_offsite_fields():
    soup = BeautifulSoup('<main><div class="mod">' + PAGE.split('<main>')[1].split('</main>')[0]
                         + '</div></main>', "lxml").find("main")
    mod = _scrape_other_hosts(soup, "KOTOR1", "k1_full", {1})[0]
    assert mod.install_method == "Loose-File Mod"
    assert mod.instructions == "Installation Instructions Download the .tpc variant."


def test_scrape_keeps_external_patch_for_a_deadlystream_main(monkeypatch):
    from scraper.build_scraper import scrape_build
    from tests.test_hosts import FakeResp
    import requests
    html = '''<main><p><strong>Name:</strong>
        <a href="https://deadlystream.com/files/file/349-character-startup/">Character Startup</a>
        and <a href="https://mega.nz/file/abc#key">Patch</a></p></main>'''
    response = FakeResp(text=html)
    response.encoding = "utf-8"
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: response)
    mods = scrape_build("k1_full")
    assert len(mods) == 1
    assert mods[0].file_id == "349"
    assert mods[0].patch_urls == ["https://mega.nz/file/abc#key"]
