"""Tests for patient service CRUD, validation, soft-delete, and RBAC."""
from __future__ import annotations

import datetime as dt

import pytest
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import AuditEvent
from dentiva.services import auth_service, patient_service
from dentiva.services.patient_service import PatientInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from sqlalchemy import func, select


def _setup(session_factory, extra_users: bool = False):
    with UnitOfWork(session_factory) as uow:
        from dentiva.models import ClinicProfile
        existing = uow.session.scalar(select(ClinicProfile).limit(1))
        if existing is None:
            run_setup(
                uow.session,
                SetupInput(
                    clinic_name="Smile Care",
                    clinic_phone="01712345678",
                    dentists=[DentistSetupInput(name="Dr. Rahman", registration_no="BDC-001")],
                    admin_username="admin",
                    admin_password="Admin@123",
                    admin_display_name="Administrator",
                ),
            )
            uow.commit()
    with UnitOfWork(session_factory) as uow:
        admin = auth_service.authenticate(uow.session, "admin", "Admin@123")
    if not extra_users:
        return admin
    from dentiva.models import Role
    from dentiva.services.auth_service import create_user
    with UnitOfWork(session_factory) as uow:
        recep_role = uow.session.scalar(select(Role).where(Role.name == "Receptionist"))
        create_user(uow.session, admin, username="recep", password="Recep@123",
                    display_name="Receptionist", role_id=recep_role.id)
        assistant_role = uow.session.scalar(select(Role).where(Role.name == "Assistant"))
        create_user(uow.session, admin, username="assist", password="Assist@123",
                    display_name="Assistant", role_id=assistant_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        recep = auth_service.authenticate(uow.session, "recep", "Recep@123")
        assistant = auth_service.authenticate(uow.session, "assist", "Assist@123")
    return admin, recep, assistant


def _make(name="Karim Ahmed", phone="01711112222", **overrides):
    data = PatientInput(name=name, phone=phone)
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


def test_create_patient_basic(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, _make())
        uow.commit()
    assert p.id is not None
    assert p.patient_code.startswith("P-")
    assert p.name == "Karim Ahmed"
    assert p.phone == "01711112222"
    assert p.visit_count == 0
    assert p.created_by == admin.user_id
    # Audit log
    with UnitOfWork(session_factory) as uow:
        events = list(uow.session.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "patient",
                                     AuditEvent.action == "patient.create")
        ))
        uow.commit()
    assert events


