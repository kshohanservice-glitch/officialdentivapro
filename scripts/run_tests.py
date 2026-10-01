#!/usr/bin/env python
"""Convenience wrapper: ruff + mypy + pytest."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    rc = run([sys.executable, "-m", "ruff", "check", "dentiva", "tests"])
    if rc:
        return rc
    rc = run([sys.executable, "-m", "mypy", "dentiva"])
    if rc:
        return rc
    rc = run([sys.executable, "-m", "pytest", "--cov=dentiva", "--cov-report=term-missing"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
