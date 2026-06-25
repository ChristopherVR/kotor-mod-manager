"""The installer should recognise a real KOTOR folder and reject the wrong one."""
from installer.game_validate import is_kotor_install


def test_rejects_empty_or_missing(tmp_path):
    assert not is_kotor_install(None)
    assert not is_kotor_install("")
    assert not is_kotor_install(tmp_path / "does-not-exist")
    # An empty "New folder" - the exact mistake that used to fail deep in the patcher.
    assert not is_kotor_install(tmp_path)


def test_accepts_chitin_key(tmp_path):
    (tmp_path / "chitin.key").write_bytes(b"BIFFV1  ")
    assert is_kotor_install(tmp_path)


def test_accepts_modules_plus_dialog_fallback(tmp_path):
    (tmp_path / "Modules").mkdir()
    (tmp_path / "dialog.tlk").write_bytes(b"TLK ")
    assert is_kotor_install(tmp_path)


def test_modules_alone_is_not_enough(tmp_path):
    (tmp_path / "Modules").mkdir()
    assert not is_kotor_install(tmp_path)