def test_create_patient_auto_codes_increment(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        a = patient_service.create_patient(uow.session, admin, _make(name="A"))
        b = patient_service.create_patient(uow.session, admin, _make(name="B"))
        uow.commit()
    # Codes should be distinct and sequential (depending on prior id).
    assert a.patient_code != b.patient_code


def test_name_required(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError) as exc:
            patient_service.create_patient(uow.session, admin, _make(name=""))
        assert "name" in str(exc.value).lower() or "required" in exc.value.user_message.lower()


def test_phone_validation_bd(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        # Valid BD number
        p = patient_service.create_patient(uow.session, admin, _make(phone="+8801712345678"))
        uow.commit()
        assert p.phone == "+8801712345678"
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            patient_service.create_patient(uow.session, admin, _make(name="X", phone="1234"))


def test_email_validation(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            patient_service.create_patient(uow.session, admin, _make(name="X", email="not-an-email"))


def test_dob_in_future_rejected(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            patient_service.create_patient(
                uow.session, admin,
                _make(name="X", dob=dt.date.today() + dt.timedelta(days=5)),
            )


def test_dob_sets_age_cache(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(
            uow.session, admin,
            _make(name="Old", dob=dt.date(1970, 6, 15)),
        )
        uow.commit()
    # Age as of 2026-10-01 should be 56.
    assert p.age_cache == 56


def test_patient_code_unique(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        patient_service.create_patient(uow.session, admin, _make(name="A", patient_code="ABC-1"))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            patient_service.create_patient(uow.session, admin, _make(name="B", patient_code="ABC-1"))


def test_list_patients_search_and_rbac(session_factory):
    admin = _setup(session_factory, extra_users=True)
    admin, recep, viewer = admin  # type: ignore[misc]
    # "viewer" here is the Assistant role who has PATIENTS_VIEW but not create/delete.
    with UnitOfWork(session_factory) as uow:
        patient_service.create_patient(uow.session, admin, _make(name="Karim Ahmed", phone="01711110001"))
        patient_service.create_patient(uow.session, admin, _make(name="Rahima Begum", phone="01711110002"))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        all_adm = patient_service.list_patients(uow.session, admin)
        all_rec = patient_service.list_patients(uow.session, recep)
        karims = patient_service.list_patients(uow.session, admin, query="Karim")
        code_match = patient_service.list_patients(uow.session, admin, query="P-")
        assert len(all_adm) == 2
        assert len(all_rec) == 2
        assert len(karims) == 1 and karims[0].name == "Karim Ahmed"
        assert len(code_match) == 2
        # Read-only user has PATIENTS_VIEW → list works.
        assert patient_service.count_patients(uow.session, viewer) == 2


def test_soft_delete_requires_typed_confirmation(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, _make(name="Del Me"))
        uow.commit()
        pid = p.id
        code = p.patient_code
    # Wrong text → raises
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            patient_service.delete_patient(uow.session, admin, pid, confirmation_text="wrong")
    # Correct text → soft-deletes
    with UnitOfWork(session_factory) as uow:
        patient_service.delete_patient(uow.session, admin, pid, confirmation_text=f"DELETE {code}")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        # Default list hides deleted
        patients = patient_service.list_patients(uow.session, admin)
        assert all(pt.id != pid for pt in patients)
        # get_patient without include_deleted raises NotFoundError
        with pytest.raises(NotFoundError):
            patient_service.get_patient(uow.session, pid)
        # Audit log has delete event
        cnt = uow.session.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.entity_type == "patient",
                AuditEvent.action == "patient.delete",
            )
        ).scalar_one()
        assert cnt == 1


def test_delete_blocked_for_patient_with_posted_invoice(session_factory):
    admin = _setup(session_factory)
    from dentiva.core.dates import local_now
    from dentiva.models import Invoice
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, _make(name="Has Invoice"))
        uow.session.flush()
        inv = Invoice(
            invoice_number="INV-D-001", patient_id=p.id,
            date=local_now(), subtotal_paisa=10000, total_paisa=10000,
            is_posted=True, posted_at=local_now(),
            due_paisa=10000, status="unpaid",
        )
        uow.session.add(inv)
        uow.commit()
        pid = p.id
        code = p.patient_code
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError) as exc:
            patient_service.delete_patient(uow.session, admin, pid,
                                           confirmation_text=f"DELETE {code}")
        assert "invoice" in exc.value.user_message.lower()


def test_rbac_create_requires_permission(session_factory):
    admin, _, assistant = _setup(session_factory, extra_users=True)  # type: ignore[misc]
    assert not assistant.has(Permission.PATIENTS_CREATE)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            patient_service.create_patient(uow.session, assistant, _make(name="nope"))


def test_record_visit_increments_count(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, _make(name="Visitor", dob=dt.date(2000, 1, 1)))
        uow.commit()
        pid = p.id
    with UnitOfWork(session_factory) as uow:
        patient_service.record_visit(uow.session, pid)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        p2 = patient_service.get_patient(uow.session, pid)
        assert p2.visit_count == 1
        assert p2.last_visit_at is not None
        assert p2.age_cache is not None


def test_update_patient(session_factory):
    admin = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, _make(name="Before", phone="01711110001"))
        uow.commit()
        pid = p.id
    with UnitOfWork(session_factory) as uow:
        updated = patient_service.update_patient(
            uow.session, admin, pid,
            _make(name="After", phone="01711110002", address="123 Dhaka"),
        )
        uow.commit()
        assert updated.name == "After"
        assert updated.phone == "01711110002"
        assert updated.address == "123 Dhaka"
    # Audit update event recorded
    with UnitOfWork(session_factory) as uow:
        cnt = uow.session.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.entity_type == "patient",
                AuditEvent.action == "patient.update",
            )
        ).scalar_one()
        assert cnt == 1
