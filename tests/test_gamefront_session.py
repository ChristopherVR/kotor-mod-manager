"""Browser jobs must be serial, replayable, cancellable and correctly scoped."""
import threading
import time
import zipfile

from tests.test_pipeline_fixes import _mod, _pipeline


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for browser job")


def archive(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mod.tga", "texture")


def test_browser_jobs_are_serial_and_never_consume_root_files(tmp_path, monkeypatch):
    import installer.pipeline as module
    monkeypatch.setattr(module, "_DROP_POLL_SECONDS", .01)
    mods = [_mod(file_id=str(i), slug=f"mod-{i}", source_host="gamefront",
                 url=f"https://www.gamefront.com/games/k/file/mod-{i}") for i in (1, 2)]
    p = _pipeline(tmp_path, mods, gamefront_browser=True)
    outputs = {}
    def run(i):
        outputs[i] = p._await_dropped_file(p.mods[i], p._mod_dir(p.mods[i]), "")
    first = threading.Thread(target=run, args=(0,))
    second = threading.Thread(target=run, args=(1,))
    first.start()
    wait_for(lambda: p.gamefront_request is not None)
    request = dict(p.gamefront_request)
    second.start()
    # An unrelated archive and an incomplete native download must be ignored.
    archive(tmp_path / "unrelated.zip")
    dest = p._mod_dir(p.mods[0])
    staging = dest / ".gamefront-part"
    staging.mkdir()
    archive(staging / "mod.zip")
    time.sleep(.05)
    assert p.gamefront_request == request
    assert not outputs
    archive(dest / "first.zip")
    wait_for(lambda: 0 in outputs)
    wait_for(lambda: p.gamefront_request and p.gamefront_request["id"] != request["id"])
    assert p.gamefront_request["url"] == mods[1].url
    archive(p._mod_dir(p.mods[1]) / "second.zip")
    first.join(2)
    second.join(2)
    assert [v[0].name for _, v in sorted(outputs.items())] == ["first.zip", "second.zip"]
    assert p.gamefront_request is None


def test_stop_clears_request_and_cancels_queued_browser_job(tmp_path, monkeypatch):
    import installer.pipeline as module
    monkeypatch.setattr(module, "_DROP_POLL_SECONDS", .01)
    mods = [_mod(file_id=str(i), source_host="gamefront") for i in (1, 2)]
    p = _pipeline(tmp_path, mods, gamefront_browser=True)
    outputs = []
    def run(pm):
        outputs.append(p._await_dropped_file(pm, p._mod_dir(pm), ""))
    workers = [threading.Thread(target=run, args=(pm,)) for pm in p.mods]
    for worker in workers:
        worker.start()
    wait_for(lambda: p.gamefront_request is not None)
    p.stop()
    for worker in workers:
        worker.join(2)
    assert outputs == [None, None]
    assert p.gamefront_request is None


def test_browser_job_accepts_a_regular_browser_download_when_the_window_fails(tmp_path, monkeypatch):
    """If the built-in GameFront window cannot load (issue #114), the player can
    save the archive with their normal browser into Downloads and still finish."""
    import installer.pipeline as module
    monkeypatch.setattr(module, "_DROP_POLL_SECONDS", .01)
    monkeypatch.setattr(module, "_DROP_SETTLE_SECONDS", 0)
    mod = _mod(source_host="gamefront", url="https://www.gamefront.com/games/k/file/test-mod")
    p = _pipeline(tmp_path, [mod], gamefront_browser=True)
    outputs = []
    worker = threading.Thread(target=lambda: outputs.append(
        p._await_dropped_file(p.mods[0], p._mod_dir(p.mods[0]), "")))
    worker.start()
    wait_for(lambda: p.gamefront_request is not None)
    downloads = tmp_path / "dl"
    downloads.mkdir(exist_ok=True)
    # Someone else's archive must never be taken for this mod.
    archive(downloads / "unrelated.zip")
    time.sleep(.05)
    assert not outputs
    archive(downloads / "Test_Mod_v1.zip")
    worker.join(3)
    assert outputs and outputs[0][0].name == "Test_Mod_v1.zip"
    assert outputs[0][0].parent == p._mod_dir(p.mods[0])
    assert (downloads / "unrelated.zip").exists()
    assert p.gamefront_request is None
