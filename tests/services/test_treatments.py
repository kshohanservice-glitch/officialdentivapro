"""Tests for treatment catalog and records."""
from __future__ import annotations

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import (
    auth_service,
    patient_service,
    treatment_service,
    visit_service,
)
from dentiva.services.patient_service import PatientInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from dentiva.services.treatment_service import TreatmentCatalogInput, TreatmentRecordInput
from dentiva.services.visit_service import VisitInput


def _bootstrap(session_factory):
    with UnitOfWork(session_factory) as uow:
        from dentiva.models import ClinicProfile
        if uow.session.scalar(__import__("sqlalchemy", fromlist=["select"]).select(ClinicProfile).limit(1)) is None:
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


def _get_dentist(session_factory):
    from dentiva.models import Dentist
    from sqlalchemy import select
    with UnitOfWork(session_factory) as uow:
        return uow.session.scalar(select(Dentist)).id


def _visit(session_factory, admin, pid):
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="Checkup"))
        uow.commit()
        return v.id


def test_catalog_crud(session_factory):
    admin = _bootstrap(session_factory)
    with UnitOfWork(session_factory) as uow:
        item = treatment_service.create_catalog_item(uow.session, admin, TreatmentCatalogInput(
            name="Composite Filling", category="Restorative", default_price_paisa=150000,
        ))
        uow.commit()
        cid = item.id
    with UnitOfWork(session_factory) as uow:
        listed = treatment_service.list_catalog(uow.session, admin)
        names = [i.name for i in listed]
        assert "Composite Filling" in names
    with UnitOfWork(session_factory) as uow:
        treatment_service.update_catalog_item(uow.session, admin, cid, TreatmentCatalogInput(
            name="Composite Filling (Class II)", category="Restorative", default_price_paisa=200000,
        ))
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        got = treatment_service.get_catalog(uow.session, admin, cid)
        assert got.name == "Composite Filling (Class II)"
        assert got.default_price_paisa == 200000
    # Duplicate name rejected
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            treatment_service.create_catalog_item(uow.session, admin, TreatmentCatalogInput(
                name="Composite Filling (Class II)", default_price_paisa=100,
            ))


def test_catalog_requires_manage_permission(session_factory):
    admin = _bootstrap(session_factory)
    # Assistant role only has TREATMENTS_VIEW. We'll use principal from bootstrap (admin has all)
    # but strip permission via check — use assistant bootstrap:
    from dentiva.models import Role
    from dentiva.services.auth_service import create_user
    from sqlalchemy import select
    with UnitOfWork(session_factory) as uow:
        assist_role = uow.session.scalar(select(Role).where(Role.name == "Assistant"))
        create_user(uow.session, admin, username="assist2", password="Assist@123",
                    display_name="Assistant", role_id=assist_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        assist = auth_service.authenticate(uow.session, "assist2", "Assist@123")
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            treatment_service.create_catalog_item(uow.session, assist, TreatmentCatalogInput(name="X"))


def test_treatment_record_workflow(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    vid = _visit(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        cat = treatment_service.create_catalog_item(uow.session, admin, TreatmentCatalogInput(
            name="Scaling", default_price_paisa=80000,
        ))
        uow.commit()
        cid = cat.id
    # Add treatment referencing the catalog — price/name should snapshot
    with UnitOfWork(session_factory) as uow:
        rec = treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
            catalog_id=cid, tooth_codes="36, 46",
        ))
        uow.commit()
        assert rec.name_at_service_time == "Scaling"
        assert rec.price_paisa == 80000
        assert rec.tooth_codes == "36,46"
    # Tooth code validation rejects invalid codes
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
                catalog_id=cid, tooth_codes="99",
            ))
    # Deactivate catalog item and reprice catalog doesn't change record
    with UnitOfWork(session_factory) as uow:
        treatment_service.update_catalog_item(uow.session, admin, cid, TreatmentCatalogInput(
            name="Scaling", default_price_paisa=1_200_00,
        ))
        recs = treatment_service.list_treatments_for_visit(uow.session, admin, vid)
        assert len(recs) == 1
        assert recs[0].price_paisa == 80000
    # Total for visit
    with UnitOfWork(session_factory) as uow:
        assert treatment_service.visit_total_paisa(uow.session, vid) == 80000
    # Cannot add treatment to closed visit
    with UnitOfWork(session_factory) as uow:
        visit_service.close_visit(uow.session, admin, vid)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
                catalog_id=cid,
            ))


def test_custom_treatment_without_catalog(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    vid = _visit(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        rec = treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
            name_at_service_time="Emergency palliative treatment",
            price_paisa=50000,
        ))
        uow.commit()
        assert rec.catalog_id is None
        assert rec.price_paisa == 50000
