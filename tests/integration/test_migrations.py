"""Alembic migrations: upgrade from zero produces a usable schema."""
from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_config(db_url: str) -> Config:
    migrations_dir = Path(__file__).resolve().parents[2] / "dentiva" / "db" / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_migration_upgrade_head(tmp_path, monkeypatch):
    import importlib
    import sqlite3
    data_dir = tmp_path / "d"
    data_dir.mkdir()
    (data_dir / "db").mkdir()
    monkeypatch.setenv("DENTIVA_DATA_DIR", str(data_dir))
    import dentiva.paths
    importlib.reload(dentiva.paths)
    # Patch modules that hold a cached reference to the old paths singleton.
    from dentiva.db import alembic_support
    monkeypatch.setattr(alembic_support, "paths", dentiva.paths.paths, raising=False)
    # Use create_app_engine directly (it imports paths fresh enough).
    from dentiva.db.engine import create_app_engine
    engine = create_app_engine()

    # Apply Alembic using the env.py directly.
    migrations_dir = Path(__file__).resolve().parents[2] / "dentiva" / "db" / "migrations"
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{dentiva.paths.paths.database_path.as_posix()}")
    command.upgrade(cfg, "head")

    db_file = dentiva.paths.paths.database_path
    conn = sqlite3.connect(db_file)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alembic_version" in tables
    assert "patient" in tables
    assert "invoice" in tables
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert version
    conn.close()
    engine.dispose()
