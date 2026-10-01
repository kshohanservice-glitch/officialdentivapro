"""pytest configuration: each test gets an isolated temp data directory and
a SQLAlchemy session factory backed by a file-based (or in-memory) SQLite
database. Migrations/seed data are applied so the DB is in a realistic state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Dentiva Pro data paths to a temporary directory."""
    data_dir = tmp_path / "dentiva-data"
    data_dir.mkdir()
    monkeypatch.setenv("DENTIVA_DATA_DIR", str(data_dir))
    import importlib

    import dentiva.activation.machine as machine_mod
    import dentiva.activation.verifier as verifier_mod
    import dentiva.bootstrap as bootstrap_mod
    import dentiva.config as cfg_mod
    import dentiva.db.alembic_support as alembic_support
    import dentiva.db.engine as engine_mod
    import dentiva.paths
    import dentiva.services.clinic_service as clinic_mod
    importlib.reload(dentiva.paths)
    monkeypatch.setattr(verifier_mod, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(machine_mod, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(alembic_support, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(engine_mod, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(bootstrap_mod, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(clinic_mod, "paths", dentiva.paths.paths, raising=False)
    monkeypatch.setattr(cfg_mod, "_config", None)
    monkeypatch.setattr(cfg_mod, "_config_path", None)
    return data_dir


@pytest.fixture()
def session_factory(tmp_data_dir: Path):
    from dentiva.bootstrap import _apply_migrations
    from dentiva.db.engine import create_app_engine, create_session_factory
    from dentiva.db.seed import seed_defaults
    engine = create_app_engine()
    _apply_migrations(engine)
    sf = create_session_factory(engine)
    sf._engine = engine  # expose engine for tests
    from dentiva.core.unit_of_work import UnitOfWork
    with UnitOfWork(sf) as uow:
        seed_defaults(uow.session)
        uow.commit()
    yield sf
    engine.dispose()


@pytest.fixture()
def session(session_factory):
    """Single transactional session rolled back after the test."""
    from sqlalchemy.orm import Session
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def admin_principal(session_factory):
    """Run setup (if not already done) and return the initial admin principal."""
    from dentiva.core.permissions import Principal
    from dentiva.core.unit_of_work import UnitOfWork
    from dentiva.models import Role, User
    from dentiva.services.clinic_service import is_setup_complete
    from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
    from sqlalchemy import select

    with UnitOfWork(session_factory) as uow:
        needed = not is_setup_complete(uow.session)
    if needed:
        with UnitOfWork(session_factory) as uow:
            run_setup(uow.session, SetupInput(
                clinic_name="Test Dental",
                clinic_phone="01712345678",
                clinic_email="clinic@example.com",
                admin_username="admin",
                admin_password="secret1",
                admin_display_name="Administrator",
                dentists=[DentistSetupInput(name="Dr. Smith", designations=["BDS"])],
            ))
            uow.commit()

    with UnitOfWork(session_factory) as uow:
        user = uow.session.scalar(select(User).where(User.username == "admin"))
        assert user is not None, "admin user was not created by setup"
        role = uow.session.get(Role, user.role_id) if user.role_id else None
        perms = [p.permission for p in role.permissions] if role else []
        return Principal(user.id, user.username, user.display_name, perms, is_superuser=True)
