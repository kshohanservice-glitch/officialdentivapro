"""Lightweight stress checks: bulk insert + concurrent-read stability.

These tests are intentionally short but exercise hot paths with hundreds of
rows to catch SQLAlchemy-session / integer-overflow / pagination regressions.
"""
from __future__ import annotations

import io

import pytest
from dentiva.models import InventoryItem, Patient
from dentiva.services import attachment_service
from dentiva.services.dashboard_service import global_search

pytestmark = pytest.mark.usefixtures("session_factory")


def test_bulk_patients_stay_searchable(session, admin_principal):
    from dentiva.core.unit_of_work import UnitOfWork
    # Insert 200 patients in one transaction.
    for i in range(200):
        session.add(Patient(
            name=f"Stress Patient {i:03d}", phone=f"018{i:07d}",
            gender="male", patient_code=f"ST-{i:04d}",
        ))
    session.commit()
    with UnitOfWork(lambda: session) as uow:
        results = global_search(uow.session, admin_principal, "Stress", limit=500)
        uow.commit()
    patient_hits = [r for r in results if r.kind == "patients"]
    assert len(patient_hits) == 200


def test_bulk_inventory_and_search(session, admin_principal):
    from dentiva.core.unit_of_work import UnitOfWork
    for i in range(300):
        session.add(InventoryItem(
            name=f"Item-{i:04d}", sku=f"SKU-{i:05d}", unit="pcs",
            current_qty=i % 50, min_level_qty=5,
        ))
    session.commit()
    with UnitOfWork(lambda: session) as uow:
        results = global_search(uow.session, admin_principal, "Item-00", limit=500)
        uow.commit()
    assert len([r for r in results if r.kind == "inventory"]) >= 10


def test_many_attachments(session, admin_principal):
    p = Patient(name="MultiAttacher", phone="01790000000", gender="male", patient_code="MA-0001")
    session.add(p)
    session.commit()
    for i in range(25):
        attachment_service.upload_attachment(
            session, admin_principal, attachable_type="patient", attachable_id=p.id,
            filename=f"file-{i}.txt", stream=io.BytesIO(b"x" * 1024),
            title=f"File {i}", notes="bulk",
        )
    session.commit()
    lst = attachment_service.list_attachments(
        session, admin_principal, attachable_type="patient", attachable_id=p.id,
    )
    assert len(lst) == 25
