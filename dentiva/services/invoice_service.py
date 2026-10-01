"""Invoice service — draft, line items, post (immutable), void, list, totals.

Invoices follow the "post-to-lock" convention shared with prescriptions:
- A draft invoice can be edited freely (add/remove lines, change discount/tax).
- Once posted (`is_posted=True`) it is immutable. New payments can be attached;
  lines/amounts cannot change. Voiding replaces cancellation and requires a reason.

Line items have price snapshots of their own (unit_price_paisa copied from the
treatment catalog or custom at creation) so even if the catalog changes later,
historical invoices are preserved. Line items can reference a treatment_record
or treatment_catalog (item_type = treatment / catalog / custom) but always carry
their own description and unit_price for audit purposes.

Invoice numbers are generated as INV-YYYYMMDD-NNNN (zero-padded, per calendar day).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import (
    Dentist,
    Invoice,
    InvoiceLineItem,
    Patient,
    Payment,
    TreatmentCatalog,
    TreatmentRecord,
    Visit,
)
from dentiva.services.audit_service import record as audit_record

INVOICE_STATUSES = ("draft", "unpaid", "partial", "paid", "void")
LINE_TYPES = ("treatment", "catalog", "custom")


# ------------------------------------------------------------------------- DTOs


@dataclass
class InvoiceLineInput:
    item_type: str = "custom"
    reference_id: int | None = None
    description: str = ""
    quantity: int = 1
    unit_price_paisa: int = 0
    discount_paisa: int = 0


@dataclass
class InvoiceLineRow:
    id: int
    item_type: str
    reference_id: int | None
    description: str
    quantity: int
    unit_price_paisa: int
    discount_paisa: int
    line_total_paisa: int


@dataclass
class InvoiceInput:
    patient_id: int | None = None
    visit_id: int | None = None
    dentist_id: int | None = None
    date: dt.datetime | None = None
    discount_paisa: int = 0
    tax_paisa: int = 0
    notes: str = ""
    lines: list[InvoiceLineInput] = field(default_factory=list)


@dataclass
class InvoiceRow:
    id: int
    invoice_number: str
    patient_id: int
    patient_name: str
    dentist_id: int | None
    dentist_name: str
    visit_id: int | None
    date: dt.datetime
    subtotal_paisa: int
    discount_paisa: int
    tax_paisa: int
    total_paisa: int
    paid_paisa: int
    due_paisa: int
    status: str
    notes: str
    is_posted: bool
    posted_at: dt.datetime | None
    voided_at: dt.datetime | None
    void_reason: str
    lines: list[InvoiceLineRow]


# ------------------------------------------------------------------------- list / get


def list_invoices(
    session: Session,
    principal: Principal,
    *,
    patient_id: int | None = None,
    visit_id: int | None = None,
    status: str | None = None,
    posted_only: bool = False,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int = 500,
) -> list[InvoiceRow]:
    if not principal.has(Permission.INVOICES_VIEW):
        raise PermissionDeniedError(permission=Permission.INVOICES_VIEW.value)
    stmt = select(Invoice)
    if patient_id is not None:
        stmt = stmt.where(Invoice.patient_id == patient_id)
    if visit_id is not None:
        stmt = stmt.where(Invoice.visit_id == visit_id)
    if status:
        if status not in INVOICE_STATUSES:
            raise ValidationError(f"Invalid status '{status}'.", field="status")
        stmt = stmt.where(Invoice.status == status)
    if posted_only:
        stmt = stmt.where(Invoice.is_posted.is_(True))
    if start is not None:
        stmt = stmt.where(Invoice.date >= start)
    if end is not None:
        stmt = stmt.where(Invoice.date <= end)
    stmt = stmt.order_by(Invoice.date.desc(), Invoice.id.desc()).limit(limit)

    rows: list[InvoiceRow] = []
    for inv in session.scalars(stmt):
        rows.append(_row_from(session, inv))
    return rows


def get_invoice(session: Session, principal: Principal, invoice_id: int) -> InvoiceRow:
    if not principal.has(Permission.INVOICES_VIEW):
        raise PermissionDeniedError(permission=Permission.INVOICES_VIEW.value)
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", invoice_id)
    return _row_from(session, inv)


def get_invoice_by_number(session: Session, principal: Principal, number: str) -> InvoiceRow:
    if not principal.has(Permission.INVOICES_VIEW):
        raise PermissionDeniedError(permission=Permission.INVOICES_VIEW.value)
    inv = session.scalar(select(Invoice).where(Invoice.invoice_number == number))
    if inv is None:
        raise NotFoundError("Invoice", number)
    return _row_from(session, inv)


# ------------------------------------------------------------------------- create / update


def create_invoice(session: Session, principal: Principal, data: InvoiceInput) -> Invoice:
    if not principal.has(Permission.INVOICES_CREATE):
        raise PermissionDeniedError(permission=Permission.INVOICES_CREATE.value)
    pid, did, vid = _resolve_links(session, data)
    inv = Invoice(
        invoice_number=_next_invoice_number(session),
        patient_id=pid,
        dentist_id=did,
        visit_id=vid,
        date=data.date or local_now(),
        discount_paisa=max(0, int(data.discount_paisa)),
        tax_paisa=max(0, int(data.tax_paisa)),
        notes=(data.notes or "").strip(),
        status="draft",
        is_posted=False,
        created_by=principal.user_id,
    )
    session.add(inv)
    session.flush()
    _set_lines(session, inv.id, data.lines)
    _recalc_totals(session, inv)
    audit_record(
        session, principal, "invoice.create",
        entity_type="invoice", entity_id=inv.id,
        summary=f"Drafted invoice {inv.invoice_number}.",
    )
    return inv


def update_invoice(session: Session, principal: Principal, invoice_id: int, data: InvoiceInput) -> Invoice:
    if not principal.has(Permission.INVOICES_EDIT):
        raise PermissionDeniedError(permission=Permission.INVOICES_EDIT.value)
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", invoice_id)
    if inv.is_posted:
        raise ValidationError("Posted invoices cannot be edited. Void and re-create if needed.", field="is_posted")
    if inv.voided_at is not None:
        raise ValidationError("Voided invoices cannot be edited.", field="status")
    if data.patient_id is not None and data.patient_id != inv.patient_id:
        p = session.get(Patient, data.patient_id)
        if p is None or p.deleted_at is not None:
            raise ValidationError("Selected patient does not exist.", field="patient_id")
        inv.patient_id = data.patient_id
    if data.visit_id is not None and data.visit_id != inv.visit_id:
        v = session.get(Visit, data.visit_id)
        if v is None:
            raise ValidationError("Visit does not exist.", field="visit_id")
        inv.visit_id = data.visit_id
        if inv.dentist_id is None:
            inv.dentist_id = v.dentist_id
    if data.dentist_id != inv.dentist_id:
        if data.dentist_id is not None:
            d = session.get(Dentist, data.dentist_id)
            if d is None or d.deleted_at is not None:
                raise ValidationError("Selected dentist does not exist.", field="dentist_id")
        inv.dentist_id = data.dentist_id
    inv.discount_paisa = max(0, int(data.discount_paisa))
    inv.tax_paisa = max(0, int(data.tax_paisa))
    inv.notes = (data.notes or "").strip()
    _set_lines(session, inv.id, data.lines)
    _recalc_totals(session, inv)
    audit_record(
        session, principal, "invoice.update",
        entity_type="invoice", entity_id=inv.id,
        summary=f"Updated draft invoice {inv.invoice_number}.",
    )
    return inv


def create_invoice_from_visit(
    session: Session, principal: Principal, visit_id: int,
    *,
    discount_paisa: int = 0,
    tax_paisa: int = 0,
    notes: str = "",
    auto_post: bool = False,
) -> Invoice:
    """Create an invoice from a visit's treatment records (price snapshots taken)."""
    if not principal.has(Permission.INVOICES_CREATE):
        raise PermissionDeniedError(permission=Permission.INVOICES_CREATE.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    treatments = session.scalars(
        select(TreatmentRecord).where(TreatmentRecord.visit_id == visit_id).order_by(TreatmentRecord.id.asc())
    ).all()
    if not treatments:
        raise ValidationError("Cannot create an invoice from a visit with no treatment records.", field="visit_id")
    lines: list[InvoiceLineInput] = []
    for t in treatments:
        tooth = f" ({t.tooth_codes})" if t.tooth_codes else ""
        lines.append(InvoiceLineInput(
            item_type="treatment",
            reference_id=t.id,
            description=t.name_at_service_time + tooth,
            quantity=1,
            unit_price_paisa=t.price_paisa,
        ))
    inv = create_invoice(session, principal, InvoiceInput(
        patient_id=v.patient_id,
        visit_id=visit_id,
        dentist_id=v.dentist_id,
        discount_paisa=discount_paisa,
        tax_paisa=tax_paisa,
        notes=notes,
        lines=lines,
    ))
    if auto_post:
        inv = post_invoice(session, principal, inv.id)
    return inv


def post_invoice(session: Session, principal: Principal, invoice_id: int) -> Invoice:
    """Finalize / post a draft invoice. Lines/totals become immutable after posting."""
    if not principal.has(Permission.INVOICES_EDIT):
        raise PermissionDeniedError(permission=Permission.INVOICES_EDIT.value)
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", invoice_id)
    if inv.voided_at is not None:
        raise ValidationError("Cannot post a voided invoice.", field="status")
    if inv.is_posted:
        return inv
    line_count = session.scalar(
        select(func.count(InvoiceLineItem.id)).where(InvoiceLineItem.invoice_id == invoice_id)
    ) or 0
    if line_count == 0:
        raise ValidationError("Add at least one line item before posting.")
    _recalc_totals(session, inv)
    inv.is_posted = True
    inv.posted_at = local_now()
    inv.status = _derive_status(inv.total_paisa, inv.paid_paisa)
    session.flush()
    audit_record(
        session, principal, "invoice.post",
        entity_type="invoice", entity_id=inv.id,
        summary=f"Posted invoice {inv.invoice_number} (total ৳{inv.total_paisa / 100:.2f}).",
    )
    return inv


def void_invoice(session: Session, principal: Principal, invoice_id: int, reason: str) -> Invoice:
    """Void a posted (or draft) invoice. Must include a reason. Reverses no payments
    automatically — refund/reverse payments explicitly."""
    if not principal.has(Permission.INVOICES_VOID):
        raise PermissionDeniedError(permission=Permission.INVOICES_VOID.value)
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", invoice_id)
    if inv.voided_at is not None:
        return inv
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required to void an invoice.", field="reason")
    inv.voided_at = local_now()
    inv.void_reason = reason
    inv.status = "void"
    session.flush()
    audit_record(
        session, principal, "invoice.void",
        entity_type="invoice", entity_id=inv.id,
        summary=f"Voided invoice {inv.invoice_number}: {reason}",
    )
    return inv


def delete_invoice(session: Session, principal: Principal, invoice_id: int) -> None:
    """Delete a draft invoice (not posted, not voided — hard delete for drafts only)."""
    if not principal.has(Permission.INVOICES_EDIT):
        raise PermissionDeniedError(permission=Permission.INVOICES_EDIT.value)
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice", invoice_id)
    if inv.is_posted:
        raise ValidationError("Posted invoices cannot be deleted — void them instead.", field="is_posted")
    number = inv.invoice_number
    session.delete(inv)
    session.flush()
    audit_record(
        session, principal, "invoice.delete",
        entity_type="invoice", entity_id=invoice_id,
        summary=f"Deleted draft invoice {number}.",
    )


# ------------------------------------------------------------------------- helpers


def invoice_paid_total(session: Session, invoice_id: int) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_paisa), 0))
            .where(Payment.invoice_id == invoice_id, Payment.reversed_at.is_(None))
        )
        or 0
    )


