"""Application bootstrap: initialise paths, logging, config, and the database.

This module does **not** import Qt so that non-GUI tooling (tests,
migrations, admin scripts) can use it.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy.engine import Engine

from dentiva import activation
from dentiva.config import load_config
from dentiva.core.logging_setup import configure_logging
from dentiva.db.alembic_support import resolve_sqlalchemy_url
from dentiva.db.engine import create_app_engine, create_session_factory
from dentiva.paths import paths

log = logging.getLogger(__name__)


class BootstrapResult:
    def __init__(self, engine: Engine, is_activated: bool, is_setup_complete: bool) -> None:
        self.engine = engine
        self.session_factory = create_session_factory(engine)
        self.is_activated = is_activated
        self.is_setup_complete = is_setup_complete


def _ensure_assets() -> None:
    """Create minimal asset files if missing (e.g. when running from a fresh checkout).

    Real branded assets will be created in later phases; this ensures the app
    never crashes due to a missing theme/images folder.
    """
    paths.ensure()
    # Bundled assets are read-only when running from the installed
    # PyInstaller application under Program Files. Runtime/user data must
    # stay under paths.data_root, which is writable by the current user.
    # In a source checkout, create the asset directories so a fresh checkout
    # can still start without pre-created folders.
    if not getattr(__import__("sys"), "frozen", False):
        paths.themes_dir.mkdir(parents=True, exist_ok=True)
        paths.fonts_dir.mkdir(parents=True, exist_ok=True)
        paths.images_dir.mkdir(parents=True, exist_ok=True)
        paths.icon_dir.mkdir(parents=True, exist_ok=True)


def _apply_migrations(engine: Engine) -> None:
    """Apply all pending Alembic migrations.

    A pre-migration safety backup of the database file is made before any
    schema change, in case migrations encounter an unexpected state.
    """
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config()
        migrations_dir = Path(__file__).resolve().parent / "db" / "migrations"
        alembic_cfg.set_main_option("script_location", str(migrations_dir))
        alembic_cfg.set_main_option("sqlalchemy.url", resolve_sqlalchemy_url())

        # Pre-migration safety backup
        db_path = paths.database_path
        if db_path.exists():
            backup_name = f"pre-migration-{db_path.name}.bak"
            backup_path = paths.backups_dir / backup_name
            paths.backups_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path, backup_path)
            log.info("Pre-migration backup written to %s", backup_path)

        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        log.exception("Migration failed: %s", e)
        raise


def _is_setup_complete(engine: Engine) -> bool:
    from sqlalchemy import text
    with engine.connect() as conn:
        row = conn.execute(text("SELECT COUNT(*) FROM clinic_profile")).scalar()
        if not row:
            return False
        done = conn.execute(text("SELECT setup_completed FROM clinic_profile LIMIT 1")).scalar()
        return bool(done)


def bootstrap(*, log_level: int = logging.INFO) -> BootstrapResult:
    """Run the full non-GUI bootstrap. Returns a :class:`BootstrapResult`."""
    _ensure_assets()
    configure_logging(level=log_level)
    log.info("Bootstrapping Dentiva Pro (data_root=%s)", paths.data_root)
    load_config()

    engine = create_app_engine()
    _apply_migrations(engine)

    activated = activation.verifier.is_activated()
    setup_complete = _is_setup_complete(engine) if activated else False

    return BootstrapResult(
        engine=engine,
        is_activated=activated,
        is_setup_complete=setup_complete,
    )
