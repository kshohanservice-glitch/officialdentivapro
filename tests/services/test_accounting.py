"""Accounting service tests — default categories, manual entries, payment auto-posting,
reversal contra entries, and period totals."""
from __future__ import annotations

import datetime as dt

import pytest
from dentiva.core.errors import ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import accounting_service, invoice_service, patient_service, payment_service


def test_default_categories_seeded(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        cats = accounting_service.list_categories(uow.session, admin_principal)
        income = [c for c in cats if c.kind == "income"]
        expense = [c for c in cats if c.kind == "expense"]
        names_inc = {c.name for c in income}
        names_exp = {c.name for c in expense}
        uow.commit()
    assert "Consultation fees" in names_inc
    assert "Other clinical income" in names_inc
    assert "Rent" in names_exp
    assert "Staff salaries" in names_exp
    # Idempotent — second call doesn't duplicate
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        cats2 = accounting_service.list_categories(uow.session, admin_principal)
        assert len(cats2) == len(cats)


def test_manual_expense_entry(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        cats = accounting_service.list_categories(uow.session, admin_principal, kind="expense")
        rent_id = next(c.id for c in cats if c.name == "Rent")
        accounting_service.create_entry(
            uow.session, admin_principal,
            accounting_service.EntryInput(
                date=dt.date(2025, 1, 15),
                kind="expense", category_id=rent_id,
                amount_paisa=2500000,  # 25,000 tk
                reference="Jan-2025", description="Monthly rent",
            ),
        )
        uow.commit()
        entries = accounting_service.list_entries(uow.session, admin_principal,
            start=dt.date(2025, 1, 1), end=dt.date(2025, 1, 31))
    assert len(entries) == 1
    assert entries[0].kind == "expense"
    assert entries[0].amount_paisa == 2500000


def test_invalid_entry_rejected(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        with pytest.raises(ValidationError):
            accounting_service.create_entry(
                uow.session, admin_principal,
                accounting_service.EntryInput(kind="expense", amount_paisa=0),
            )
        with pytest.raises(ValidationError):
            accounting_service.create_entry(
                uow.session, admin_principal,
                accounting_service.EntryInput(kind="income", amount_paisa=10000, category_id=999999),
            )


def test_payment_auto_posts_income_and_reversal(session_factory, admin_principal):
    """A payment generates an income entry; reversing it generates a contra entry."""
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        pid = patient_service.create_patient(uow.session, admin_principal, patient_service.PatientInput(
            name="A/c Patient", dob=dt.date(1990, 1, 1),
        )).id
        inv = invoice_service.create_invoice(uow.session, admin_principal, invoice_service.InvoiceInput(
            patient_id=pid,
            lines=[invoice_service.InvoiceLineInput(
                item_type="custom", description="Consultation", quantity=1, unit_price_paisa=100000,
            )],
        ))
        invoice_service.post_invoice(uow.session, admin_principal, inv.id)
        inv2 = invoice_service.get_invoice(uow.session, admin_principal, inv.id)
        cash_method = next(m for m in payment_service.list_payment_methods(uow.session, admin_principal) if m.code == "cash")
        pay = payment_service.record_payment(uow.session, admin_principal, payment_service.PaymentInput(
            invoice_id=inv2.id, method_id=cash_method.id, amount_paisa=100000,
        ))
        uow.commit()
        # List accounting entries for the period.
        today = dt.date.today()
        entries = accounting_service.list_entries(uow.session, admin_principal, start=today, end=today)
        income_entries = [e for e in entries if e.source == "payment"]
        assert len(income_entries) == 1
        assert income_entries[0].amount_paisa == 100000
        assert income_entries[0].signed_paisa == 100000
        # Reverse payment
        payment_service.reverse_payment(uow.session, admin_principal, pay.id, reason="Refund")
        uow.commit()
        entries2 = accounting_service.list_entries(uow.session, admin_principal, start=today, end=today)
        refunds = [e for e in entries2 if e.source == "payment_reversal"]
        assert len(refunds) == 1
        assert refunds[0].signed_paisa == -100000


def test_period_totals(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        accounting_service.ensure_default_categories(uow.session)
        cats = accounting_service.list_categories(uow.session, admin_principal)
        rent_id = next(c.id for c in cats if c.kind == "expense" and c.name == "Rent")
        # Two expenses: 1000 and 500, one manual income 300.
        for d, amt in [(dt.date(2025, 3, 1), 100000), (dt.date(2025, 3, 5), 50000)]:
            accounting_service.create_entry(uow.session, admin_principal,
                accounting_service.EntryInput(date=d, kind="expense", category_id=rent_id, amount_paisa=amt))
        other_inc = next(c.id for c in cats if c.kind == "income" and c.name == "Other clinical income")
        accounting_service.create_entry(uow.session, admin_principal,
            accounting_service.EntryInput(date=dt.date(2025, 3, 3), kind="income",
                                          category_id=other_inc, amount_paisa=30000))
        uow.commit()
        totals = accounting_service.period_totals(uow.session, admin_principal,
            start=dt.date(2025, 3, 1), end=dt.date(2025, 3, 31))
    assert totals.income_paisa == 30000
    assert totals.expense_paisa == 150000
    assert totals.profit_paisa == -120000
    assert any(name == "Rent" for name, _ in totals.by_category_expense)
    assert len(totals.daily_net) >= 3
