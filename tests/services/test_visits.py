"""Tests for visit service: create/update/close, chart findings, RBAC."""
from __future__ import annotations

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import AuditEvent
from dentiva.services import auth_service, patient_service, visit_service
from dentiva.services.patient_service import PatientInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from dentiva.services.visit_service import FINDING_CODE_TO_COLOR, VisitInput
from sqlalchemy import func, select


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


def _patient(session_factory, admin, name="Test"):
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, PatientInput(name=name, phone="01711110001"))
        uow.commit()
        return p.id


def test_create_visit_records_visit_count_and_audit(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(
            reason="Checkup", chief_complaint="Pain in lower right",
            findings={"46": "caries", "36": "filled"},
        ))
        uow.commit()
        vid = v.id
    assert vid is not None
    assert v.status == "open"
    with UnitOfWork(session_factory) as uow:
        p = patient_service.get_patient(uow.session, pid)
        assert p.visit_count == 1
        assert p.last_visit_at is not None
        summary = visit_service.get_visit(uow.session, admin, vid)
        codes = {f.tooth_code: f.finding for f in summary.findings}
        assert codes == {"46": "caries", "36": "filled"}
        cnt = uow.session.execute(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "visit.create")
        ).scalar_one()
        assert cnt == 1


def test_invalid_finding_or_tooth_rejected(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            visit_service.create_visit(uow.session, admin, pid, VisitInput(findings={"99": "caries"}))
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            visit_service.create_visit(uow.session, admin, pid, VisitInput(findings={"46": "bogus"}))


def test_close_visit_prevents_further_edits(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="x"))
        uow.commit()
        vid = v.id
    with UnitOfWork(session_factory) as uow:
        visit_service.close_visit(uow.session, admin, vid)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            visit_service.set_tooth_finding(uow.session, admin, vid, "46", "caries")


def test_latest_chart_state_merges_visits(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        v1 = visit_service.create_visit(uow.session, admin, pid, VisitInput(findings={"46": "caries"}))
        uow.commit()
        vid1 = v1.id
    # Close first and add a second visit that fills 46.
    with UnitOfWork(session_factory) as uow:
        visit_service.close_visit(uow.session, admin, vid1)
        v2 = visit_service.create_visit(uow.session, admin, pid, VisitInput(findings={"46": "filled"}))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        state = visit_service.latest_chart_state(uow.session, pid)
        assert state["46"] == "filled"


def test_rbac_denies_assistant_create(session_factory):
    admin, assist = _bootstrap(session_factory, extra=True)
    pid = _patient(session_factory, admin)
    assert not assist.has(Permission.VISITS_CREATE)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            visit_service.create_visit(uow.session, assist, pid, VisitInput())


def test_list_visits_ordered_newest_first(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="first"))
        visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="second"))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        visits = visit_service.list_visits(uow.session, admin, pid)
    assert len(visits) == 2
    assert visits[0].reason == "second"
    assert visits[1].reason == "first"


def test_set_tooth_finding_adds_to_open_visit(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput())
        uow.commit()
        vid = v.id
    with UnitOfWork(session_factory) as uow:
        visit_service.set_tooth_finding(uow.session, admin, vid, "11", "sealant")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        s = visit_service.get_visit(uow.session, admin, vid)
        codes = {f.tooth_code: f.finding for f in s.findings}
        assert codes["11"] == "sealant"


def test_findings_constants_have_color():
    assert FINDING_CODE_TO_COLOR["caries"].startswith("#")
