"""Patient service: CRUD with RBAC, BD-phone validation, patient-code
generation, soft-delete, and audit logging.

Patient codes are generated as ``P-000001``, ``P-000002``, … by default and
are unique across soft-deleted patients too. ``last_visit_at`` and
``visit_count`` are maintained by visit creation (Phase 7); the service
only sets them when explicitly called.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from dentiva.core.dates import age_from_dob, local_now
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.core.validators import (
    validate_email,
    validate_non_empty,
    validate_patient_code,
    validate_phone,
)
from dentiva.models import Patient

from .audit_service import record as audit_record

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class PatientInput:
    """Input DTO for create/update. Fields mirror :class:`Patient` except
    system-maintained columns (id, created_at, last_visit_at, visit_count)."""

    name: str = ""
    dob: dt.date | None = None
    gender: str = ""
    blood_group: str = ""
    address: str = ""
    phone: str = ""
    emergency_phone: str = ""
    email: str = ""
    patient_code: str = ""  # empty = auto-generate
    chief_complaint: str = ""
    medical_history: str = ""
    allergies: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Listing / retrieval
# ---------------------------------------------------------------------------

def list_patients(
    session: Session,
    principal: Principal,
    *,
    query: str = "",
    limit: int = 500,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Patient]:
    """Return patients matching ``query`` (searches name, phone, code).

    Soft-deleted patients are excluded unless ``include_deleted`` is True
    (which requires ``patients.delete`` permission).
    """
    if not principal.has(Permission.PATIENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.PATIENTS_VIEW.value)
    q = (query or "").strip()
    stmt = select(Patient)
    if not (include_deleted and principal.has(Permission.PATIENTS_DELETE)):
        stmt = stmt.where(Patient.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Patient.name.ilike(like),
                Patient.phone.ilike(like),
                Patient.patient_code.ilike(like),
            )
        )
    stmt = stmt.order_by(Patient.name.asc()).limit(limit).offset(offset)
    return list(session.scalars(stmt))


def count_patients(session: Session, principal: Principal, *, query: str = "") -> int:
    if not principal.has(Permission.PATIENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.PATIENTS_VIEW.value)
    q = (query or "").strip()
    stmt = select(func.count(Patient.id)).where(Patient.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Patient.name.ilike(like),
                Patient.phone.ilike(like),
                Patient.patient_code.ilike(like),
            )
        )
    return int(session.execute(stmt).scalar_one() or 0)


def get_patient(session: Session, patient_id: int, *, include_deleted: bool = False) -> Patient:
    p = session.get(Patient, patient_id)
    if p is None or (p.deleted_at is not None and not include_deleted):
        raise NotFoundError("Patient", patient_id)
    return p


def get_patient_by_code(session: Session, code: str, *, include_deleted: bool = False) -> Patient | None:
    stmt = select(Patient).where(Patient.patient_code == code.strip().upper())
    if not include_deleted:
        stmt = stmt.where(Patient.deleted_at.is_(None))
    return session.scalar(stmt)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def _next_patient_code(session: Session) -> str:
    """Return the next available P-###### code based on current max id."""
    max_id = session.execute(select(func.coalesce(func.max(Patient.id), 0))).scalar_one()
    return f"P-{int(max_id or 0) + 1:06d}"


def _validate_patient_input(session: Session, data: PatientInput, *, existing: Patient | None) -> dict[str, Any]:
    """Validate input and return a sanitised dict of field values."""
    name = validate_non_empty(data.name, "name", label="Patient name")
    phone = validate_phone(data.phone, "phone", required=False)
    emergency_phone = validate_phone(data.emergency_phone, "emergency_phone", required=False)
    email = validate_email(data.email, "email", required=False)

    code_raw = (data.patient_code or "").strip().upper()
    if not code_raw:
        code = _next_patient_code(session) if existing is None else existing.patient_code
    else:
        code = validate_patient_code(code_raw)
        # Uniqueness check (against all patients including soft-deleted so we
        # don't silently reuse a code a previous record held).
        dup = session.scalar(select(Patient).where(Patient.patient_code == code).limit(1))
        if dup is not None and (existing is None or dup.id != existing.id):
            raise ValidationError("Patient code already in use.", field="patient_code")

    dob = data.dob
    age = age_from_dob(dob) if dob else None
    if dob is not None and dob > dt.date.today():
        raise ValidationError("Date of birth cannot be in the future.", field="dob")

    gender = (data.gender or "").strip().title()
    if gender and gender not in {"Male", "Female", "Other", ""}:
        # Allow free-text but normalise; we do not hard-reject unknown values
        # because clinics sometimes record non-standard entries.
        gender = (data.gender or "").strip()

    return {
        "name": name,
        "dob": dob,
        "age_cache": age,
        "gender": gender,
        "blood_group": (data.blood_group or "").strip().upper(),
        "address": (data.address or "").strip(),
        "phone": phone,
        "emergency_phone": emergency_phone,
        "email": email,
        "patient_code": code,
        "chief_complaint": (data.chief_complaint or "").strip(),
        "medical_history": (data.medical_history or "").strip(),
        "allergies": (data.allergies or "").strip(),
        "notes": (data.notes or "").strip(),
    }


