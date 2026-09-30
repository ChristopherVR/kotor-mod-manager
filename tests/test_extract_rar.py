"""RAR extraction on Linux: Debian/Ubuntu's 7-Zip lists RAR files but cannot
decompress them ("Unsupported Method"), so unar and bsdtar must be tried."""
import subprocess

import pytest

from installer import extractor


class _Result:
    def __init__(self, code):
        self.returncode = code


def _setup(monkeypatch, tools, works):
    """tools: executables 'installed'. works: the one that succeeds (or None)."""
    calls = []
    monkeypatch.setattr(extractor, "_find_7z", lambda: "7z" if "7z" in tools else None)
    monkeypatch.setattr(extractor, "_find_unrar", lambda: None)
    monkeypatch.setattr(extractor.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in tools else None)
    monkeypatch.setattr(extractor, "HAS_RAR", False)
    monkeypatch.setattr(extractor, "HAS_7Z", False)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        name = str(cmd[0]).split("/")[-1]
        return _Result(0 if name == works else 2)

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    return calls


def test_unar_is_used_when_7z_cannot_read_rar(tmp_path, monkeypatch):
    calls = _setup(monkeypatch, {"7z", "unar", "bsdtar"}, works="unar")
    extractor._extract_rar(tmp_path / "m.rar", tmp_path / "out")
    names = [str(c[0]).split("/")[-1] for c in calls]
    assert names == ["7z", "unar"]
    assert str(tmp_path / "out") in calls[-1]


def test_bsdtar_is_the_next_fallback(tmp_path, monkeypatch):
    calls = _setup(monkeypatch, {"7z", "bsdtar"}, works="bsdtar")
    extractor._extract_rar(tmp_path / "m.rar", tmp_path / "out")
    assert [str(c[0]).split("/")[-1] for c in calls] == ["7z", "bsdtar"]
    assert calls[-1][:2] == ["/usr/bin/bsdtar", "-xf"]


def test_error_lists_every_tool_that_would_work(tmp_path, monkeypatch):
    _setup(monkeypatch, {"7z"}, works=None)
    monkeypatch.setattr(extractor.sys, "platform", "linux")
    with pytest.raises(extractor.ExtractionError) as e:
        extractor._extract_rar(tmp_path / "m.rar", tmp_path / "out")
    msg = str(e.value)
    assert "Please install one of the following tools:" in msg
    for tool in ("unar", "unrar", "bsdtar", "7-Zip"):
        assert tool in msg
