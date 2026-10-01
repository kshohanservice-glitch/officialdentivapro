"""Payments service — record payments against posted invoices, multi-method,
partial payments, refunds/reversals with reason.

Only POSTED invoices accept payments (you can't pay a draft). Payments are
always additive on the invoice; after each payment the invoice's paid/due/status
is refreshed (unpaid → partial → paid). Reversals mark a payment reversed (soft
delete by flag) so the full payment history remains for audit.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import Invoice, Patient, Payment, PaymentMethod
from dentiva.services.audit_service import record as audit_record

PAYMENT_METHOD_CODES = ("cash", "bkash", "nagad", "rocket", "upay", "card", "bank", "other")


@dataclass
class PaymentMethodRow:
    id: int
    code: str
    name: str
    is_active: bool
    sort_order: int


@dataclass
class PaymentInput:
    invoice_id: int
    method_id: int
    amount_paisa: int
    reference_no: str = ""
    notes: str = ""
    paid_at: dt.datetime | None = None


@dataclass
class PaymentRow:
    id: int
    invoice_id: int
    invoice_number: str
    patient_id: int
    patient_name: str
    method_id: int
    method_code: str
    method_name: str
    amount_paisa: int
    reference_no: str
    notes: str
    paid_at: dt.datetime
    reversed_at: dt.datetime | None
    reversal_reason: str
    created_by: int | None


# ------------------------------------------------- methods


def list_payment_methods(
    session: Session, active_only: bool = True
) -> list[PaymentMethodRow]:
    stmt = select(PaymentMethod)
    if active_only:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    stmt = stmt.order_by(PaymentMethod.sort_order.asc(), PaymentMethod.name.asc())
    out = []
    for m in session.scalars(stmt):
        out.append(PaymentMethodRow(
            id=m.id, code=m.code, name=m.name, is_active=bool(m.is_active),
            sort_order=m.sort_order or 0,
        ))
    return out


def get_payment_method(session: Session, method_id: int) -> PaymentMethodRow:
    m = session.get(PaymentMethod, method_id)
    if m is None:
        raise NotFoundError("PaymentMethod", method_id)
    return PaymentMethodRow(
        id=m.id, code=m.code, name=m.name, is_active=bool(m.is_active),
        sort_order=m.sort_order or 0,
    )


# ------------------------------------------------- payments


def list_payments(
    session: Session,
    principal: Principal,
    *,
    invoice_id: int | None = None,
    patient_id: int | None = None,
    method_id: int | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    include_reversed: bool = True,
    limit: int = 500,
) -> list[PaymentRow]:
    if not principal.has(Permission.PAYMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.PAYMENTS_VIEW.value)
    stmt = select(Payment)
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if patient_id is not None:
        stmt = stmt.where(Payment.patient_id == patient_id)
    if method_id is not None:
        stmt = stmt.where(Payment.method_id == method_id)
    if not include_reversed:
        stmt = stmt.where(Payment.reversed_at.is_(None))
    if start is not None:
        stmt = stmt.where(Payment.paid_at >= start)
    if end is not None:
        stmt = stmt.where(Payment.paid_at <= end)
    stmt = stmt.order_by(Payment.paid_at.desc(), Payment.id.desc()).limit(limit)
    return [_row_from(session, p) for p in session.scalars(stmt)]


def get_payment(session: Session, principal: Principal, payment_id: int) -> PaymentRow:
    if not principal.has(Permission.PAYMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.PAYMENTS_VIEW.value)
    p = session.get(Payment, payment_id)
    if p is None:
        raise NotFoundError("Payment", payment_id)
    return _row_from(session, p)


def record_payment(session: Session, principal: Principal, data: PaymentInput) -> Payment:
    """Record a payment against a posted invoice. Accepts overpayments (stores as
    credit — invoice.paid_paisa can exceed total, which surfaces in status as 'paid'
    with due=0)."""
    if not principal.has(Permission.PAYMENTS_CREATE):
        raise PermissionDeniedError(permission=Permission.PAYMENTS_CREATE.value)
    inv = session.get(Invoice, data.invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", data.invoice_id)
    if inv.voided_at is not None:
        raise ValidationError("Cannot accept payment on a voided invoice.", field="invoice_id")
    if not inv.is_posted:
        raise ValidationError("Post the invoice before recording payments.", field="invoice_id")
    method = session.get(PaymentMethod, data.method_id)
    if method is None or not method.is_active:
        raise ValidationError("Selected payment method is not valid.", field="method_id")
    amount = int(data.amount_paisa or 0)
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.", field="amount_paisa")
    p = Payment(
        invoice_id=inv.id,
        patient_id=inv.patient_id,
        method_id=method.id,
        amount_paisa=amount,
        reference_no=(data.reference_no or "").strip(),
        notes=(data.notes or "").strip(),
        paid_at=data.paid_at or local_now(),
        created_by=principal.user_id,
    )
    session.add(p)
    session.flush()
    # Recalculate invoice totals/status.
    from dentiva.services.invoice_service import refresh_invoice_paid
    refresh_invoice_paid(session, inv)
    session.flush()
    # Post income to accounting ledger.
    from dentiva.services import accounting_service
    accounting_service.ensure_default_categories(session)
    accounting_service.record_payment_income(session, principal, p)
    audit_record(
        session, principal, "payment.create",
        entity_type="payment", entity_id=p.id,
        summary=(
            f"Recorded payment of ৳{amount/100:.2f} via {method.name} "
            f"on invoice {inv.invoice_number}."
        ),
    )
    return p


def reverse_payment(
    session: Session, principal: Principal, payment_id: int, reason: str
) -> Payment:
    """Mark a payment as reversed (refunded). Updates invoice totals accordingly."""
    if not principal.has(Permission.PAYMENTS_REFUND):
        raise PermissionDeniedError(permission=Permission.PAYMENTS_REFUND.value)
    p = session.get(Payment, payment_id)
    if p is None:
        raise NotFoundError("Payment", payment_id)
    if p.reversed_at is not None:
        return p
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required to reverse a payment.", field="reason")
    p.reversed_at = local_now()
    p.reversal_reason = reason
    session.flush()
    inv = session.get(Invoice, p.invoice_id)
    if inv is not None:
        from dentiva.services.invoice_service import refresh_invoice_paid
        refresh_invoice_paid(session, inv)
    session.flush()
    # Post contra income entry.
    from dentiva.services import accounting_service
    accounting_service.ensure_default_categories(session)
    accounting_service.record_payment_reversal(session, principal, p)
    audit_record(
        session, principal, "payment.reverse",
        entity_type="payment", entity_id=p.id,
        summary=f"Reversed payment #{p.id} (৳{p.amount_paisa/100:.2f}): {reason}",
    )
    return p


# ------------------------------------------------- helpers


def _row_from(session: Session, p: Payment) -> PaymentRow:
    inv = session.get(Invoice, p.invoice_id)
    inv_no = inv.invoice_number if inv is not None else "(deleted)"
    pat = session.get(Patient, p.patient_id)
    pname = pat.name if pat is not None else "(deleted)"
    method = session.get(PaymentMethod, p.method_id)
    mcode = method.code if method is not None else "?"
    mname = method.name if method is not None else "(deleted)"
    return PaymentRow(
        id=p.id, invoice_id=p.invoice_id, invoice_number=inv_no,
        patient_id=p.patient_id, patient_name=pname, method_id=p.method_id,
        method_code=mcode, method_name=mname, amount_paisa=p.amount_paisa or 0,
        reference_no=p.reference_no or "", notes=p.notes or "",
        paid_at=p.paid_at, reversed_at=p.reversed_at,
        reversal_reason=p.reversal_reason or "", created_by=p.created_by,
    )
