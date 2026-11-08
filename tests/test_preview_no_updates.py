"""The OAuth preview shared with Nexus Mods must never update itself.

A tester has to stay on the exact build they were given: newer regular releases
do not have the preview's sign-in, so the preview neither checks for, announces
nor installs updates.
"""

import urllib.request

import pytest

from backend import server


def test_update_check_never_goes_online(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("the preview must not check for updates"))
    info = server.update_check()
    assert info["available"] is False
    assert info["updates_disabled"] is True
    assert info["can_self_update"] is False


def test_update_download_is_refused():
    resp = server.update_download()
    assert resp.status_code == 403


def test_self_update_is_off_even_without_the_nexus_marker(monkeypatch):
    monkeypatch.delenv("KMI_NO_SELF_UPDATE", raising=False)
    assert server._self_update_allowed() is False
