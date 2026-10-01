"""Helpers shared between Alembic env.py and bootstrap.

Kept separate so that bootstrap.py does not need to import alembic/env.py
(which only works while an Alembic command is running).
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_sqlalchemy_url(db_path: Path | None = None) -> str:
    """Return the SQLAlchemy URL to apply migrations against."""
    override = os.environ.get("DENTIVA_DATABASE_URL")
    if override:
        return override
    if db_path is None:
        from dentiva.paths import paths as _p
        db_path = _p.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"
