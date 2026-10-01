"""Tests for prescription service: create/edit/finalize/lock/clone/delete."""
from __future__ import annotations

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import auth_service, patient_service, prescription_service, visit_service
from dentiva.services.patient_service import PatientInput
from dentiva.services.prescription_service import MedicineLine, PrescriptionInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from dentiva.services.visit_service import VisitInput


def _bootstrap(session_factory):
    with UnitOfWork(session_factory) as uow:
        from dentiva.models import ClinicProfile
        from sqlalchemy import select
        if uow.session.scalar(select(ClinicProfile).limit(1)) is None:
            run_setup(uow.session, SetupInput(
                clinic_name="C", clinic_phone="01712345678",
                dentists=[DentistSetupInput(name="Dr R", registration_no="1")],
                admin_username="admin", admin_password="Admin@123",
            ))
            uow.commit()
    with UnitOfWork(session_factory) as uow:
        return auth_service.authenticate(uow.session, "admin", "Admin@123")


def _patient(session_factory, admin, name="P"):
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, PatientInput(name=name, phone="01711110001"))
        uow.commit()
        return p.id


def _visit(session_factory, admin, pid):
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="Pain"))
        uow.commit()
        return v.id


def _meds():
    return [
        MedicineLine(name="Amoxicillin", form="capsule", strength="500 mg",
                     frequency_morning=True, frequency_noon=True, frequency_night=True,
                     meal_relation="after", duration_days=5, quantity="30 caps",
                     instructions="Finish course"),
        MedicineLine(name="Ibuprofen", form="tablet", strength="400 mg",
                     frequency_night=True, meal_relation="after", duration_days=3),
    ]


def test_create_prescription_inherits_from_visit(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    vid = _visit(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        rx = prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
            visit_id=vid, chief_complaint="Toothache",
            on_examination="Caries 36", advice="Maintain hygiene",
            medicines=_meds(),
        ))
        uow.commit()
        assert rx.patient_id == pid
        assert rx.visit_id == vid
        assert rx.finalized is False
    with UnitOfWork(session_factory) as uow:
        loaded = prescription_service.get_prescription(uow.session, admin, rx.id)
        assert len(loaded.medicines) == 2
        assert loaded.medicines[0].name == "Amoxicillin"
        assert loaded.medicines[0].frequency_label == "Morning+Noon+Night"


def test_requires_patient(session_factory):
    admin = _bootstrap(session_factory)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
                medicines=_meds(),
            ))


def test_finalize_locks_rx_and_requires_meds_or_notes(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        rx = prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
            patient_id=pid, chief_complaint="", medicines=[],
        ))
        uow.commit()
        rid = rx.id
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            prescription_service.finalize_prescription(uow.session, admin, rid)
    with UnitOfWork(session_factory) as uow:
        prescription_service.update_prescription(uow.session, admin, rid, PrescriptionInput(
            patient_id=pid, medicines=_meds(),
        ))
        rx = prescription_service.finalize_prescription(uow.session, admin, rid)
        uow.commit()
        assert rx.finalized
        assert rx.finalized_at is not None
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            prescription_service.update_prescription(uow.session, admin, rid, PrescriptionInput(
                patient_id=pid, medicines=_meds(), notes="trying",
            ))
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            prescription_service.delete_prescription(uow.session, admin, rid)


def test_clone_creates_editable_copy(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        rx = prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
            patient_id=pid, chief_complaint="Pain", medicines=_meds(),
        ))
        rx = prescription_service.finalize_prescription(uow.session, admin, rx.id)
        uow.commit()
        rid = rx.id
    with UnitOfWork(session_factory) as uow:
        cloned = prescription_service.clone_prescription(uow.session, admin, rid)
        uow.commit()
        assert cloned.id != rid
        assert cloned.finalized is False
        # same meds count
        from dentiva.models import PrescriptionMedicine
        from sqlalchemy import func, select
        cnt_old = uow.session.scalar(select(func.count(PrescriptionMedicine.id)).where(PrescriptionMedicine.prescription_id == rid))
        cnt_new = uow.session.scalar(select(func.count(PrescriptionMedicine.id)).where(PrescriptionMedicine.prescription_id == cloned.id))
        assert cnt_old == cnt_new


def test_duplicate_meds_deduplicated_and_blank_skipped(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    meds = [
        MedicineLine(name="Amox", strength="500"),
        MedicineLine(name=""),  # blank -> skipped
        MedicineLine(name="amox", strength="250"),  # dup -> deduped (case-insensitive)
    ]
    with UnitOfWork(session_factory) as uow:
        rx = prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
            patient_id=pid, medicines=meds,
        ))
        uow.commit()
        loaded = prescription_service.get_prescription(uow.session, admin, rx.id)
        assert len(loaded.medicines) == 1


def test_rbac_assistant_can_view_but_not_edit(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    from dentiva.models import Role
    from dentiva.services.auth_service import create_user
    from sqlalchemy import select
    with UnitOfWork(session_factory) as uow:
        assist_role = uow.session.scalar(select(Role).where(Role.name == "Assistant"))
        create_user(uow.session, admin, username="assist3", password="Assist@123",
                    display_name="Assistant", role_id=assist_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        assist = auth_service.authenticate(uow.session, "assist3", "Assist@123")
        rx = prescription_service.create_prescription(uow.session, admin, PrescriptionInput(
            patient_id=pid, medicines=_meds(),
        ))
        uow.commit()
        rid = rx.id
    # Assistant can view
    with UnitOfWork(session_factory) as uow:
        prescription_service.get_prescription(uow.session, assist, rid)
    # Assistant cannot create
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            prescription_service.create_prescription(uow.session, assist, PrescriptionInput(patient_id=pid))
    # Assistant cannot finalize
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            prescription_service.finalize_prescription(uow.session, assist, rid)
