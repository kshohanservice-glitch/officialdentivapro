"""Tests for invoice service: draft/post/void, line items, totals, visit→invoice."""
from __future__ import annotations

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Role
from dentiva.services import (
    auth_service,
    invoice_service,
    patient_service,
    treatment_service,
    visit_service,
)
from dentiva.services.auth_service import create_user
from dentiva.services.invoice_service import InvoiceInput, InvoiceLineInput
from dentiva.services.patient_service import PatientInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from dentiva.services.treatment_service import TreatmentCatalogInput, TreatmentRecordInput
from dentiva.services.visit_service import VisitInput
from sqlalchemy import select


def _bootstrap(session_factory):
    with UnitOfWork(session_factory) as uow:
        from dentiva.models import ClinicProfile
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


def _visit_and_catalog(session_factory, admin, pid):
    with UnitOfWork(session_factory) as uow:
        cat = treatment_service.create_catalog_item(uow.session, admin, TreatmentCatalogInput(
            name="Filling", default_price_paisa=100000))
        uow.commit()
        cid = cat.id
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="Pain"))
        uow.commit()
        vid = v.id
        treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
            catalog_id=cid, tooth_codes="36"))
        treatment_service.add_treatment_to_visit(uow.session, admin, vid, TreatmentRecordInput(
            catalog_id=cid, tooth_codes="46", price_paisa=100000))
        uow.commit()
    return vid, cid


def test_invoice_numbering_and_basic_totals(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid,
            lines=[
                InvoiceLineInput(description="Consultation", unit_price_paisa=50000, quantity=1),
                InvoiceLineInput(description="X-Ray", unit_price_paisa=30000, quantity=2, discount_paisa=1000),
            ],
            discount_paisa=5000, tax_paisa=10000,
        ))
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, inv.id)
        # subtotal: 50000 + (30000*2 - 1000) = 50000 + 59000 = 109000
        assert row.subtotal_paisa == 109000
        # total: 109000 - 5000 + 10000 = 114000
        assert row.total_paisa == 114000
        assert row.paid_paisa == 0
        assert row.due_paisa == 114000
        assert row.status == "draft"
        assert row.is_posted is False
        assert row.invoice_number.startswith("INV-")
        # Create another invoice same day - number increments
        inv2 = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid, lines=[InvoiceLineInput(description="A", unit_price_paisa=1000)]))
        uow.commit()
        assert inv2.invoice_number != inv.invoice_number
        assert int(inv2.invoice_number.split("-")[-1]) == int(inv.invoice_number.split("-")[-1]) + 1


def test_post_locks_and_requires_lines(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid, lines=[]))
        uow.commit()
        with pytest.raises(ValidationError):
            invoice_service.post_invoice(uow.session, admin, inv.id)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.update_invoice(uow.session, admin, inv.id, InvoiceInput(
            patient_id=pid,
            lines=[InvoiceLineInput(description="X", unit_price_paisa=1000)],
        ))
        inv = invoice_service.post_invoice(uow.session, admin, inv.id)
        uow.commit()
        assert inv.is_posted
        assert inv.posted_at is not None
        assert inv.status == "unpaid"
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            invoice_service.update_invoice(uow.session, admin, inv.id, InvoiceInput(
                patient_id=pid, lines=[InvoiceLineInput(description="Y", unit_price_paisa=2000)]))


def test_create_from_visit(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    vid, _cid = _visit_and_catalog(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice_from_visit(uow.session, admin, vid,
                                                        discount_paisa=2000, tax_paisa=500)
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, inv.id)
        assert len(row.lines) == 2
        assert row.subtotal_paisa == 200000
        assert row.total_paisa == 200000 - 2000 + 500  # 198500
        assert row.visit_id == vid
        assert row.patient_id == pid
        # Auto-post variant
        inv2 = invoice_service.create_invoice_from_visit(uow.session, admin, vid, auto_post=True)
        uow.commit()
        assert inv2.is_posted


def test_visit_with_no_treatments_fails(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        v = visit_service.create_visit(uow.session, admin, pid, VisitInput(reason="x"))
        uow.commit()
        vid = v.id
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            invoice_service.create_invoice_from_visit(uow.session, admin, vid)


def test_void_requires_reason_and_blocks_payment(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid, lines=[InvoiceLineInput(description="X", unit_price_paisa=1000)]))
        inv = invoice_service.post_invoice(uow.session, admin, inv.id)
        uow.commit()
        iid = inv.id
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            invoice_service.void_invoice(uow.session, admin, iid, reason="")
        invoice_service.void_invoice(uow.session, admin, iid, reason="Duplicate invoice")
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, iid)
        assert row.status == "void"
        assert row.voided_at is not None


def test_delete_only_draft(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid, lines=[InvoiceLineInput(description="X", unit_price_paisa=1000)]))
        inv = invoice_service.post_invoice(uow.session, admin, inv.id)
        uow.commit()
        iid = inv.id
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            invoice_service.delete_invoice(uow.session, admin, iid)


def test_negative_price_rejected(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            invoice_service.create_invoice(uow.session, admin, InvoiceInput(
                patient_id=pid,
                lines=[InvoiceLineInput(description="X", unit_price_paisa=-100)]))


def test_rbac_assistant_cannot_create_invoice(session_factory):
    admin = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        assist_role = uow.session.scalar(select(Role).where(Role.name == "Assistant"))
        create_user(uow.session, admin, username="assist_inv", password="Assist@123",
                    display_name="A", role_id=assist_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        assist = auth_service.authenticate(uow.session, "assist_inv", "Assist@123")
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            invoice_service.create_invoice(uow.session, assist, InvoiceInput(
                patient_id=pid, lines=[InvoiceLineInput(description="x", unit_price_paisa=100)]))
