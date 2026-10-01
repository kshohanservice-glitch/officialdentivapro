# mypy: disable-error-code="arg-type, union-attr"
"""Notification generation + read/clear helpers.

Idempotent generators for four types of notification:

* Upcoming appointment reminder (within lead window, window is configurable)
* Daily schedule summary (first tick of the day)
* Low-stock inventory items (below reorder level)
* Overdue invoices (posted, unpaid past due-days threshold)

All emitted notifications are "broadcast" (user_id=None) so every logged-in user
sees them. Episode state (last processed ids per kind) is persisted in AppSetting
so restarts don't re-emit duplicates.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.permissions import Permission, Policy, Principal
from dentiva.models import (
    Appointment,
    AppSetting,
    InventoryItem,
    Invoice,
    Notification,
    Patient,
)

log = logging.getLogger(__name__)


# -------------------------------------------------------------------------- settings
SETTINGS: dict[str, dict[str, Any]] = {
    "notif.appt_reminder.enabled": {"type": "bool", "default": True},
    "notif.appt_reminder.lead_minutes": {"type": "int", "default": 30, "min": 5, "max": 1440},
    "notif.today_summary.enabled": {"type": "bool", "default": True},
    "notif.low_stock.enabled": {"type": "bool", "default": True},
    "notif.overdue_invoice.enabled": {"type": "bool", "default": True},
    "notif.overdue_invoice.days": {"type": "int", "default": 7, "min": 1, "max": 365},
    # Printing defaults (used by prescription/invoice preview dialogs)
    "print.prescription.paper": {"type": "str", "default": "a4", "choices": ("a4", "a5", "thermal-80", "thermal-58")},
    "print.invoice.paper": {"type": "str", "default": "a4", "choices": ("a4", "a5", "thermal-80", "thermal-58")},
}


def get_setting(session: Session, key: str, principal: Principal, default: Any = None) -> Any:
    spec = SETTINGS.get(key)
    raw_default = spec["default"] if spec else default
    row = session.scalar(select(AppSetting).where(AppSetting.key == key))
    raw = row.value if row else None
    if raw is None:
        return raw_default
    return _cast(raw, spec["type"] if spec else "str")


def set_setting(session: Session, key: str, value: Any, principal: Principal) -> bool:
    """Persist a setting value. Returns False if the value failed validation."""
    spec = SETTINGS.get(key)
    if spec is None:
        # Unknown keys are still stored (forward-compat) as strings
        conv = str(value)
    else:
        t = spec["type"]
        if t == "bool":
            conv = "1" if bool(value) else "0"
        elif t == "int":
            try:
                iv = int(value)
            except (TypeError, ValueError):
                return False
            if "min" in spec and iv < spec["min"]:
                return False
            if "max" in spec and iv > spec["max"]:
                return False
            conv = str(iv)
        else:
            conv = str(value)
            if "choices" in spec and conv not in spec["choices"]:
                return False
    row = session.scalar(select(AppSetting).where(AppSetting.key == key))
    if row is None:
        row = AppSetting(key=key, value=conv)
        session.add(row)
    else:
        row.value = conv
    session.flush()
    return True


def list_settings(session: Session, principal: Principal) -> dict[str, Any]:
    Policy.require(principal, Permission.NOTIFICATIONS_MANAGE)
    return {key: get_setting(session, key, principal) for key in SETTINGS}


# -------------------------------------------------------------------- episode state
_EPISODE_KEY = "notif.episode_state"
_EPISODE_CAP = 200  # cap per kind to avoid unbounded growth


def _load_state(session: Session) -> dict[str, list[int]]:
    row = session.scalar(select(AppSetting).where(AppSetting.key == _EPISODE_KEY))
    if not row or not row.value:
        return {}
    try:
        loaded = json.loads(row.value)
        if isinstance(loaded, dict):
            return {k: [int(x) for x in v] for k, v in loaded.items() if isinstance(v, list)}
    except Exception:  # pragma: no cover
        log.warning("Bad notif episode state; resetting")
    return {}


def _save_state(session: Session, state: dict[str, list[int]]) -> None:
    clipped = {k: v[-_EPISODE_CAP:] for k, v in state.items()}
    payload = json.dumps(clipped)
    row = session.scalar(select(AppSetting).where(AppSetting.key == _EPISODE_KEY))
    if row is None:
        session.add(AppSetting(key=_EPISODE_KEY, value=payload))
    else:
        row.value = payload


def _seen(state: dict[str, list[int]], kind: str, obj_id: int) -> bool:
    return obj_id in state.get(kind, [])


def _mark_seen(state: dict[str, list[int]], kind: str, obj_id: int) -> None:
    state.setdefault(kind, []).append(obj_id)


# ------------------------------------------------------------------- generators
def generate_notifications(session: Session, principal: Principal) -> list[Notification]:
    """Run all generators. Idempotent within a process lifetime and across
    restarts (episode state is persisted)."""
    created: list[Notification] = []
    state = _load_state(session)
    now = local_now()

    if get_setting(session, "notif.appt_reminder.enabled", principal):
        created.extend(_gen_appt_upcoming(session, principal, state, now))
    if get_setting(session, "notif.today_summary.enabled", principal):
        created.extend(_gen_day_summary(session, principal, state, now))
    if get_setting(session, "notif.low_stock.enabled", principal):
        created.extend(_gen_low_stock(session, principal, state))
    if get_setting(session, "notif.overdue_invoice.enabled", principal):
        created.extend(_gen_overdue_invoices(session, principal, state, now))

    _save_state(session, state)
    session.flush()
    return created


def _gen_appt_upcoming(session: Session, principal: Principal,
                       state: dict[str, list[int]], now: dt.datetime) -> Iterable[Notification]:
    lead = int(get_setting(session, "notif.appt_reminder.lead_minutes", principal))
    window_start = now
    window_end = now + dt.timedelta(minutes=lead)
    rows = session.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.scheduled_at >= window_start,
            Appointment.scheduled_at <= window_end,
            Appointment.status == "scheduled",
            Appointment.cancelled_at.is_(None),
        )
    ).all()
    for appt, patient in rows:
        if _seen(state, "appt_upcoming", appt.id):
            continue
        mins = max(1, int((appt.scheduled_at - now).total_seconds() // 60))
        title = f"Upcoming appointment in {mins} min"
        message = f"{patient.name} — {appt.reason or 'Visit'} at {appt.scheduled_at.strftime('%I:%M %p')}."
        n = _emit(session, "appt_upcoming", title, message, {"appointment_id": appt.id})
        _mark_seen(state, "appt_upcoming", appt.id)
        yield n


def _gen_day_summary(session: Session, principal: Principal,
                     state: dict[str, list[int]], now: dt.datetime) -> Iterable[Notification]:
    today = now.date()
    key = f"day_summary:{today.isoformat()}"
    # Use a synthetic sentinel id = ordinal of the day so state works per-kind with int list.
    sentinel = int(today.toordinal())
    if _seen(state, "day_summary", sentinel):
        return
    start = dt.datetime.combine(today, dt.time(0, 0))
    end = start + dt.timedelta(days=1)
    count = session.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end,
            Appointment.status == "scheduled",
            Appointment.cancelled_at.is_(None),
        )
    ) or 0
    if count <= 0:
        _mark_seen(state, "day_summary", sentinel)
        return
    title = f"Today's schedule: {count} appointment" + ("s" if count != 1 else "")
    message = f"You have {count} appointment" + ("s" if count != 1 else "") + " scheduled today."
    n = _emit(session, "day_summary", title, message, {"date": key, "count": count})
    _mark_seen(state, "day_summary", sentinel)
    yield n


def _gen_low_stock(session: Session, principal: Principal,
                   state: dict[str, list[int]]) -> Iterable[Notification]:
    rows = session.execute(
        select(InventoryItem).where(
            InventoryItem.current_qty <= InventoryItem.min_level_qty,
        )
    ).scalars().all()
    low = [r for r in rows if float(r.current_qty or 0) < float(r.min_level_qty or 0)]
    if not low:
        return
    for item in low:
        if _seen(state, "low_stock", item.id):
            continue
        title = f"Low stock: {item.name}"
        message = f"On hand {float(item.current_qty):g} {item.unit or 'pcs'}, reorder level {float(item.min_level_qty):g}."
        n = _emit(session, "low_stock", title, message, {"inventory_item_id": item.id})
        _mark_seen(state, "low_stock", item.id)
        yield n


def _gen_overdue_invoices(session: Session, principal: Principal,
                          state: dict[str, list[int]], now: dt.datetime) -> Iterable[Notification]:
    days = int(get_setting(session, "notif.overdue_invoice.days", principal))
    # Overdue = posted + due_paisa > 0 + posted_at older than threshold days.
    cutoff = now - dt.timedelta(days=days)
    rows = session.execute(
        select(Invoice, Patient)
        .join(Patient, Patient.id == Invoice.patient_id)
        .where(
            Invoice.is_posted.is_(True),
            Invoice.due_paisa > 0,
            Invoice.posted_at.isnot(None),
            Invoice.posted_at <= cutoff,
            Invoice.status.in_(("unpaid", "partial")),
        )
    ).all()
    for inv, patient in rows:
        if _seen(state, "overdue_invoice", inv.id):
            continue
        amount = inv.due_paisa / 100
        title = f"Overdue invoice: {inv.invoice_number}"
        message = f"{patient.name} owes ৳{amount:,.2f}."
        n = _emit(session, "overdue_invoice", title, message, {"invoice_id": inv.id})
        _mark_seen(state, "overdue_invoice", inv.id)
        yield n


def _emit(session: Session, kind: str, title: str, message: str, payload: dict[str, Any] | None = None) -> Notification:
    n = Notification(
        user_id=None,  # broadcast
        kind=kind,
        title=title,
        message=message,
        payload_json=json.dumps(payload or {}),
        is_read=False,
    )
    session.add(n)
    session.flush()
    return n


# ----------------------------------------------------------- listing / read helpers
def list_notifications(
    session: Session,
    principal: Principal,
    *,
    limit: int = 100,
    kind_filter: str | None = None,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Notification).where(
        or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None))
    ).order_by(Notification.created_at.desc()).limit(limit)
    rows = list(session.scalars(stmt).all())
    out: list[dict[str, Any]] = []
    for r in rows:
        if kind_filter and r.kind != kind_filter:
            continue
        if status_filter == "unread" and r.is_read:
            continue
        if status_filter == "read" and not r.is_read:
            continue
        out.append({
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "message": r.message,
            "is_read": bool(r.is_read),
            "created_at": r.created_at,
            "read_at": r.read_at,
        })
    return out


def unread_count(session: Session, principal: Principal) -> int:
    return int(session.scalar(
        select(func.count(Notification.id)).where(
            Notification.is_read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ) or 0)


def mark_read(session: Session, principal: Principal, notification_id: int) -> bool:
    row = session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    )
    if not row or row.is_read:
        return False
    row.is_read = True
    row.read_at = dt.datetime.utcnow()
    return True


def mark_all_read(session: Session, principal: Principal) -> int:
    rows = session.scalars(
        select(Notification).where(
            Notification.is_read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ).all()
    now = dt.datetime.utcnow()
    n = 0
    for r in rows:
        r.is_read = True
        r.read_at = now
        n += 1
    return n


def delete_all_read(session: Session, principal: Principal, older_than_days: int = 1) -> int:
    """Housekeeping: delete read notifications older than ``older_than_days``."""
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=older_than_days)
    rows = session.scalars(
        select(Notification).where(
            Notification.is_read.is_(True),
            Notification.read_at.isnot(None),
            Notification.read_at <= cutoff,
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
    ).all()
    for r in rows:
        session.delete(r)
    return len(rows)


# --------------------------------------------------------------- helpers
def _cast(raw: str, t: str) -> Any:
    if t == "bool":
        return raw in ("1", "true", "True", "yes")
    if t == "int":
        try:
            return int(raw)
        except ValueError:
            return 0
    return raw