def create_patient(session: Session, principal: Principal, data: PatientInput) -> Patient:
    if not principal.has(Permission.PATIENTS_CREATE):
        raise PermissionDeniedError(permission=Permission.PATIENTS_CREATE.value)
    fields = _validate_patient_input(session, data, existing=None)
    p = Patient(
        name=fields["name"],
        dob=fields["dob"],
        age_cache=fields["age_cache"],
        gender=fields["gender"],
        blood_group=fields["blood_group"],
        address=fields["address"],
        phone=fields["phone"],
        emergency_phone=fields["emergency_phone"],
        email=fields["email"],
        patient_code=fields["patient_code"],
        chief_complaint=fields["chief_complaint"],
        medical_history=fields["medical_history"],
        allergies=fields["allergies"],
        notes=fields["notes"],
        created_by=principal.user_id,
        visit_count=0,
    )
    session.add(p)
    session.flush()
    audit_record(
        session, principal, "patient.create",
        entity_type="patient", entity_id=p.id,
        summary=f"Created patient {p.patient_code} — {p.name}.",
        after={k: v for k, v in fields.items() if k != "age_cache"},
    )
    return p


def update_patient(session: Session, principal: Principal, patient_id: int, data: PatientInput) -> Patient:
    if not principal.has(Permission.PATIENTS_EDIT):
        raise PermissionDeniedError(permission=Permission.PATIENTS_EDIT.value)
    p = get_patient(session, patient_id)
    before = _patient_snapshot(p)
    fields = _validate_patient_input(session, data, existing=p)
    for k, v in fields.items():
        setattr(p, k, v)
    session.flush()
    audit_record(
        session, principal, "patient.update",
        entity_type="patient", entity_id=p.id,
        summary=f"Updated patient {p.patient_code} — {p.name}.",
        before=before, after={k: v for k, v in fields.items() if k != "age_cache"},
    )
    return p


def delete_patient(
    session: Session,
    principal: Principal,
    patient_id: int,
    *,
    confirmation_text: str,
) -> Patient:
    """Soft-delete a patient. Caller must pass the literal confirmation text
    ``"DELETE <patient_code>"`` to confirm (the UI asks for this by showing
    the code). Deleting a patient with linked financial records is refused.
    """
    if not principal.has(Permission.PATIENTS_DELETE):
        raise PermissionDeniedError(permission=Permission.PATIENTS_DELETE.value)
    p = get_patient(session, patient_id)
    expected = f"DELETE {p.patient_code}"
    if (confirmation_text or "").strip().upper() != expected:
        raise ValidationError(
            f"To delete, type '{expected}' to confirm.", field="confirmation"
        )
    # Refuse if patient has posted/non-voided invoices (financial integrity).
    from sqlalchemy import select as _sel

    from dentiva.models import Invoice
    inv_count = session.execute(
        _sel(func.count(Invoice.id)).where(
            Invoice.patient_id == p.id,
            Invoice.is_posted.is_(True),
            Invoice.voided_at.is_(None),
        )
    ).scalar_one()
    if inv_count:
        raise ValidationError(
            "Cannot delete a patient with posted invoices. Void or transfer them first.",
            field="confirmation",
        )
    p.deleted_at = local_now()
    session.flush()
    audit_record(
        session, principal, "patient.delete",
        entity_type="patient", entity_id=p.id,
        summary=f"Soft-deleted patient {p.patient_code} — {p.name}.",
        before=_patient_snapshot(p),
    )
    return p


def record_visit(session: Session, patient_id: int, *, when: dt.datetime | None = None) -> Patient:
    """Called by visit/invoice services to maintain ``last_visit_at`` and
    ``visit_count``. Does NOT perform RBAC checks — callers must already
    have authenticated the operation.
    """
    p = get_patient(session, patient_id)
    ts = when or local_now()
    p.last_visit_at = ts
    p.visit_count = (p.visit_count or 0) + 1
    # Recompute age cache on each visit so it stays current without a job.
    p.age_cache = age_from_dob(p.dob)
    session.flush()
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patient_snapshot(p: Patient) -> dict[str, Any]:
    return {
        "name": p.name,
        "dob": p.dob.isoformat() if p.dob else None,
        "gender": p.gender,
        "blood_group": p.blood_group,
        "phone": p.phone,
        "email": p.email,
        "address": p.address,
        "patient_code": p.patient_code,
        "medical_history": p.medical_history,
        "allergies": p.allergies,
        "notes": p.notes,
    }
