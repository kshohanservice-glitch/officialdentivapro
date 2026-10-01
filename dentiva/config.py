"""Application configuration (settings stored under config_dir).

Settings fall back to built-in defaults and are persisted as a small JSON
file. We use a ``pydantic`` model for validation so corrupted settings files
fail gracefully and fall back to defaults.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from dentiva.paths import paths

log = logging.getLogger(__name__)

CONFIG_FILENAME = "settings.json"

# Default values (overridable through Settings UI).
DEFAULT_AUTOLOCK_MINUTES = 10
DEFAULT_BACKUP_INTERVAL_DAYS = 7
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_CURRENCY = "BDT"
DEFAULT_PATIENT_PREFIX = "P"


class AppConfig(BaseModel):
    """Runtime application configuration. All fields have safe defaults."""

    # Clinic/UI
    clinic_name: str = ""
    last_logged_in_user: str = ""
    window_width: int = 1280
    window_height: int = 800
    window_maximized: bool = True
    sidebar_expanded: bool = True

    # Security
    autolock_minutes: int = Field(default=DEFAULT_AUTOLOCK_MINUTES, ge=0, le=120)
    password_min_length: int = Field(default=6, ge=4, le=64)
    failed_login_lockout_minutes: int = Field(default=10, ge=0, le=1440)
    max_failed_login_attempts: int = Field(default=5, ge=0, le=100)

    # Backup
    backup_folder: str = ""  # empty = use default backups_dir
    backup_interval_days: int = Field(default=DEFAULT_BACKUP_INTERVAL_DAYS, ge=0, le=365)
    last_backup_at: str = ""
    next_backup_at: str = ""

    # Print
    default_paper_prescription: str = DEFAULT_PAPER_SIZE
    default_paper_invoice: str = DEFAULT_PAPER_SIZE
    default_printer_name: str = ""

    # Regional
    currency_code: str = DEFAULT_CURRENCY
    date_format: str = "yyyy-MM-dd"
    use_lakh_grouping: bool = True

    # Patients
    patient_code_prefix: str = DEFAULT_PATIENT_PREFIX
    patient_code_padding: int = Field(default=5, ge=0, le=12)

    # Appointments
    appointment_default_duration_minutes: int = Field(default=15, ge=5, le=240)

    # UX
    animations_enabled: bool = True
    compact_mode: bool = False


_config: AppConfig | None = None
_config_path: Path | None = None


def config_path() -> Path:
    global _config_path
    if _config_path is None:
        _config_path = paths.config_dir / CONFIG_FILENAME
    return _config_path


def load_config() -> AppConfig:
    """Load config from disk, falling back to defaults on any failure."""
    global _config
    paths.ensure()
    p = config_path()
    if not p.exists():
        _config = AppConfig()
        save_config(_config)
        return _config
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        _config = AppConfig(**raw)
    except (OSError, ValueError, ValidationError) as e:
        log.warning("Failed to load config (%s); using defaults.", e)
        _config = AppConfig()
    return _config


def save_config(cfg: AppConfig) -> None:
    global _config
    paths.ensure()
    p = config_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(p)
    _config = cfg


def get_config() -> AppConfig:
    global _config
    if _config is None:
        return load_config()
    return _config


def update_config(**kwargs: Any) -> AppConfig:
    cfg = get_config()
    data = cfg.model_dump()
    data.update(kwargs)
    new_cfg = AppConfig(**data)
    save_config(new_cfg)
    return new_cfg
