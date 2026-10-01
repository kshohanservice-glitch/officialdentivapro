"""Database engine and session factory for Dentiva Pro.

Uses SQLite in WAL mode with foreign keys enabled and pragmatic timeouts.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from dentiva.paths import paths

log = logging.getLogger(__name__)


def _make_sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
    """Apply Dentiva Pro's default SQLite pragmas on every connection."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.execute("PRAGMA recursive_triggers=ON;")
    # 256 MB mmap; SQLite treats this as advisory.
    cursor.execute("PRAGMA mmap_size=268435456;")
    cursor.close()


def create_app_engine(db_path: Path | None = None) -> Engine:
    """Create the SQLAlchemy engine for the Dentiva Pro database."""
    target = db_path or paths.database_path
    target.parent.mkdir(parents=True, exist_ok=True)
    url = _make_sqlite_url(target)
    engine = create_engine(
        url,
        echo=False,
        future=True,
        connect_args={
            "timeout": 15,  # wait up to 15s on locked DB
            "check_same_thread": False,  # we serialize writers in application code
            "isolation_level": None,  # SQLAlchemy manages transactions
        },
    )
    log.info("Database engine created url=%s", url)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist (development / tests).

    Production applications should use Alembic migrations instead. This helper
    exists so tests and quick-bootstrap code paths can stand up a schema
    without invoking the migration system.
    """
    # Import models so they are registered on Base.metadata before create_all.
    from dentiva import models  # noqa: F401

    from .base import Base

    Base.metadata.create_all(engine)
