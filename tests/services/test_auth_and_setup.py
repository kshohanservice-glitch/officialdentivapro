"""Integration tests for Phase 3: setup wizard, authentication, RBAC, users."""
import pytest
from dentiva.core.errors import (
    AuthenticationError,
    PermissionDeniedError,
    ValidationError,
)
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import ClinicProfile, Role, User
from dentiva.services import auth_service, clinic_service, user_service
from dentiva.services.setup_service import SetupInput, run_setup
from sqlalchemy import select


def test_setup_wizard_atomic(session_factory, admin_principal):
    # The admin_principal fixture already completed setup; this test verifies
    # the row contents afterwards.
    with UnitOfWork(session_factory) as uow:
        cp = uow.session.scalar(select(ClinicProfile).limit(1))
        assert cp is not None
        assert cp.setup_completed is True
        admin = uow.session.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        assert admin.is_superuser is True
        assert admin.is_active is True


def test_setup_requires_dentist(session_factory, admin_principal):
    # After setup is complete, attempting setup again raises an error.
    with pytest.raises(ValidationError):
        with UnitOfWork(session_factory) as uow:
            run_setup(uow.session, SetupInput(
                clinic_name="Second Clinic",
                admin_username="admin2", admin_password="pass123",
                dentists=[],
            ))


def test_setup_validation_requires_dentist_before_complete(session_factory):
    """Setup validates inputs before writing anything — empty-dentist case
    can be tested before the admin_principal fixture completes setup."""
    with pytest.raises(ValidationError):
        with UnitOfWork(session_factory) as uow:
            run_setup(uow.session, SetupInput(
                clinic_name="No Dentist Clinic",
                admin_username="admin", admin_password="pass123",
                dentists=[],
            ))
            uow.commit()
    with UnitOfWork(session_factory) as uow:
        # Confirm DB was NOT modified (no clinic row).
        cp = uow.session.scalar(select(ClinicProfile).limit(1))
        assert cp is None


def test_authentication_valid_and_invalid(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        principal = auth_service.authenticate(uow.session, "admin", "secret1")
        uow.commit()
    assert principal.username == "admin"
    assert principal.has(Permission.USERS_CREATE)

    with pytest.raises(AuthenticationError):
        with UnitOfWork(session_factory) as uow:
            auth_service.authenticate(uow.session, "admin", "wrong")


def test_locked_account(session_factory, admin_principal):
    from dentiva.services.auth_service import authenticate
    # Force lock immediately by logging in with wrong password N times.
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            with UnitOfWork(session_factory) as uow:
                authenticate(uow.session, "admin", "wrong1", max_attempts=5, lockout_minutes=10)
                uow.commit()
    # Even the correct password should be blocked during lockout.
    with pytest.raises(AuthenticationError) as exc_info:
        with UnitOfWork(session_factory) as uow:
            authenticate(uow.session, "admin", "secret1", max_attempts=5, lockout_minutes=10)
    assert "locked" in exc_info.value.user_message.lower()


def test_rbac_enforced_in_user_service(session_factory, admin_principal):
    # Build a receptionist principal (without user management permission).
    receptionist = type("P", (), {
        "user_id": 999, "username": "recep", "display_name": "Recep",
        "is_superuser": False,
        "permissions": {Permission.PATIENTS_VIEW},
        "has": lambda self, p: p in self.permissions,
        "can_view_financials": lambda self: False,
    })()
    with pytest.raises(PermissionDeniedError):
        with UnitOfWork(session_factory) as uow:
            user_service.list_users(uow.session, receptionist)


def test_create_user_and_reset_password(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        # Use a non-admin role: Dentist
        dentist_role = uow.session.scalar(select(Role).where(Role.name == "Dentist"))
        new_user = auth_service.create_user(
            uow.session, admin_principal,
            username="assistant1", password="assistpw",
            display_name="Assistant One", role_id=dentist_role.id,
        )
        uow.commit()
        uid = new_user.id
    with UnitOfWork(session_factory) as uow:
        user_service.reset_password(uow.session, admin_principal, uid, "newpass1")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        p = auth_service.authenticate(uow.session, "assistant1", "newpass1")
        uow.commit()
    assert p.username == "assistant1"


def test_password_must_be_min_length(session_factory, admin_principal):
    with pytest.raises(ValidationError):
        with UnitOfWork(session_factory) as uow:
            auth_service.create_user(
                uow.session, admin_principal,
                username="badpw", password="1", display_name="Bad",
                role_id=None,
            )


def test_clinic_profile_marks_setup_complete(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        assert clinic_service.is_setup_complete(uow.session) is True