def refresh_invoice_paid(session: Session, invoice: Invoice) -> None:
    """Recompute paid_paisa / due_paisa / status from the payments table."""
    paid = invoice_paid_total(session, invoice.id)
    invoice.paid_paisa = paid
    invoice.due_paisa = max(0, invoice.total_paisa - paid)
    if invoice.voided_at is not None:
        invoice.status = "void"
    elif not invoice.is_posted:
        invoice.status = "draft"
    else:
        invoice.status = _derive_status(invoice.total_paisa, paid)
    # Overpaid? Treat as paid (no negative due).
    if paid >= invoice.total_paisa and invoice.is_posted:
        invoice.due_paisa = max(0, invoice.total_paisa - paid)
        invoice.status = "paid"


def _derive_status(total: int, paid: int) -> str:
    if paid <= 0:
        return "unpaid"
    if paid >= total:
        return "paid"
    return "partial"


def _next_invoice_number(session: Session) -> str:
    today = local_now().date()
    prefix = f"INV-{today.strftime('%Y%m%d')}-"
    # Find today's last suffix, treat missing/non-numeric as 0.
    like = prefix + "%"
    existing = session.scalars(select(Invoice).where(Invoice.invoice_number.like(like))).all()
    max_n = 0
    for inv in existing:
        suffix = inv.invoice_number[len(prefix):]
        try:
            n = int(suffix)
            if n > max_n:
                max_n = n
        except ValueError:
            continue
    return f"{prefix}{max_n + 1:04d}"


