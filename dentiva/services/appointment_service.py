"""Appointment & queue services: scheduling, check-in, chair-side flow,
re-order, and status transitions.

Status flow for an appointment:

    scheduled → confirmed → checked_in → (in_progress via queue) → completed
                         ↘ cancelled / no_show

Queue entries are created either from a checked-in appointment (linking
``appointment_id``) or as a walk-in (no appointment). Queue status flow:

    waiting → with_dentist → finished
           ↘ removed/no_show

When a patient is moved to ``with_dentist``, a new :class:`Visit` is opened
automatically (Phase 6 visit_service) so the chart can be used immediately
from the chair.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.dates import end_of_day, local_now, start_of_day
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import Appointment, Dentist, Patient, QueueEntry

from .audit_service import record as audit_record

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

APPT_STATUSES = {"scheduled", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show"}
QUEUE_STATUSES = {"waiting", "with_dentist", "finished", "removed", "no_show"}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class AppointmentInput:
    patient_id: int = 0
    dentist_id: int | None = None
    scheduled_at: dt.datetime | None = None
    duration_minutes: int = 15
    reason: str = ""
    notes: str = ""
    status: str = "scheduled"


@dataclass
class AppointmentRow:
    id: int
    patient_id: int
    patient_name: str
    patient_phone: str
    dentist_id: int | None
    dentist_name: str
    scheduled_at: dt.datetime
    duration_minutes: int
    reason: str
    status: str
    notes: str


@dataclass
class QueueRow:
    id: int
    patient_id: int
    patient_name: str
    patient_phone: str
    dentist_id: int | None
    dentist_name: str
    appointment_id: int | None
    status: str
    arrived_at: dt.datetime
    started_at: dt.datetime | None
    wait_minutes: int
    visit_id: int | None = None
    reason: str = ""


@dataclass
class ScheduleDay:
    date: dt.date
    appointments: list[AppointmentRow] = field(default_factory=list)
    queue: list[QueueRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

def list_appointments(
    session: Session,
    principal: Principal,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    dentist_id: int | None = None,
    statuses: set[str] | None = None,
    patient_id: int | None = None,
    limit: int = 500,
) -> list[AppointmentRow]:
    if not principal.has(Permission.APPOINTMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.APPOINTMENTS_VIEW.value)
    stmt = (
        select(
            Appointment.id,
            Appointment.patient_id,
            Appointment.dentist_id,
            Appointment.scheduled_at,
            Appointment.duration_minutes,
            Appointment.reason,
            Appointment.status,
            Appointment.notes,
            Patient.name.label("patient_name"),
            Patient.phone.label("patient_phone"),
            Dentist.name.label("dentist_name"),
        )
        .join(Patient, Patient.id == Appointment.patient_id)
        .outerjoin(Dentist, Dentist.id == Appointment.dentist_id)
    )
    if start is not None:
        stmt = stmt.where(Appointment.scheduled_at >= start)
    if end is not None:
        stmt = stmt.where(Appointment.scheduled_at <= end)
    if dentist_id is not None:
        stmt = stmt.where(Appointment.dentist_id == dentist_id)
    if statuses:
        stmt = stmt.where(Appointment.status.in_(statuses))
    if patient_id is not None:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    stmt = stmt.order_by(Appointment.scheduled_at.asc()).limit(limit)
    rows = session.execute(stmt).all()
    return [
        AppointmentRow(
            id=r.id, patient_id=r.patient_id, patient_name=r.patient_name or "",
            patient_phone=r.patient_phone or "", dentist_id=r.dentist_id,
            dentist_name=r.dentist_name or "—",
            scheduled_at=r.scheduled_at, duration_minutes=r.duration_minutes or 15,
            reason=r.reason or "", status=r.status or "scheduled", notes=r.notes or "",
        )
        for r in rows
    ]


def get_appointment(session: Session, principal: Principal, appt_id: int) -> AppointmentRow:
    if not principal.has(Permission.APPOINTMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.APPOINTMENTS_VIEW.value)
    a = session.get(Appointment, appt_id)
    if a is None:
        raise NotFoundError("Appointment", appt_id)
    p = session.get(Patient, a.patient_id)
    d = session.get(Dentist, a.dentist_id) if a.dentist_id else None
    return AppointmentRow(
        id=a.id, patient_id=a.patient_id,
        patient_name=p.name if p else "(deleted)",
        patient_phone=p.phone if p else "",
        dentist_id=a.dentist_id,
        dentist_name=d.name if d else "—",
        scheduled_at=a.scheduled_at, duration_minutes=a.duration_minutes or 15,
        reason=a.reason or "", status=a.status or "scheduled", notes=a.notes or "",
    )


def _conflict_check(
    session: Session,
    dentist_id: int | None,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    exclude_id: int | None = None,
) -> int:
    """Return count of conflicting appointments for a dentist in the window.

    Two appointments conflict when their time ranges overlap. Unassigned
    appointments (no dentist) only conflict with other unassigned ones.
    """
    stmt = select(Appointment).where(
        Appointment.cancelled_at.is_(None),
        Appointment.status.in_(["scheduled", "confirmed", "checked_in", "in_progress"]),
    )
    if dentist_id is None:
        stmt = stmt.where(Appointment.dentist_id.is_(None))
    else:
        stmt = stmt.where(Appointment.dentist_id == dentist_id)
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    conflicts = 0
    for a in session.scalars(stmt):
        a_end = a.scheduled_at + dt.timedelta(minutes=a.duration_minutes or 15)
        if a.scheduled_at < end_dt and a_end > start_dt:
            conflicts += 1
    return conflicts


def create_appointment(session: Session, principal: Principal, data: AppointmentInput) -> Appointment:
    if not principal.has(Permission.APPOINTMENTS_CREATE):
        raise PermissionDeniedError(permission=Permission.APPOINTMENTS_CREATE.value)
    _validate_input(session, data)
    # Check patient exists & not deleted
    patient = session.get(Patient, data.patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ValidationError("Selected patient does not exist.", field="patient_id")
    # Check dentist if provided
    if data.dentist_id is not None:
        d = session.get(Dentist, data.dentist_id)
        if d is None or d.deleted_at is not None:
            raise ValidationError("Selected dentist does not exist.", field="dentist_id")
    assert data.scheduled_at is not None
    start_dt: dt.datetime = data.scheduled_at
    end_dt: dt.datetime = start_dt + dt.timedelta(minutes=data.duration_minutes)
    conflicts = _conflict_check(session, data.dentist_id, start_dt, end_dt)
    if conflicts:
        raise ValidationError(
            "Time slot conflicts with another appointment for the selected dentist.",
            field="scheduled_at",
        )
    appt = Appointment(
        patient_id=data.patient_id,
        dentist_id=data.dentist_id,
        scheduled_at=data.scheduled_at,
        duration_minutes=data.duration_minutes,
        reason=(data.reason or "").strip(),
        notes=(data.notes or "").strip(),
        status=data.status if data.status in APPT_STATUSES else "scheduled",
        created_by=principal.user_id,
    )
    session.add(appt)
    session.flush()
    audit_record(session, principal, "appointment.create", entity_type="appointment", entity_id=appt.id,
                 summary=f"Scheduled {(patient.name)} on {data.scheduled_at:%Y-%m-%d %H:%M}.")
    return appt


def update_appointment(session: Session, principal: Principal, appt_id: int, data: AppointmentInput) -> Appointment:
    if not principal.has(Permission.APPOINTMENTS_EDIT):
        raise PermissionDeniedError(permission=Permission.APPOINTMENTS_EDIT.value)
    a = session.get(Appointment, appt_id)
    if a is None:
        raise NotFoundError("Appointment", appt_id)
    if a.status in {"completed", "cancelled", "no_show"}:
        raise ValidationError("Cannot edit a completed/cancelled/no-show appointment.", field="status")
    _validate_input(session=None, data=data, existing=a)
    if data.patient_id and data.patient_id != a.patient_id:
        p = session.get(Patient, data.patient_id)
        if p is None or p.deleted_at is not None:
            raise ValidationError("Selected patient does not exist.", field="patient_id")
        a.patient_id = data.patient_id
    if data.dentist_id != a.dentist_id:
        if data.dentist_id is not None:
            d = session.get(Dentist, data.dentist_id)
            if d is None or d.deleted_at is not None:
                raise ValidationError("Selected dentist does not exist.", field="dentist_id")
        a.dentist_id = data.dentist_id
    a.scheduled_at = data.scheduled_at  # type: ignore[assignment]
    a.duration_minutes = data.duration_minutes
    a.reason = (data.reason or "").strip()
    a.notes = (data.notes or "").strip()
    assert a.scheduled_at is not None
    end_dt = a.scheduled_at + dt.timedelta(minutes=a.duration_minutes or 15)
    if _conflict_check(session, a.dentist_id, a.scheduled_at, end_dt, exclude_id=a.id):
        raise ValidationError(
            "Time slot conflicts with another appointment for the selected dentist.",
            field="scheduled_at",
        )
    session.flush()
    audit_record(session, principal, "appointment.update", entity_type="appointment", entity_id=a.id,
                 summary="Appointment rescheduled/edited.")
    return a


def cancel_appointment(session: Session, principal: Principal, appt_id: int, *, reason: str = "") -> Appointment:
    if not principal.has(Permission.APPOINTMENTS_CANCEL):
        raise PermissionDeniedError(permission=Permission.APPOINTMENTS_CANCEL.value)
    a = session.get(Appointment, appt_id)
    if a is None:
        raise NotFoundError("Appointment", appt_id)
    if a.status in {"completed", "cancelled"}:
        return a
    a.status = "cancelled"
    a.cancelled_at = local_now()
    if reason and not a.notes:
        a.notes = f"Cancelled: {reason}"
    session.flush()
    audit_record(session, principal, "appointment.cancel", entity_type="appointment", entity_id=a.id,
                 summary=reason or "Appointment cancelled.")
    # Remove from queue if present
    q = session.scalar(
        select(QueueEntry).where(
            QueueEntry.appointment_id == a.id,
            QueueEntry.status.in_(["waiting", "with_dentist"]),
        )
    )
    if q is not None:
        q.status = "removed"
        q.finished_at = local_now()
    return a


def mark_appointment_status(session: Session, principal: Principal, appt_id: int, status: str) -> Appointment:
    """Set status (e.g. confirmed, no_show, completed)."""
    if status not in APPT_STATUSES:
        raise ValidationError(f"Unknown appointment status: {status}")
    a = session.get(Appointment, appt_id)
    if a is None:
        raise NotFoundError("Appointment", appt_id)
    a.status = status
    if status == "cancelled" and a.cancelled_at is None:
        a.cancelled_at = local_now()
    session.flush()
    audit_record(session, principal, f"appointment.status.{status}", entity_type="appointment", entity_id=a.id,
                 summary=f"Status set to {status}.")
    return a


# ---------------------------------------------------------------------------
# Queue / check-in / chair-side flow
# ---------------------------------------------------------------------------

def list_queue(session: Session, principal: Principal, *, dentist_id: int | None = None,
               include_finished_today: bool = True) -> list[QueueRow]:
    if not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    today = start_of_day(local_now())
    today_end = end_of_day(local_now())
    stmt = (
        select(
            QueueEntry.id, QueueEntry.patient_id, QueueEntry.dentist_id, QueueEntry.appointment_id,
            QueueEntry.status, QueueEntry.arrived_at, QueueEntry.started_at,
            Patient.name.label("patient_name"), Patient.phone.label("patient_phone"),
            Dentist.name.label("dentist_name"),
            Appointment.reason.label("appt_reason"),
        )
        .join(Patient, Patient.id == QueueEntry.patient_id)
        .outerjoin(Dentist, Dentist.id == QueueEntry.dentist_id)
        .outerjoin(Appointment, Appointment.id == QueueEntry.appointment_id)
        .where(QueueEntry.arrived_at >= today, QueueEntry.arrived_at <= today_end)
        .order_by(QueueEntry.position.asc(), QueueEntry.arrived_at.asc())
    )
    if dentist_id is not None:
        stmt = stmt.where(QueueEntry.dentist_id == dentist_id)
    if not include_finished_today:
        stmt = stmt.where(QueueEntry.status.in_(["waiting", "with_dentist"]))
    rows = session.execute(stmt).all()
    now = local_now()
    out: list[QueueRow] = []
    for r in rows:
        wait = int((now - r.arrived_at).total_seconds() // 60) if r.arrived_at else 0
        out.append(QueueRow(
            id=r.id, patient_id=r.patient_id, patient_name=r.patient_name or "",
            patient_phone=r.patient_phone or "", dentist_id=r.dentist_id,
            dentist_name=r.dentist_name or "Unassigned",
            appointment_id=r.appointment_id, status=r.status or "waiting",
            arrived_at=r.arrived_at, started_at=r.started_at, wait_minutes=wait,
            reason=r.appt_reason or "",
        ))
    return out


def check_in_appointment(session: Session, principal: Principal, appt_id: int, *, dentist_id: int | None = None) -> QueueEntry:
    """Mark a scheduled/confirmed appointment as checked-in and add to queue."""
    if not principal.has(Permission.QUEUE_MANAGE) or not principal.has(Permission.APPOINTMENTS_EDIT):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    a = session.get(Appointment, appt_id)
    if a is None:
        raise NotFoundError("Appointment", appt_id)
    if a.status in {"cancelled", "no_show", "completed"}:
        raise ValidationError(f"Cannot check in a {a.status} appointment.")
    # Already checked in?
    existing = session.scalar(
        select(QueueEntry).where(
            QueueEntry.appointment_id == appt_id,
            QueueEntry.status.in_(["waiting", "with_dentist"]),
            QueueEntry.arrived_at >= start_of_day(local_now()),
        )
    )
    if existing is not None:
        return existing
    assign_dentist = dentist_id if dentist_id is not None else a.dentist_id
    a.status = "checked_in"
    pos = _next_queue_position(session, assign_dentist)
    q = QueueEntry(
        patient_id=a.patient_id,
        dentist_id=assign_dentist,
        appointment_id=a.id,
        status="waiting",
        position=pos,
        arrived_at=local_now(),
        created_by=principal.user_id,
    )
    session.add(q)
    session.flush()
    audit_record(session, principal, "queue.check_in", entity_type="queue_entry", entity_id=q.id,
                 summary=f"Checked in appointment #{appt_id}.")
    return q


def walk_in(session: Session, principal: Principal, patient_id: int, *, dentist_id: int | None = None, reason: str = "") -> QueueEntry:
    """Register a walk-in patient in the queue (no appointment)."""
    if not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    p = session.get(Patient, patient_id)
    if p is None or p.deleted_at is not None:
        raise ValidationError("Selected patient does not exist.", field="patient_id")
    if dentist_id is not None:
        d = session.get(Dentist, dentist_id)
        if d is None or d.deleted_at is not None:
            raise ValidationError("Selected dentist does not exist.", field="dentist_id")
    pos = _next_queue_position(session, dentist_id)
    q = QueueEntry(
        patient_id=patient_id,
        dentist_id=dentist_id,
        appointment_id=None,
        status="waiting",
        position=pos,
        arrived_at=local_now(),
        created_by=principal.user_id,
    )
    session.add(q)
    session.flush()
    # Add reason to patient's chief complaint if it looks like one? No — leave
    # that for the visit dialog.
    audit_record(session, principal, "queue.walk_in", entity_type="queue_entry", entity_id=q.id,
                 summary=f"Walk-in for patient {p.name}{f' ({reason})' if reason else ''}.")
    return q


def start_service(session: Session, principal: Principal, queue_entry_id: int) -> tuple[QueueEntry, int]:
    """Move a waiting entry to with_dentist, open a new Visit, and return
    (queue_entry, visit_id)."""
    if not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    from dentiva.services import visit_service
    q = session.get(QueueEntry, queue_entry_id)
    if q is None:
        raise NotFoundError("QueueEntry", queue_entry_id)
    if q.status != "waiting":
        raise ValidationError("Only waiting patients can be started.")
    q.status = "with_dentist"
    q.started_at = local_now()
    session.flush()
    # Open a visit
    from dentiva.services.visit_service import VisitInput
    v = visit_service.create_visit(session, principal, q.patient_id, VisitInput(
        dentist_id=q.dentist_id,
        visit_date=local_now(),
        reason=(q.appointment_id and "(from queue)") or "(walk-in)",
    ))
    audit_record(session, principal, "queue.start", entity_type="queue_entry", entity_id=q.id,
                 summary=f"Started service for queue entry #{q.id}; visit #{v.id} opened.")
    return q, v.id


def finish_service(session: Session, principal: Principal, queue_entry_id: int, *, mark_appt_completed: bool = True) -> QueueEntry:
    if not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    q = session.get(QueueEntry, queue_entry_id)
    if q is None:
        raise NotFoundError("QueueEntry", queue_entry_id)
    if q.status == "finished":
        return q
    q.status = "finished"
    q.finished_at = local_now()
    if mark_appt_completed and q.appointment_id is not None:
        a = session.get(Appointment, q.appointment_id)
        if a is not None and a.status not in {"cancelled", "no_show"}:
            a.status = "completed"
    session.flush()
    audit_record(session, principal, "queue.finish", entity_type="queue_entry", entity_id=q.id,
                 summary=f"Finished queue entry #{q.id}.")
    return q


def remove_from_queue(session: Session, principal: Principal, queue_entry_id: int, *, reason: str = "removed") -> QueueEntry:
    if not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_MANAGE.value)
    q = session.get(QueueEntry, queue_entry_id)
    if q is None:
        raise NotFoundError("QueueEntry", queue_entry_id)
    if q.status in {"finished", "removed"}:
        return q
    q.status = "removed" if reason != "no_show" else "no_show"
    q.finished_at = local_now()
    if q.appointment_id is not None and reason == "no_show":
        a = session.get(Appointment, q.appointment_id)
        if a is not None:
            a.status = "no_show"
    session.flush()
    audit_record(session, principal, "queue.remove", entity_type="queue_entry", entity_id=q.id,
                 summary=f"Removed from queue ({reason}).")
    return q


def reorder_queue(session: Session, principal: Principal, dentist_id: int | None, ordered_ids: list[int]) -> None:
    """Set position for the given queue entry ids (waiting + with_dentist)
    according to the supplied order."""
    if not principal.has(Permission.QUEUE_REORDER) and not principal.has(Permission.QUEUE_MANAGE):
        raise PermissionDeniedError(permission=Permission.QUEUE_REORDER.value)
    # Validate ids belong to active queue.
    today_start = start_of_day(local_now())
    today_end = end_of_day(local_now())
    rows = list(session.scalars(
        select(QueueEntry).where(
            QueueEntry.arrived_at >= today_start,
            QueueEntry.arrived_at <= today_end,
            QueueEntry.status.in_(["waiting", "with_dentist"]),
        )
    ))
    by_id = {r.id: r for r in rows}
    for idx, qid in enumerate(ordered_ids, start=1):
        q = by_id.get(qid)
        if q is None:
            continue
        if dentist_id is not None and q.dentist_id != dentist_id:
            continue
        q.position = idx
    session.flush()


def _next_queue_position(session: Session, dentist_id: int | None) -> int:
    today_start = start_of_day(local_now())
    today_end = end_of_day(local_now())
    stmt = select(func.coalesce(func.max(QueueEntry.position), 0)).where(
        QueueEntry.arrived_at >= today_start,
        QueueEntry.arrived_at <= today_end,
    )
    if dentist_id is None:
        stmt = stmt.where(QueueEntry.dentist_id.is_(None))
    else:
        stmt = stmt.where(QueueEntry.dentist_id == dentist_id)
    return int(session.execute(stmt).scalar_one() or 0) + 1


def _validate_input(session: Session | None, data: AppointmentInput, *, existing: Appointment | None = None) -> None:
    if not data.patient_id and (existing is None or not existing.patient_id):
        raise ValidationError("Patient is required.", field="patient_id")
    if data.scheduled_at is None:
        raise ValidationError("Appointment date/time is required.", field="scheduled_at")
    if data.scheduled_at.tzinfo is not None:
        # Strip tz for naive local comparison
        data.scheduled_at = data.scheduled_at.astimezone().replace(tzinfo=None)
    if data.duration_minutes is None or data.duration_minutes < 5 or data.duration_minutes > 480:
        raise ValidationError("Duration must be between 5 and 480 minutes.", field="duration_minutes")
    if data.status and data.status not in APPT_STATUSES:
        raise ValidationError(f"Unknown status: {data.status}", field="status")


# ---------------------------------------------------------------------------
# Upcoming reminders / helpers
# ---------------------------------------------------------------------------

def upcoming_appointments(session: Session, principal: Principal, *, within_minutes: int = 60) -> list[AppointmentRow]:
    """Return appointments starting within the next ``within_minutes`` minutes
    that are still scheduled/confirmed (for notifications)."""
    now = local_now()
    return list_appointments(
        session, principal,
        start=now,
        end=now + dt.timedelta(minutes=within_minutes),
        statuses={"scheduled", "confirmed"},
    )
