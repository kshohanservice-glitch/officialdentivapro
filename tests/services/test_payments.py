"""Tests for payment service: record/multi-method/partial/reverse, status transitions."""
from __future__ import annotations

import pytest
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Role
from dentiva.services import auth_service, invoice_service, patient_service, payment_service
from dentiva.services.auth_service import create_user
from dentiva.services.invoice_service import InvoiceInput, InvoiceLineInput
from dentiva.services.patient_service import PatientInput
from dentiva.services.payment_service import PaymentInput
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
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
        admin = auth_service.authenticate(uow.session, "admin", "Admin@123")
        methods = payment_service.list_payment_methods(uow.session, active_only=True)
        cash = next(m for m in methods if m.code == "cash")
        bkash = next(m for m in methods if m.code == "bkash")
        return admin, cash.id, bkash.id


def _patient(session_factory, admin, name="P"):
    with UnitOfWork(session_factory) as uow:
        p = patient_service.create_patient(uow.session, admin, PatientInput(name=name, phone="01711110002"))
        uow.commit()
        return p.id


def _posted_invoice(session_factory, admin, pid, amount=100000):
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid,
            lines=[InvoiceLineInput(description="Svcs", unit_price_paisa=amount)]))
        inv = invoice_service.post_invoice(uow.session, admin, inv.id)
        uow.commit()
        return inv.id


def test_payments_flow_partial_to_paid(session_factory):
    admin, cash_id, bkash_id = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    iid = _posted_invoice(session_factory, admin, pid, amount=100000)
    # Pay 400 cash → partial
    with UnitOfWork(session_factory) as uow:
        payment_service.record_payment(uow.session, admin, PaymentInput(
            invoice_id=iid, method_id=cash_id, amount_paisa=40000, reference_no=""))
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, iid)
        assert row.paid_paisa == 40000
        assert row.due_paisa == 60000
        assert row.status == "partial"
    # Pay 600 bKash → paid
    with UnitOfWork(session_factory) as uow:
        payment_service.record_payment(uow.session, admin, PaymentInput(
            invoice_id=iid, method_id=bkash_id, amount_paisa=60000))
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, iid)
        assert row.paid_paisa == 100000
        assert row.due_paisa == 0
        assert row.status == "paid"
    # Overpayment is allowed
    with UnitOfWork(session_factory) as uow:
        payment_service.record_payment(uow.session, admin, PaymentInput(
            invoice_id=iid, method_id=cash_id, amount_paisa=5000))
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, iid)
        assert row.paid_paisa == 105000
        assert row.status == "paid"
        assert row.due_paisa == 0


def test_cannot_pay_unposted_or_void(session_factory):
    admin, cash_id, _b = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.create_invoice(uow.session, admin, InvoiceInput(
            patient_id=pid, lines=[InvoiceLineInput(description="X", unit_price_paisa=1000)]))
        uow.commit()
        iid = inv.id
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            payment_service.record_payment(uow.session, admin, PaymentInput(
                invoice_id=iid, method_id=cash_id, amount_paisa=1000))
    with UnitOfWork(session_factory) as uow:
        inv = invoice_service.post_invoice(uow.session, admin, iid)
        invoice_service.void_invoice(uow.session, admin, iid, reason="oops")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            payment_service.record_payment(uow.session, admin, PaymentInput(
                invoice_id=iid, method_id=cash_id, amount_paisa=1000))


def test_reverse_payment_updates_totals(session_factory):
    admin, cash_id, _b = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    iid = _posted_invoice(session_factory, admin, pid, amount=100000)
    with UnitOfWork(session_factory) as uow:
        p = payment_service.record_payment(uow.session, admin, PaymentInput(
            invoice_id=iid, method_id=cash_id, amount_paisa=100000))
        uow.commit()
        pid_pay = p.id
    with UnitOfWork(session_factory) as uow:
        assert invoice_service.get_invoice(uow.session, admin, iid).status == "paid"
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            payment_service.reverse_payment(uow.session, admin, pid_pay, reason="")
        payment_service.reverse_payment(uow.session, admin, pid_pay, reason="Wrong invoice")
        uow.commit()
        row = invoice_service.get_invoice(uow.session, admin, iid)
        assert row.paid_paisa == 0
        assert row.status == "unpaid"
        pay = payment_service.get_payment(uow.session, admin, pid_pay)
        assert pay.reversed_at is not None


def test_zero_or_negative_payment_rejected(session_factory):
    admin, cash_id, _b = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    iid = _posted_invoice(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(ValidationError):
            payment_service.record_payment(uow.session, admin, PaymentInput(
                invoice_id=iid, method_id=cash_id, amount_paisa=0))
        with pytest.raises(ValidationError):
            payment_service.record_payment(uow.session, admin, PaymentInput(
                invoice_id=iid, method_id=cash_id, amount_paisa=-500))


def test_rbac_receptionist_can_record_payment(session_factory):
    """Receptionist role has payments.create but Accountant has payments.refund."""
    admin, cash_id, _b = _bootstrap(session_factory)
    pid = _patient(session_factory, admin)
    iid = _posted_invoice(session_factory, admin, pid)
    with UnitOfWork(session_factory) as uow:
        reception = uow.session.scalar(select(Role).where(Role.name == "Receptionist"))
        create_user(uow.session, admin, username="rec", password="Rec@123",
                    display_name="R", role_id=reception.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        rec = auth_service.authenticate(uow.session, "rec", "Rec@123")
        p = payment_service.record_payment(uow.session, rec, PaymentInput(
            invoice_id=iid, method_id=cash_id, amount_paisa=50000))
        uow.commit()
    # Receptionist cannot refund/reverse
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            payment_service.reverse_payment(uow.session, rec, p.id, reason="err")