def _resolve_links(session: Session, data: InvoiceInput) -> tuple[int, int | None, int | None]:
    pid = data.patient_id
    vid = data.visit_id
    if pid is None and vid is not None:
        v = session.get(Visit, vid)
        if v is None:
            raise ValidationError("Visit does not exist.", field="visit_id")
        pid = v.patient_id
    if pid is None:
        raise ValidationError("Patient is required.", field="patient_id")
    p = session.get(Patient, pid)
    if p is None or p.deleted_at is not None:
        raise ValidationError("Selected patient does not exist.", field="patient_id")
    did = data.dentist_id
    if vid is not None:
        v = session.get(Visit, vid)
        if v is None:
            raise ValidationError("Visit does not exist.", field="visit_id")
        if did is None:
            did = v.dentist_id
    if did is not None:
        d = session.get(Dentist, did)
        if d is None or d.deleted_at is not None:
            raise ValidationError("Selected dentist does not exist.", field="dentist_id")
    return pid, did, vid


def _set_lines(session: Session, invoice_id: int, lines: list[InvoiceLineInput]) -> None:
    session.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id == invoice_id).delete()
    session.flush()
    for _i, line in enumerate(lines):
        desc = (line.description or "").strip()
        itype = (line.item_type or "custom").strip().lower()
        if itype not in LINE_TYPES:
            itype = "custom"
        qty = max(1, int(line.quantity or 1))
        unit = int(line.unit_price_paisa or 0)
        if unit < 0:
            raise ValidationError("Unit price cannot be negative.", field="unit_price_paisa")
        line_disc = max(0, int(line.discount_paisa or 0))
        # Auto-fill price/desc from reference if not supplied
        if itype == "treatment" and line.reference_id is not None and (not desc or not unit):
            rec = session.get(TreatmentRecord, line.reference_id)
            if rec is not None:
                if not desc:
                    tooth = f" ({rec.tooth_codes})" if rec.tooth_codes else ""
                    desc = rec.name_at_service_time + tooth
                if not unit:
                    unit = rec.price_paisa
        elif itype == "catalog" and line.reference_id is not None and (not desc or not unit):
            cat = session.get(TreatmentCatalog, line.reference_id)
            if cat is not None:
                if not desc:
                    desc = cat.name
                if not unit:
                    unit = cat.default_price_paisa
        if not desc:
            raise ValidationError("Each invoice line must have a description.", field="description")
        line_total = max(0, unit * qty - line_disc)
        session.add(InvoiceLineItem(
            invoice_id=invoice_id,
            item_type=itype,
            reference_id=line.reference_id,
            description=desc,
            quantity=qty,
            unit_price_paisa=unit,
            discount_paisa=line_disc,
            line_total_paisa=line_total,
        ))
    session.flush()


