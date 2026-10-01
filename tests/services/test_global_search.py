"""Global search coverage for new entity types (prescriptions, inventory, attachments)."""
from __future__ import annotations

import io

import pytest
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import InventoryItem, Patient, Prescription
from dentiva.services import attachment_service
from dentiva.services.dashboard_service import global_search

pytestmark = pytest.mark.usefixtures("session_factory")


def test_global_search_finds_inventory(admin_principal, session):
    ii = InventoryItem(name="Amalgam Capsule", sku="AMG-01", unit="pcs",
                       current_qty=10, min_level_qty=2)
    session.add(ii)
    session.commit()
    with UnitOfWork(lambda: session) as uow:
        results = global_search(uow.session, admin_principal, "Amalgam", limit=20)
        uow.commit()
    assert any(r.kind == "inventory" for r in results)


def test_global_search_finds_prescription(admin_principal, session):
    p = Patient(name="SearchRx Pat", phone="01700000099", patient_code="SRX-001",
                gender="male")
    session.add(p)
    session.flush()
    rx = Prescription(patient_id=p.id, chief_complaint="Severe toothache")
    session.add(rx)
    session.commit()
    with UnitOfWork(lambda: session) as uow:
        results = global_search(uow.session, admin_principal, "toothache", limit=20)
        uow.commit()
    assert any(r.kind == "prescriptions" for r in results)


def test_global_search_finds_attachments(admin_principal, session):
    p = Patient(name="AttachFind", phone="01700000100", patient_code="SAT-001",
                gender="male")
    session.add(p)
    session.flush()
    attachment_service.upload_attachment(
        session, admin_principal,
        attachable_type="patient", attachable_id=p.id,
        filename="opg-xray.png", stream=io.BytesIO(b"\x89PNG-fake"),
        title="OPG X-ray report", notes="full mouth",
    )
    session.commit()
    with UnitOfWork(lambda: session) as uow:
        results = global_search(uow.session, admin_principal, "xray", limit=20)
        uow.commit()
    assert any(r.kind == "attachments" for r in results)
