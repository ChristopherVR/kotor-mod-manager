"""Wrap a scanned Windows or Linux release in a standalone-app ZIP for Nexus Mods."""

import argparse
import hashlib
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_nexus(
    tag: str,
    repository: str,
    executable: Path,
    notes: Path,
    scan_report: Path,
    license_file: Path,
    output: Path,
    platform: str = "windows",
) -> Path:
    if platform not in ("windows", "linux"):
        raise ValueError(f"Unsupported platform: {platform}")
    version = tag.removeprefix("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError(f"Invalid release version: {tag}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"Invalid GitHub repository: {repository}")
    for source in (executable, notes, scan_report, license_file):
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"Missing or empty release input: {source}")

    release_url = f"https://github.com/{repository}/releases/tag/{tag}"
    is_linux = platform == "linux"
    label = "Linux x86_64" if is_linux else "Windows"
    executable_name = "KOTOR-Mod-Installer-linux-x86_64" if is_linux else "KOTOR-Mod-Installer.exe"
    suffix = "-linux" if is_linux else ""
    launch = (
        f"Make {executable_name} executable (Properties > Permissions, or\n"
        f"   chmod +x {executable_name}), then run ./{executable_name}."
        if is_linux else f"Run {executable_name} on 64-bit Windows."
    )
    platform_note = (
        "Requires an x86_64 Linux desktop with GTK 3 and WebKitGTK 4.1 runtime\n"
        "libraries. If launch fails, run from a terminal to see missing libraries.\n"
        if is_linux else "Windows may show a SmartScreen warning for an unsigned app.\n"
    )
    readme = f"""KOTOR Mod Installer {version}
=============================

This is a standalone app for KOTOR 1 and KOTOR 2, not a mod to deploy with Vortex.

1. Use Manual download on Nexus and extract this ZIP into its own folder.
   Do not extract it into your game folder or install it through another manager.
2. {launch}
3. In Settings > Game Installs, choose your KOTOR 1 and/or KOTOR 2 folders.
4. Sign in to DeadlyStream under Account. If your build uses Nexus mods,
   add your personal Nexus API key under Settings > Nexus.
5. Choose a build in Mod Builds, load its mod list, then Download & Install.

No Python or Node installation is needed. The app downloads mods from their
original hosts using your accounts. No game files or mod packs are bundled.
Nexus Premium supports automatic downloads; free accounts need a click per mod.
Back up your saves and start with a clean game installation for a new build.
Patcher-based mod changes are not cleanly reversible by switching a mod off.

{platform_note}This ZIP includes
the release antivirus report and SHA-256 checksums. Report antivirus detections
rather than disabling protection. The report is not a guarantee of safety.

The app can check GitHub for updates. Windows and Linux downloads are on Nexus
and GitHub. Choose the download for your operating system.
Guide and support: https://github.com/{repository}
Exact release, corresponding source and scan report: {release_url}
License: GPL-3.0-only, see LICENSE.
"""
    # Nexus file descriptions are plain text, unlike the manually pasted page BBCode.
    plain_notes = re.sub(r"(?m)^#{1,6}\s+", "", notes.read_text(encoding="utf-8"))
    plain_notes = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", plain_notes)
    plain_notes = plain_notes.replace("**", "").replace("`", "").strip()
    permission_note = f"If needed, run chmod +x {executable_name} first. " if is_linux else ""
    description = (
        f"KOTOR Mod Installer {version} - {label} standalone app\n\n"
        f"Manual download, extract into its own folder, and run {executable_name}. "
        f"{permission_note}"
        "Do not install through Vortex or extract into the game folder.\n\n"
        f"{plain_notes}\n\nSource, downloads and scan report: {release_url}\n"
    )

    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"kotor-mod-installer-{version}{suffix}-nexus.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipped:
        zipped.write(executable, executable_name)
        if is_linux:
            # Actions artifact downloads lose Unix permissions. Restore them in
            # the ZIP metadata regardless of the machine used to package it.
            info = zipped.getinfo(executable_name)
            info.create_system = 3
            info.external_attr = 0o100755 << 16
        zipped.writestr("READ-ME-FIRST.txt", readme)
        zipped.write(scan_report, "virus-scan.txt")
        zipped.write(license_file, "LICENSE")
        checksums = []
        for name in zipped.namelist():
            # Stream the bundled executable rather than loading it all into memory.
            with zipped.open(name) as member:
                digest = hashlib.file_digest(member, "sha256").hexdigest()
            checksums.append(f"{digest}  {name}\n")
        zipped.writestr("SHA256SUMS.txt", "".join(checksums))
    (output / f"description{suffix}.txt").write_text(description, encoding="utf-8")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--platform", choices=("windows", "linux"), default="windows")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--notes", type=Path, default=Path("release-notes.md"))
    parser.add_argument("--scan-report", type=Path, default=Path("virus-scan.txt"))
    parser.add_argument("--license", type=Path, default=Path("LICENSE"))
    parser.add_argument("--output", type=Path, default=Path("nexus-files"))
    args = parser.parse_args()
    executable = args.executable or Path("release-files") / (
        "KOTOR-Mod-Installer-linux-x86_64" if args.platform == "linux" else "KOTOR-Mod-Installer.exe"
    )
    archive = package_nexus(
        args.tag, args.repository, executable, args.notes,
        args.scan_report, args.license, args.output, args.platform,
    )
    print(archive)


if __name__ == "__main__":
    main()
