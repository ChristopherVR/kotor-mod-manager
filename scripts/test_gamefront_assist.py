"""Interactive, download-only smoke test of the real GameFront pipeline.

Run from the repository root:
    python scripts/test_gamefront_assist.py

The browser opens Vurt's Ebon Hawk page. Save the archive in the printed folder.
The manager detects it, files it under the mod, and writes result.json. The test
never starts installation, reads saved credentials, or changes game settings.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer import pipeline
from scraper.build_scraper import BuildMod
from scraper.deadlystream import DeadlyStreamClient


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    root = args.download_dir or (Path.home() / "Downloads" / "KOTOR_Browser_Assist_Test"
                                / datetime.now().strftime("%Y%m%d-%H%M%S"))
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = {"status": "starting", "download_dir": str(root), "download_only": True}

    def save(**changes):
        result.update(changes)
        temp = root / "result.json.tmp"
        temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        temp.replace(root / "result.json")

    def log(message, level="info"):
        print(message, flush=True)
        with (root / "test.log").open("a", encoding="utf-8") as stream:
            stream.write(f"[{level}] {message}\n")

    def status(file_id, state, detail):
        save(status=state.name.lower(), detail=detail)

    mod = BuildMod(
        install_order=1, file_id="guide:86", slug="vurt-s-k1-hi-res-ebon-hawk-retexture",
        name="Vurt's K1 Hi-Res Ebon Hawk Retexture",
        url="https://www.gamefront.com/games/knights-of-the-old-republic/file/vurt-s-k1-hi-res-ebon-hawk-retexture",
        game="KOTOR1", section="", category="", note="", option_hint="",
        install_method_hint="loose", build_key="k1_full", source_host="gamefront",
    )
    pipeline._DROP_WAIT_SECONDS = max(1, args.timeout)
    runner = pipeline.Pipeline(
        [mod], game_path=root / "unused-game", download_dir=root,
        client=DeadlyStreamClient(), record_to_library=False,
        on_log=log, on_status=status,
        # Marks this as interactive so the production browser-assist path opens
        # the source page. This mod does not ask any installer questions.
        on_confirm=lambda *unused: None,
    )
    save(url=mod.url, mod=mod.name)
    log(f"Save the GameFront archive in: {root}")
    log(f"Waiting up to {args.timeout} seconds. No game files will be installed.")
    pm = runner.mods[0]
    try:
        # Exercise the actual download stage only, never Pipeline.start().
        runner._download_mod(pm)
        if not pm.archive_paths or pm.status == pipeline.ModStatus.ERROR:
            save(status="failed", error=pm.error or "No archive received.")
            return 1
        entries = 0
        for path in pm.archive_paths:
            if path.suffix.lower() == ".rar":
                import rarfile
                with rarfile.RarFile(path) as archive:
                    entries += len(archive.infolist())
            elif path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    entries += len(archive.infolist())
            elif path.suffix.lower() == ".7z":
                import py7zr
                with py7zr.SevenZipFile(path) as archive:
                    entries += len(archive.list())
        if not entries:
            raise ValueError("The received archive has no readable entries.")
        save(status="passed", detail="Browser download received and archive directory parsed.",
             files=[str(path) for path in pm.archive_paths], archive_entries=entries,
             bytes=sum(path.stat().st_size for path in pm.archive_paths))
        log("PASS: manager received the archive and its directory is readable. Nothing installed.")
        return 0
    except KeyboardInterrupt:
        runner.stop()
        save(status="cancelled")
        return 130
    except Exception as exc:
        save(status="failed", error=str(exc))
        log(f"FAIL: {exc}", "error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
