# mypy: disable-error-code="arg-type, union-attr, assignment"
"""Accounting service — chart of accounts (categories), manual journal entries,
income auto-generated from payments, and period reports.

Auto-posting design:
  * When a payment is created (posted), an income accounting entry is generated
    automatically with the default income category; voiding/reversing a payment
    does NOT hard-delete entries but writes a contra income entry (negative) so
    the ledger remains immutable.
  * Manual entries are free-form income/expense items (rent, utilities, supplies
    purchased outside the inventory workflow, sundry income).
  * All entries have a `source` discriminator: "manual" | "payment" | "payment_reversal"
    (future: "inventory_purchase", "payroll"). This lets the reports distinguish
    clinical income from ad-hoc income without losing entries when payments are
    reversed.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.dates import today as local_today
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import (
    AccountingCategory,
    AccountingEntry,
    PaymentMethod,
)
from dentiva.services.audit_service import record as audit_record

DEFAULT_INCOME_CATEGORIES: tuple[str, ...] = (
    "Consultation fees",
    "Restorative",
    "Endodontics (RCT)",
    "Prosthodontics (crowns/bridges/dentures)",
    "Orthodontics",
    "Oral surgery / extractions",
    "Scaling & prophylaxis",
    "Whitening / cosmetic",
    "Imaging / X-ray",
    "Other clinical income",
)
DEFAULT_EXPENSE_CATEGORIES: tuple[str, ...] = (
    "Rent",
    "Utilities (electricity/water/gas/internet)",
    "Staff salaries",
    "Dental supplies & consumables",
    "Lab fees",
    "Equipment purchase/maintenance",
    "Marketing & advertising",
    "Taxes & compliance",
    "Miscellaneous",
)

SOURCE_MANUAL = "manual"
SOURCE_PAYMENT = "payment"
SOURCE_PAYMENT_REVERSAL = "payment_reversal"


# ------------------------------------------------------------------------- DTOs


@dataclass
class CategoryRow:
    id: int
    name: str
    kind: str  # "income" | "expense"
    parent_id: int | None
    parent_name: str
    is_active: bool


@dataclass
class CategoryInput:
    name: str = ""
    kind: str = "expense"
    parent_id: int | None = None
    is_active: bool = True


@dataclass
class EntryRow:
    id: int
    date: dt.date
    category_id: int
    category_name: str
    kind: str
    amount_paisa: int
    signed_paisa: int  # +income, -expense for summing
    payment_method_id: int | None
    payment_method: str
    source: str
    reference: str
    description: str
    related_invoice_id: int | None
    related_payment_id: int | None
    created_by_name: str
    created_at: dt.datetime


@dataclass
class EntryInput:
    date: dt.date | None = None
    category_id: int | None = None
    kind: str = "expense"
    amount_paisa: int = 0
    payment_method_id: int | None = None
    reference: str = ""
    description: str = ""


@dataclass
class PeriodTotals:
    start_date: dt.date
    end_date: dt.date
    income_paisa: int = 0
    expense_paisa: int = 0
    receivable_added_paisa: int = 0  # from invoices posted in period
    receivable_paid_paisa: int = 0   # from payments in period
    by_category_income: list[tuple[str, int]] = field(default_factory=list)
    by_category_expense: list[tuple[str, int]] = field(default_factory=list)
    by_method_income: list[tuple[str, int]] = field(default_factory=list)
    daily_net: list[tuple[dt.date, int, int, int]] = field(default_factory=list)  # date, income, expense, net
    profit_paisa: int = 0


# ------------------------------------------------------------------------- categories


def ensure_default_categories(session: Session) -> None:
    """Idempotently create default accounting categories. Safe to call on every
    startup and on first run."""
    for name in DEFAULT_INCOME_CATEGORIES:
        _ensure_cat(session, name, "income")
    for name in DEFAULT_EXPENSE_CATEGORIES:
        _ensure_cat(session, name, "expense")


def _ensure_cat(session: Session, name: str, kind: str) -> AccountingCategory:
    existing = session.scalar(
        select(AccountingCategory).where(
            func.lower(AccountingCategory.name) == name.lower(),
            AccountingCategory.kind == kind,
        )
    )
    if existing is not None:
        return existing
    cat = AccountingCategory(name=name, kind=kind, is_active=True)
    session.add(cat)
    session.flush()
    return cat


def default_income_category(session: Session) -> AccountingCategory:
    return _ensure_cat(session, "Other clinical income", "income")


def list_categories(
    session: Session, principal: Principal, *, kind: str | None = None, active_only: bool = False
) -> list[CategoryRow]:
    if not principal.has(Permission.ACCOUNTING_VIEW):
        raise PermissionDeniedError(permission=Permission.ACCOUNTING_VIEW.value)
    stmt = select(AccountingCategory)
    if kind in ("income", "expense"):
        stmt = stmt.where(AccountingCategory.kind == kind)
    if active_only:
        stmt = stmt.where(AccountingCategory.is_active.is_(True))
    stmt = stmt.order_by(AccountingCategory.kind.asc(), AccountingCategory.name.asc())
    cats = list(session.scalars(stmt))
    names = {c.id: c.name for c in cats}
    return [
        CategoryRow(
            id=c.id, name=c.name, kind=c.kind, parent_id=c.parent_id,
            parent_name=names.get(c.parent_id, "") if c.parent_id else "",
            is_active=bool(c.is_active),
        )
        for c in cats
    ]


def create_category(session: Session, principal: Principal, data: CategoryInput) -> AccountingCategory:
    if not principal.has(Permission.ACCOUNTING_MANAGE):
        raise PermissionDeniedError(permission=Permission.ACCOUNTING_MANAGE.value)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Category name is required.", field="name")
    if data.kind not in ("income", "expense"):
        raise ValidationError("Kind must be 'income' or 'expense'.", field="kind")
    if data.parent_id is not None:
        parent = session.get(AccountingCategory, data.parent_id)
        if parent is None or parent.kind != data.kind:
            raise ValidationError("Parent category must be of the same kind.", field="parent_id")
    dup = session.scalar(
        select(AccountingCategory).where(
            func.lower(AccountingCategory.name) == name.lower(),
            AccountingCategory.kind == data.kind,
        )
    )
    if dup is not None:
        raise ValidationError(f"A {data.kind} category named '{name}' already exists.", field="name")
    cat = AccountingCategory(name=name, kind=data.kind, parent_id=data.parent_id, is_active=bool(data.is_active))
    session.add(cat)
    session.flush()
    audit_record(session, principal, f"accounting.category.create.{data.kind}",
                 entity_type="accounting_category", entity_id=cat.id,
                 summary=f"Added {data.kind} category '{name}'.")
    return cat


# ------------------------------------------------------------------------- entries (manual)


def list_entries(
    session: Session,
    principal: Principal,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    kind: str | None = None,
    category_id: int | None = None,
    limit: int = 500,
) -> list[EntryRow]:
    if not principal.has(Permission.ACCOUNTING_VIEW):
        raise PermissionDeniedError(permission=Permission.ACCOUNTING_VIEW.value)
    from dentiva.models import User
    stmt = (
        select(AccountingEntry)
        .order_by(AccountingEntry.date.desc(), AccountingEntry.id.desc())
        .limit(limit)
    )
    if start is not None:
        stmt = stmt.where(AccountingEntry.date >= start)
    if end is not None:
        stmt = stmt.where(AccountingEntry.date <= end)
    if kind in ("income", "expense"):
        stmt = stmt.where(AccountingEntry.kind == kind)
    if category_id is not None:
        stmt = stmt.where(AccountingEntry.category_id == category_id)
    rows = list(session.scalars(stmt))
    cat_ids = {e.category_id for e in rows}
    pm_ids = {e.payment_method_id for e in rows if e.payment_method_id}
    u_ids = {e.created_by for e in rows if e.created_by}
    cat_names: dict[int, str] = {}
    pm_names: dict[int, str] = {}
    u_names: dict[int, str] = {}
    if cat_ids:
        for c in session.scalars(select(AccountingCategory).where(AccountingCategory.id.in_(cat_ids))):
            cat_names[c.id] = c.name
    if pm_ids:
        for p in session.scalars(select(PaymentMethod).where(PaymentMethod.id.in_(pm_ids))):
            pm_names[p.id] = p.name
    if u_ids:
        for u in session.scalars(select(User).where(User.id.in_(u_ids))):
            u_names[u.id] = u.display_name
    # Inject a synthetic "source" field via reference parsing? We don't have it
    # as a column. Use description prefix or just infer: if related_payment_id
    # is set, source is payment/reversal based on amount sign.
    out: list[EntryRow] = []
    for e in rows:
        signed = e.amount_paisa if e.kind == "income" else -e.amount_paisa
        if e.related_payment_id is not None:
            source = SOURCE_PAYMENT_REVERSAL if e.amount_paisa < 0 else SOURCE_PAYMENT
            # Wait, payment entries always have income kind; reversal has negative amount? We store
            # kind='income' for reversals too but amount_paisa negative. So:
            if e.amount_paisa < 0:
                source = SOURCE_PAYMENT_REVERSAL
                signed = e.amount_paisa  # negative already
            else:
                source = SOURCE_PAYMENT
                signed = e.amount_paisa
        else:
            source = SOURCE_MANUAL
        out.append(EntryRow(
            id=e.id, date=e.date, category_id=e.category_id,
            category_name=cat_names.get(e.category_id, f"#{e.category_id}"),
            kind=e.kind, amount_paisa=abs(e.amount_paisa), signed_paisa=signed,
            payment_method_id=e.payment_method_id,
            payment_method=pm_names.get(e.payment_method_id, "") if e.payment_method_id else "",
            source=source, reference=e.reference or "", description=e.description or "",
            related_invoice_id=e.related_invoice_id, related_payment_id=e.related_payment_id,
            created_by_name=u_names.get(e.created_by, "") if e.created_by else "",
            created_at=e.created_at,
        ))
    return out


def create_entry(session: Session, principal: Principal, data: EntryInput) -> AccountingEntry:
    if not principal.has(Permission.ACCOUNTING_MANAGE):
        raise PermissionDeniedError(permission=Permission.ACCOUNTING_MANAGE.value)
    if data.kind not in ("income", "expense"):
        raise ValidationError("Kind must be 'income' or 'expense'.", field="kind")
    amount = int(data.amount_paisa)
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero.", field="amount_paisa")
    cat = session.get(AccountingCategory, data.category_id) if data.category_id else None
    if cat is None:
        raise ValidationError("Category is required.", field="category_id")
    if cat.kind != data.kind:
        raise ValidationError(f"Selected category is not a {data.kind} category.", field="category_id")
    if data.payment_method_id is not None and session.get(PaymentMethod, data.payment_method_id) is None:
        raise ValidationError("Selected payment method does not exist.", field="payment_method_id")
    date = data.date or local_today()
    e = AccountingEntry(
        date=date, category_id=cat.id, kind=data.kind, amount_paisa=amount,
        payment_method_id=data.payment_method_id,
        reference=(data.reference or "").strip(), description=(data.description or "").strip(),
        created_by=principal.user_id,
    )
    session.add(e)
    session.flush()
    audit_record(session, principal, f"accounting.entry.create.{data.kind}",
                 entity_type="accounting_entry", entity_id=e.id,
                 summary=f"Added {data.kind} entry: ৳{amount / 100:.2f} ({cat.name}).")
    return e


# ------------------------------------------------------------------------- auto-posting from payments


def record_payment_income(session: Session, principal: Principal, payment, category_id: int | None = None) -> AccountingEntry:
    """Create an income entry for a posted payment. Called by payment_service on create."""
    if category_id is None:
        cat = default_income_category(session)
        category_id = cat.id
    paid_dt = getattr(payment, "paid_at", None) or local_now()
    e = AccountingEntry(
        date=paid_dt.date(),
        category_id=category_id,
        kind="income",
        amount_paisa=payment.amount_paisa,
        payment_method_id=getattr(payment, "method_id", None),
        reference=f"Payment #{payment.id}",
        description=f"Payment for invoice #{getattr(payment, 'invoice_id', '')}",
        related_invoice_id=getattr(payment, "invoice_id", None),
        related_payment_id=payment.id,
        created_by=principal.user_id,
    )
    session.add(e)
    session.flush()
    return e


def record_payment_reversal(session: Session, principal: Principal, payment) -> AccountingEntry:
    """Create a contra (negative) income entry when a payment is reversed."""
    existing = session.scalar(
        select(AccountingEntry).where(AccountingEntry.related_payment_id == payment.id)
    )
    cat_id = existing.category_id if existing is not None else default_income_category(session).id
    e = AccountingEntry(
        date=local_today(),
        category_id=cat_id,
        kind="income",
        amount_paisa=-payment.amount_paisa,
        payment_method_id=getattr(payment, "method_id", None),
        reference=f"Reversal of payment #{payment.id}",
        description=f"Payment reversed for invoice #{getattr(payment, 'invoice_id', '')}",
        related_invoice_id=getattr(payment, "invoice_id", None),
        related_payment_id=payment.id,
        created_by=principal.user_id,
    )
    session.add(e)
    session.flush()
    return e


# ------------------------------------------------------------------------- reports


def period_totals(
    session: Session, principal: Principal, *, start: dt.date, end: dt.date
) -> PeriodTotals:
    if not principal.has(Permission.ACCOUNTING_VIEW):
        raise PermissionDeniedError(permission=Permission.ACCOUNTING_VIEW.value)
    if end < start:
        raise ValidationError("End date must be on or after start date.")

    # Sum entries
    rows = list(session.scalars(
        select(AccountingEntry)
        .where(AccountingEntry.date >= start, AccountingEntry.date <= end)
    ))
    income = 0
    expense = 0
    by_cat_inc: dict[int, int] = {}
    by_cat_exp: dict[int, int] = {}
    by_method: dict[int, int] = {}
    daily_inc: dict[dt.date, int] = {}
    daily_exp: dict[dt.date, int] = {}
    for e in rows:
        # Income entries can have negative amount_paisa (reversals). Expense entries are positive.
        if e.kind == "income":
            signed = e.amount_paisa  # already signed (+income, -reversal)
            if e.category_id is not None:
                by_cat_inc[e.category_id] = by_cat_inc.get(e.category_id, 0) + signed
            if e.payment_method_id is not None:
                by_method[e.payment_method_id] = by_method.get(e.payment_method_id, 0) + signed
            income += signed
            daily_inc[e.date] = daily_inc.get(e.date, 0) + signed
        else:
            expense += e.amount_paisa
            if e.category_id is not None:
                by_cat_exp[e.category_id] = by_cat_exp.get(e.category_id, 0) + e.amount_paisa
            daily_exp[e.date] = daily_exp.get(e.date, 0) + e.amount_paisa

    # Resolve names
    all_cat_ids = set(by_cat_inc) | set(by_cat_exp)
    cat_names: dict[int, str] = {}
    if all_cat_ids:
        for c in session.scalars(select(AccountingCategory).where(AccountingCategory.id.in_(all_cat_ids))):
            cat_names[c.id] = c.name
    pm_names: dict[int, str] = {}
    if by_method:
        for p in session.scalars(select(PaymentMethod).where(PaymentMethod.id.in_(set(by_method)))):
            pm_names[p.id] = p.name

    # Daily net list
    all_dates = sorted(set(daily_inc) | set(daily_exp))
    daily_net = [
        (d, daily_inc.get(d, 0), daily_exp.get(d, 0), daily_inc.get(d, 0) - daily_exp.get(d, 0))
        for d in all_dates
    ]

    # TODO: receivable_added / receivable_paid require invoice/payment joins;
    # we approximate here with what's already in accounting entries (payments
    # are auto-posted). A more precise figure would join Invoice.posted_at.
    receivable_paid = income  # includes reversals (signed)
    receivable_added = 0
    from dentiva.models import Invoice
    inv_rows = session.execute(
        select(func.coalesce(func.sum(Invoice.total_paisa), 0))
        .where(Invoice.is_posted.is_(True), Invoice.voided_at.is_(None))
        .where(Invoice.posted_at.is_not(None))
        .where(func.date(Invoice.posted_at) >= start, func.date(Invoice.posted_at) <= end)
    ).scalar() or 0
    receivable_added = int(inv_rows or 0)

    return PeriodTotals(
        start_date=start, end_date=end,
        income_paisa=income, expense_paisa=expense,
        receivable_added_paisa=receivable_added, receivable_paid_paisa=receivable_paid,
        by_category_income=sorted(
            [(cat_names.get(cid, f"#{cid}"), v) for cid, v in by_cat_inc.items() if v != 0],
            key=lambda x: -x[1],
        ),
        by_category_expense=sorted(
            [(cat_names.get(cid, f"#{cid}"), v) for cid, v in by_cat_exp.items() if v != 0],
            key=lambda x: -x[1],
        ),
        by_method_income=sorted(
            [(pm_names.get(pid, f"#{pid}"), v) for pid, v in by_method.items() if v != 0],
            key=lambda x: -x[1],
        ),
        daily_net=daily_net,
        profit_paisa=income - expense,
    )
