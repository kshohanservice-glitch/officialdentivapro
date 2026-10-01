"""Alembic environment for Dentiva Pro."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the project importable when Alembic is invoked from the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import all models so they register on Base.metadata.
from dentiva import models as _models  # noqa: F401
from dentiva.db.alembic_support import resolve_sqlalchemy_url
from dentiva.db.base import Base
from dentiva.paths import paths

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_env_url() -> str:
    """Prefer the configured URL, but fall back to the runtime DB path."""
    url = config.get_main_option("sqlalchemy.url")
    if url and url != "sqlite:///dentiva.db":
        return url
    return resolve_sqlalchemy_url(paths.database_path)


def run_migrations_offline() -> None:
    url = _resolve_env_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = dict(config.get_section(config.config_ini_section, {}))
    configuration["sqlalchemy.url"] = _resolve_env_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