def _recalc_totals(session: Session, inv: Invoice) -> None:
    lines_sum = session.scalar(
        select(func.coalesce(func.sum(InvoiceLineItem.line_total_paisa), 0))
        .where(InvoiceLineItem.invoice_id == inv.id)
    ) or 0
    inv.subtotal_paisa = int(lines_sum)
    inv.discount_paisa = max(0, int(inv.discount_paisa))
    inv.tax_paisa = max(0, int(inv.tax_paisa))
    inv.total_paisa = max(0, inv.subtotal_paisa - inv.discount_paisa + inv.tax_paisa)
    refresh_invoice_paid(session, inv)


def _row_from(session: Session, inv: Invoice) -> InvoiceRow:
    lines = session.scalars(
        select(InvoiceLineItem)
        .where(InvoiceLineItem.invoice_id == inv.id)
        .order_by(InvoiceLineItem.id.asc())
    ).all()
    line_rows = [
        InvoiceLineRow(
            id=li.id, item_type=li.item_type, reference_id=li.reference_id,
            description=li.description, quantity=li.quantity or 1,
            unit_price_paisa=li.unit_price_paisa or 0, discount_paisa=li.discount_paisa or 0,
            line_total_paisa=li.line_total_paisa or 0,
        )
        for li in lines
    ]
    p = session.get(Patient, inv.patient_id)
    pname = p.name if p is not None else "(deleted)"
    dname = "—"
    if inv.dentist_id is not None:
        d = session.get(Dentist, inv.dentist_id)
        dname = d.name if d is not None else "(deleted)"
    return InvoiceRow(
        id=inv.id, invoice_number=inv.invoice_number, patient_id=inv.patient_id,
        patient_name=pname, dentist_id=inv.dentist_id, dentist_name=dname,
        visit_id=inv.visit_id, date=inv.date, subtotal_paisa=inv.subtotal_paisa or 0,
        discount_paisa=inv.discount_paisa or 0, tax_paisa=inv.tax_paisa or 0,
        total_paisa=inv.total_paisa or 0, paid_paisa=inv.paid_paisa or 0,
        due_paisa=inv.due_paisa or 0, status=inv.status, notes=inv.notes or "",
        is_posted=bool(inv.is_posted), posted_at=inv.posted_at,
        voided_at=inv.voided_at, void_reason=inv.void_reason or "",
        lines=line_rows,
    )
