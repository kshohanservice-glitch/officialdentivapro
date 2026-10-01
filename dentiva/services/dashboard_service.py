"""Dashboard aggregates and global search queries.

All functions accept the current :class:`Principal` and enforce RBAC at the
service layer: tiles or search results a user is not allowed to see are
omitted from the response (never raise, since the dashboard/search surfaces
are shared and should degrade gracefully per-role).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from dentiva.core.dates import end_of_day, local_now, start_of_day
from dentiva.core.money import format_bdt
from dentiva.core.permissions import Permission, Principal
from dentiva.models import (
    Appointment,
    ClinicProfile,
    Dentist,
    InventoryItem,
    Invoice,
    Notification,
    Patient,
    Payment,
    QueueEntry,
)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@dataclass
class ApptRow:
    id: int
    time_str: str
    patient_name: str
    patient_phone: str
    dentist_name: str
    reason: str
    status: str


@dataclass
class AlertRow:
    kind: str
    title: str
    detail: str


@dataclass
class DashboardData:
    clinic_name: str = ""
    today_appointments: int = 0
    checked_in: int = 0
    waiting_queue: int = 0
    todays_revenue_paisa: int = 0
    pending_invoices_count: int = 0
    pending_invoices_total_paisa: int = 0
    low_stock_count: int = 0
    upcoming: list[ApptRow] = field(default_factory=list)
    alerts: list[AlertRow] = field(default_factory=list)

    @property
    def todays_revenue_display(self) -> str:
        return format_bdt(self.todays_revenue_paisa)

    @property
    def pending_invoices_total_display(self) -> str:
        return format_bdt(self.pending_invoices_total_paisa)


def _time_fmt(d: dt.datetime | None) -> str:
    if d is None:
        return ""
    return d.strftime("%I:%M %p").lstrip("0")


def load_dashboard(session: Session, principal: Principal) -> DashboardData:
    """Return dashboard aggregates filtered by principal permissions."""
    data = DashboardData()

    # Clinic name (visible to everyone)
    cp = session.scalar(select(ClinicProfile).limit(1))
    if cp is not None:
        data.clinic_name = cp.name or ""

    now = local_now()
    today_start = start_of_day(now)
    today_end = end_of_day(now)

    can_view_appts = principal.has(Permission.APPOINTMENTS_VIEW)
    can_view_queue = principal.has(Permission.QUEUE_MANAGE)
    can_view_invoices = principal.has(Permission.INVOICES_VIEW)
    can_view_payments = principal.has(Permission.PAYMENTS_VIEW)
    can_view_inventory = principal.has(Permission.INVENTORY_VIEW)
    can_view_patients = principal.has(Permission.PATIENTS_VIEW)

    # Today's appointments
    if can_view_appts:
        data.today_appointments = session.scalar(
            select(func.count(Appointment.id)).where(
                Appointment.scheduled_at >= today_start,
                Appointment.scheduled_at <= today_end,
                Appointment.status.in_(["scheduled", "confirmed", "in_progress", "completed"]),
                Appointment.cancelled_at.is_(None),
            )
        ) or 0
        data.checked_in = session.scalar(
            select(func.count(Appointment.id)).where(
                Appointment.scheduled_at >= today_start,
                Appointment.scheduled_at <= today_end,
                Appointment.status.in_(["checked_in", "in_progress"]),
                Appointment.cancelled_at.is_(None),
            )
        ) or 0

    # Waiting queue
    if can_view_queue:
        data.waiting_queue = session.scalar(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.status.in_(["waiting", "with_dentist"]),
                QueueEntry.finished_at.is_(None),
            )
        ) or 0

    # Today's revenue (payments recorded today, not reversed)
    if can_view_payments:
        rev = session.execute(
            select(func.coalesce(func.sum(Payment.amount_paisa), 0)).where(
                Payment.paid_at >= today_start,
                Payment.paid_at <= today_end,
                Payment.reversed_at.is_(None),
            )
        ).scalar_one()
        data.todays_revenue_paisa = int(rev or 0)

    # Pending invoices (posted, unpaid/partial, not voided)
    if can_view_invoices:
        row = session.execute(
            select(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.due_paisa), 0),
            ).where(
                Invoice.is_posted.is_(True),
                Invoice.status.in_(["unpaid", "partial"]),
                Invoice.voided_at.is_(None),
            )
        ).one()
        data.pending_invoices_count = int(row[0] or 0)
        data.pending_invoices_total_paisa = int(row[1] or 0)

    # Low stock (current_qty <= min_level_qty)
    if can_view_inventory:
        data.low_stock_count = session.scalar(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.current_qty <= InventoryItem.min_level_qty,
                InventoryItem.min_level_qty > 0,
            )
        ) or 0

    # Upcoming appointments (next 12, today only, ordered by time)
    if can_view_appts and can_view_patients:
        rows: list[Any] = list(session.execute(
            select(
                Appointment.id,
                Appointment.scheduled_at,
                Appointment.reason,
                Appointment.status,
                Patient.name.label("patient_name"),
                Patient.phone.label("patient_phone"),
                Dentist.name.label("dentist_name"),
            )
            .join(Patient, Patient.id == Appointment.patient_id)
            .outerjoin(Dentist, Dentist.id == Appointment.dentist_id)
            .where(
                Appointment.scheduled_at >= now - dt.timedelta(minutes=30),
                Appointment.scheduled_at <= today_end,
                Appointment.status.in_(["scheduled", "confirmed", "checked_in"]),
                Appointment.cancelled_at.is_(None),
            )
            .order_by(Appointment.scheduled_at.asc())
            .limit(12)
        ).all())
        for r in rows:
            data.upcoming.append(ApptRow(
                id=r.id,
                time_str=_time_fmt(r.scheduled_at),
                patient_name=r.patient_name or "(no name)",
                patient_phone=r.patient_phone or "",
                dentist_name=r.dentist_name or "—",
                reason=r.reason or "",
                status=r.status or "",
            ))

    # Alerts (unread notifications targeted at this user or global)
    unread = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.is_read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ) or 0
    if unread:
        data.alerts.append(AlertRow(
            kind="info",
            title=f"{unread} unread notification(s)",
            detail="Open the notifications menu to review.",
        ))
    if data.pending_invoices_count and can_view_invoices:
        data.alerts.append(AlertRow(
            kind="warning",
            title=f"{data.pending_invoices_count} pending invoice(s)",
            detail=f"Outstanding balance: {data.pending_invoices_total_display}",
        ))
    if data.low_stock_count and can_view_inventory:
        data.alerts.append(AlertRow(
            kind="warning",
            title=f"{data.low_stock_count} low-stock item(s)",
            detail="Reorder to avoid running out.",
        ))
    # Birthday alerts? Skipped — not required by Phase 4 scope.

    return data


# ---------------------------------------------------------------------------
# Global search (Ctrl+K / Ctrl+F)
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    kind: str           # patients | appointments | invoices | payments
    title: str
    subtitle: str
    route: str          # target route to navigate to on activation
    entity_id: int      # id for selection/opening later


def global_search(session: Session, principal: Principal, query: str, limit: int = 20) -> list[SearchResult]:
    """Search across patients, appointments, invoices.

    Returns results only for entities the principal can view, capped to a
    total of ``limit`` entries. Safe to call on every keystroke.
    """
    q = (query or "").strip()
    if not q or len(q) < 1:
        return []
    like = f"%{q}%"
    results: list[SearchResult] = []
    remaining = limit

    # --- Patients ---
    if remaining > 0 and principal.has(Permission.PATIENTS_VIEW):
        patient_rows: list[Any] = list(session.execute(
            select(Patient.id, Patient.name, Patient.phone, Patient.patient_code)
            .where(
                or_(
                    Patient.name.ilike(like),
                    Patient.phone.ilike(like),
                    Patient.patient_code.ilike(like),
                ),
                Patient.deleted_at.is_(None),
            )
            .order_by(Patient.name.asc())
            .limit(remaining)
        ).all())
        for r in patient_rows:
            sub_parts = []
            if r.patient_code:
                sub_parts.append(r.patient_code)
            if r.phone:
                sub_parts.append(r.phone)
            results.append(SearchResult(
                kind="patients",
                title=r.name or "(no name)",
                subtitle="Patient · " + " · ".join(sub_parts) if sub_parts else "Patient",
                route="patients",
                entity_id=r.id,
            ))
        remaining -= len(patient_rows)

    # --- Appointments (today + future by patient name match) ---
    if remaining > 0 and principal.has(Permission.APPOINTMENTS_VIEW) and principal.has(Permission.PATIENTS_VIEW):
        appt_rows: list[Any] = list(session.execute(
            select(
                Appointment.id,
                Appointment.scheduled_at,
                Appointment.status,
                Patient.name.label("patient_name"),
            )
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(
                or_(
                    Patient.name.ilike(like),
                    Appointment.reason.ilike(like),
                ),
                Appointment.scheduled_at >= local_now() - dt.timedelta(days=7),
                Appointment.cancelled_at.is_(None),
            )
            .order_by(Appointment.scheduled_at.asc())
            .limit(remaining)
        ).all())
        for r in appt_rows:
            t = r.scheduled_at.strftime("%d %b %I:%M %p").lstrip("0") if r.scheduled_at else ""
            results.append(SearchResult(
                kind="appointments",
                title=r.patient_name or "(no name)",
                subtitle=f"Appointment · {t} · {(r.status or '').replace('_', ' ').title()}",
                route="appointments",
                entity_id=r.id,
            ))
        remaining -= len(appt_rows)

    # --- Invoices ---
    if remaining > 0 and principal.has(Permission.INVOICES_VIEW) and principal.has(Permission.PATIENTS_VIEW):
        inv_rows: list[Any] = list(session.execute(
            select(
                Invoice.id,
                Invoice.invoice_number,
                Invoice.total_paisa,
                Invoice.status,
                Patient.name.label("patient_name"),
            )
            .join(Patient, Patient.id == Invoice.patient_id)
            .where(
                or_(
                    Patient.name.ilike(like),
                    Invoice.invoice_number.ilike(like),
                ),
                Invoice.voided_at.is_(None),
            )
            .order_by(Invoice.created_at.desc())
            .limit(remaining)
        ).all())
        for r in inv_rows:
            results.append(SearchResult(
                kind="invoices",
                title=f"{r.invoice_number} — {r.patient_name}",
                subtitle=f"Invoice · {format_bdt(r.total_paisa)} · {(r.status or '').title()}",
                route="invoices",
                entity_id=r.id,
            ))
        remaining -= len(inv_rows)

    return results[:limit]


def notification_summary(session: Session, principal: Principal, limit: int = 10) -> dict[str, Any]:
    """Return unread count + recent notifications for the header bell."""
    unread = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.is_read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ) or 0
    rows: list[Any] = list(session.execute(
        select(Notification.id, Notification.kind, Notification.title, Notification.message, Notification.created_at, Notification.is_read)
        .where(
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).all())
    items = [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "message": r.message,
            "created_at": r.created_at,
            "is_read": bool(r.is_read),
        }
        for r in rows
    ]
    return {"unread": int(unread), "items": items}


def mark_notifications_read(session: Session, principal: Principal) -> int:
    """Mark all the user's notifications as read; returns count updated."""
    items = session.scalars(
        select(Notification).where(
            Notification.is_read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ).all()
    n = 0
    now = dt.datetime.utcnow()
    for it in items:
        it.is_read = True
        it.read_at = now
        n += 1
    return n


def add_notification(
    session: Session,
    *,
    user_id: int | None,
    kind: str,
    title: str,
    message: str = "",
) -> Notification:
    # All datetime columns use naive local Asia/Dhaka time for consistency
    # with the rest of the schema (see core/dates.py).
    from dentiva.core.dates import local_now
    n = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        message=message,
        is_read=False,
        created_at=local_now(),
    )
    session.add(n)
    return n
