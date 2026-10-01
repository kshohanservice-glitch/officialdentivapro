#!/usr/bin/env python3
"""Local release build helper.

Runs the same build steps as the GitHub Actions release workflow so a
developer can produce a signed-off installer artifact locally and drop it
into ``dist/`` when GitHub Releases is unavailable.

Usage::

    python scripts/build_release.py [version]

The version defaults to ``1.0.0``. Requires Python 3.11+, PyInstaller, and
(on Windows) NSIS ``makensis`` available on PATH.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
INSTALLER_SRC = ROOT / "installer" / "DentivaPro-Setup.exe"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else str(ROOT), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Dentiva Pro locally")
    parser.add_argument("version", nargs="?", default="1.0.0")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-installer", action="store_true",
                        help="Build PyInstaller bundle but skip NSIS step")
    args = parser.parse_args()

    DIST.mkdir(exist_ok=True)

    if not args.skip_tests:
        _run([sys.executable, "-m", "ruff", "check", "dentiva", "tests", "scripts"])
        _run([sys.executable, "-m", "pytest", "-q", "-p", "no:pytest-qt"])

    _run([sys.executable, "scripts/build_icon.py"])

    spec = ROOT / "scripts" / "dist_pyinstaller.spec"
    _run([sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm"], cwd=ROOT)

    if args.skip_installer:
        print(f"PyInstaller build finished. Bundle is at {ROOT / 'dist' / 'DentivaPro'}")
        return 0

    makensis = shutil.which("makensis")
    if not makensis:
        print("makensis not found on PATH — skipping NSIS step.")
        print("On Windows, install NSIS and add makensis.exe to PATH.")
        return 0

    _run([makensis, str(ROOT / "installer" / "dentivapro.nsi")], cwd=ROOT)

    final = DIST / f"DentivaPro-Setup-v{args.version}.exe"
    if INSTALLER_SRC.exists():
        shutil.move(str(INSTALLER_SRC), str(final))
        size_mb = final.stat().st_size / (1024 * 1024)
        print(f"\nInstaller built: {final}  ({size_mb:.1f} MB)")
    else:
        print("Installer was not produced — check NSIS output.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
