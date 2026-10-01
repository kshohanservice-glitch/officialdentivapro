"""Tests for appointment & queue service."""
from __future__ import annotations

import datetime as dt

import pytest
from dentiva.core.dates import local_now
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Appointment
from dentiva.services import appointment_service, auth_service, dentist_service, patient_service
from dentiva.services.appointment_service import AppointmentInput
from dentiva.services.patient_service import PatientInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from sqlalchemy import select


def _bootstrap(session_factory, extra: bool = False):
    with UnitOfWork(session_factory) as uow:
        from dentiva.models import ClinicProfile, Role
        if uow.session.scalar(select(ClinicProfile).limit(1)) is None:
            run_setup(uow.session, SetupInput(
                clinic_name="C", clinic_phone="01712345678",
                dentists=[DentistSetupInput(name="Dr R", registration_no="1")],
                admin_username="admin", admin_password="Admin@123",
            ))
            uow.commit()
    with UnitOfWork(session_factory) as uow:
        admin = auth_service.authenticate(uow.session, "admin", "Admin@123")
    if not extra:
        return admin
    from dentiva.models import Role
    from dentiva.services.auth_service import create_user
    with UnitOfWork(session_factory) as uow:
        assist_role = uow.session.scalar(select(Role).where(Role.name == "Assistant"))
        create_user(uow.session, admin, username="assist", password="Assist@123",
                    display_name="Assistant", role_id=assist_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        assist = auth_service.authenticate(uow.session, "assist", "Assist@123")
    return admin, assist


def _patient(session_factory, admin, name="P"):
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, PatientInput(name=name, phone="01711110001"))
        uow.commit()
        return p.id


def _get_dentist(session_factory):
    from dentiva.models import Dentist
    with UnitOfWork(session_factory) as uow:
        return uow.session.scalar(select(Dentist)).id


def test_list_dentists_loads_designations_without_joined_result_error(session_factory):
    admin = _bootstrap(session_factory)
    with UnitOfWork(session_factory) as uow:
        dentists = dentist_service.list_dentists(uow.session, admin)
        assert len(dentists) == 1
        assert dentists[0].name == "Dr R"
        assert dentists[0].designations == []


def test_create_appointment_basic(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    did = _get_dentist(session_factory)
    start = local_now() + dt.timedelta(hours=1)
    with UnitOfWork(session_factory) as uow:
        a = appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, dentist_id=did, scheduled_at=start, duration_minutes=15, reason="Checkup",
        ))
        uow.commit()
    assert a.id is not None
    assert a.status == "scheduled"
    assert a.duration_minutes == 15


def test_conflict_detection(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    did = _get_dentist(session_factory)
    start = local_now().replace(second=0, microsecond=0) + dt.timedelta(hours=2)
    with UnitOfWork(session_factory) as uow:
        appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, dentist_id=did, scheduled_at=start, duration_minutes=30))
        uow.commit()
    # Overlapping appointment at same time with same dentist → conflict
    with UnitOfWork(session_factory) as uow:
        pid2 = _patient(session_factory, admin, name="P2")
        with pytest.raises(ValidationError):
            appointment_service.create_appointment(uow.session, admin, AppointmentInput(
                patient_id=pid2, dentist_id=did, scheduled_at=start + dt.timedelta(minutes=10), duration_minutes=15))
    # Adjacent appointment (starts when previous ends) should be OK
    with UnitOfWork(session_factory) as uow:
        appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid2, dentist_id=did, scheduled_at=start + dt.timedelta(minutes=30), duration_minutes=15))
        uow.commit()


def test_validation_missing_patient_and_time(session_factory):
    admin = _bootstrap(session_factory)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            appointment_service.create_appointment(uow.session, admin, AppointmentInput())


def test_cancel_appointment(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    did = _get_dentist(session_factory)
    start = local_now() + dt.timedelta(hours=3)
    with UnitOfWork(session_factory) as uow:
        a = appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, dentist_id=did, scheduled_at=start))
        uow.commit()
        aid = a.id
    with UnitOfWork(session_factory) as uow:
        appointment_service.cancel_appointment(uow.session, admin, aid, reason="Patient called")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        a = uow.session.get(Appointment, aid)
        assert a.status == "cancelled"
        assert a.cancelled_at is not None


def test_rbac_assistant_cannot_create(session_factory):
    admin, assist = _bootstrap(session_factory, extra=True)
    pid = _patient(session_factory, admin)
    assert not assist.has(Permission.APPOINTMENTS_CREATE)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            appointment_service.create_appointment(uow.session, assist, AppointmentInput(
                patient_id=pid, scheduled_at=local_now() + dt.timedelta(hours=1)))


def test_check_in_creates_queue_entry_and_marks_appt(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    did = _get_dentist(session_factory)
    start = local_now()
    with UnitOfWork(session_factory) as uow:
        a = appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, dentist_id=did, scheduled_at=start))
        uow.commit()
        aid = a.id
    with UnitOfWork(session_factory) as uow:
        q = appointment_service.check_in_appointment(uow.session, admin, aid)
        uow.commit()
        assert q.status == "waiting"
        appt = uow.session.get(Appointment, aid)
        assert appt.status == "checked_in"


def test_walk_in_adds_to_queue(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        q = appointment_service.walk_in(uow.session, admin, pid, reason="Toothache")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        queue = appointment_service.list_queue(uow.session, admin)
        assert len(queue) == 1
        assert queue[0].status == "waiting"
        assert queue[0].patient_id == pid


def test_start_then_finish_flow(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    did = _get_dentist(session_factory)
    start = local_now()
    with UnitOfWork(session_factory) as uow:
        a = appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, dentist_id=did, scheduled_at=start))
        uow.commit()
        aid = a.id
    with UnitOfWork(session_factory) as uow:
        q = appointment_service.check_in_appointment(uow.session, admin, aid)
        uow.commit()
        qid = q.id
    with UnitOfWork(session_factory) as uow:
        _q, vid = appointment_service.start_service(uow.session, admin, qid)
        uow.commit()
        assert vid is not None
        # Queue entry now with_dentist
    with UnitOfWork(session_factory) as uow:
        q2 = appointment_service.finish_service(uow.session, admin, qid)
        uow.commit()
        assert q2.status == "finished"
        appt = uow.session.get(Appointment, aid)
        assert appt.status == "completed"


def test_upcoming_appointments_filter(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    future = local_now() + dt.timedelta(minutes=15)
    with UnitOfWork(session_factory) as uow:
        appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, scheduled_at=future))
        # Past appointment shouldn't show in upcoming.
        appointment_service.create_appointment(uow.session, admin, AppointmentInput(
            patient_id=pid, scheduled_at=local_now() - dt.timedelta(hours=1)))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        upcoming = appointment_service.upcoming_appointments(uow.session, admin, within_minutes=60)
        assert len(upcoming) == 1
