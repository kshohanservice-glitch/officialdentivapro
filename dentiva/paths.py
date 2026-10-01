"""Filesystem path resolution for Dentiva Pro.

All runtime data lives under a single application data root that resolves to
the correct per-user, per-platform location:

    Windows:  %APPDATA%\\DentivaPro
    macOS:    ~/Library/Application Support/DentivaPro
    Linux:    $XDG_DATA_HOME/DentivaPro (or ~/.local/share/DentivaPro)

Development overrides:

* Set ``DENTIVA_DATA_DIR`` to redirect the data root (useful for tests / portable
  mode).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "DentivaPro"


def _app_data_root() -> Path:
    override = os.environ.get("DENTIVA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def _install_root() -> Path:
    """Return the directory Dentiva Pro is running from.

    Used for bundled assets (themes, fonts, icons) whether running from a
    source checkout or a PyInstaller bundle.
    """
    if getattr(sys, "frozen", False):  # pragma: no cover - only set in frozen builds
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


class Paths:
    """Resolved runtime paths. Instantiated once at bootstrap."""

    def __init__(self) -> None:
        self.install_root = _install_root()
        self.data_root = _app_data_root()

        # Runtime data subdirectories
        self.db_dir = self.data_root / "db"
        self.logs_dir = self.data_root / "logs"
        self.config_dir = self.data_root / "config"
        self.backups_dir = self.data_root / "backups"
        self.attachments_dir = self.data_root / "attachments"
        self.logos_dir = self.data_root / "logos"
        self.tmp_dir = self.data_root / "tmp"

        # Database path
        self.database_path = self.db_dir / "dentiva.db"

        # Bundled assets
        self.assets_dir = self.install_root / "assets"
        self.themes_dir = self.assets_dir / "themes"
        self.fonts_dir = self.assets_dir / "fonts"
        self.images_dir = self.assets_dir / "images"
        self.icon_dir = self.assets_dir / "icon"
        self.app_icon_path = self.icon_dir / "dentiva-pro.ico"

    def ensure(self) -> None:
        """Create all required runtime directories (idempotent)."""
        for directory in (
            self.data_root,
            self.db_dir,
            self.logs_dir,
            self.config_dir,
            self.backups_dir,
            self.attachments_dir,
            self.logos_dir,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


# Singleton accessor. Importing code should use ``paths``.
paths = Paths()
