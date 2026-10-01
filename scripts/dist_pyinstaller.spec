# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Dentiva Pro (Windows onedir build).
# Usage:
#   pyinstaller scripts/dist_pyinstaller.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
BLOCK_CIPHER = None

# Collect every dentiva submodule to avoid hidden-import misses at runtime.
_dentiva_hidden = collect_submodules("dentiva")

# SQLAlchemy dialects and Alembic migration templates are commonly missed
# by static analysis; include them explicitly.
_extra_hidden = [
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.base",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "alembic",
    "alembic.config",
    "alembic.runtime.migration",
    "alembic.operations",
    "alembic.autogenerate",
    "logging.config",
    # Qt PrintSupport is used by dentiva.printing and some PySide6
    # distributions don't pull it in automatically.
    "PySide6.QtPrintSupport",
]

_alembic_datas = collect_data_files("alembic")

a = Analysis(
    [str(PROJECT_ROOT / "dentiva" / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "assets"), "assets"),
        (str(PROJECT_ROOT / "dentiva" / "db" / "migrations"), "dentiva/db/migrations"),
        (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(PROJECT_ROOT / "LICENSE.txt"), "."),
    ]
    + _alembic_datas,
    hiddenimports=_dentiva_hidden + _extra_hidden,
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
