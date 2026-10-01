# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Dentiva Pro (Windows onedir build).
# Usage:
#   pyinstaller scripts/dist_pyinstaller.spec
import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent
BLOCK_CIPHER = None

a = Analysis(
    [str(PROJECT_ROOT / "dentiva" / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "assets"), "assets"),
        (str(PROJECT_ROOT / "dentiva" / "db" / "migrations"), "dentiva/db/migrations"),
        (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(PROJECT_ROOT / "LICENSE.txt"), "."),
    ],
    hiddenimports=[
        "dentiva.models",
        "dentiva.activation.verifier",
        "dentiva.activation.machine",
        "dentiva.activation._salt",
        "dentiva.activation._digest",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=BLOCK_CIPHER,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=BLOCK_CIPHER)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DentivaPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "icon" / "dentiva-pro.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DentivaPro",
)
