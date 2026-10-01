"""Prescription service.

Prescriptions have a header (patient/dentist/visit/chief_complaint/on_examination/advice/notes/finalized)
and a list of medicine lines. Finalized prescriptions are immutable (they can
only be cloned, not edited). Finalization locks the prescription immediately
before printing/hand-off to the patient.
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
    ClinicalTemplateOption,
    Dentist,
    Patient,
    Prescription,
    PrescriptionMedicine,
    Visit,
)
from dentiva.services.audit_service import record as audit_record

MEAL_RELATIONS = ("before", "after", "with", "none")
FORMS = ("tablet", "capsule", "syrup", "injection", "cream", "ointment", "gel", "mouthwash", "drop", "inhaler", "other")


# ------------------------------------------------------------------------- DTOs


@dataclass
class MedicineLine:
    id: int | None = None
    idx: int = 0
    name: str = ""
    form: str = ""
    strength: str = ""
    frequency_morning: bool = False
    frequency_noon: bool = False
    frequency_night: bool = False
    meal_relation: str = "after"
    duration_days: int = 0
    quantity: str = ""
    instructions: str = ""

    @property
    def frequency_label(self) -> str:
        parts = []
        if self.frequency_morning:
            parts.append("Morning")
        if self.frequency_noon:
            parts.append("Noon")
        if self.frequency_night:
            parts.append("Night")
        return "+".join(parts) if parts else "As needed"


@dataclass
class PrescriptionInput:
    visit_id: int | None = None
    patient_id: int | None = None
    dentist_id: int | None = None
    chief_complaint: str = ""
    on_examination: str = ""
    advice: str = ""
    notes: str = ""
    medicines: list[MedicineLine] = field(default_factory=list)


@dataclass
class PrescriptionRow:
    id: int
    visit_id: int | None
    patient_id: int
    patient_name: str
    dentist_id: int | None
    dentist_name: str
    date: dt.datetime
    chief_complaint: str
    on_examination: str
    advice: str
    notes: str
    finalized: bool
    finalized_at: dt.datetime | None
    created_by: int | None
    medicines: list[MedicineLine]


@dataclass
class TemplateOptionRow:
    id: int
    section_key: str
    display_text: str
    sort_order: int


# ------------------------------------------------------------------------- list / get


def list_prescriptions(
    session: Session,
    principal: Principal,
    *,
    patient_id: int | None = None,
    visit_id: int | None = None,
    finalized: bool | None = None,
    limit: int = 200,
) -> list[PrescriptionRow]:
    if not principal.has(Permission.PRESCRIPTIONS_VIEW):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_VIEW.value)
    stmt = select(Prescription)
    if patient_id is not None:
        stmt = stmt.where(Prescription.patient_id == patient_id)
    if visit_id is not None:
        stmt = stmt.where(Prescription.visit_id == visit_id)
    if finalized is not None:
        stmt = stmt.where(Prescription.finalized.is_(finalized))
    stmt = stmt.order_by(Prescription.date.desc()).limit(limit)

    rows: list[PrescriptionRow] = []
    name_cache: dict[int, str] = {}
    dname_cache: dict[int, str] = {}
    for p in session.scalars(stmt):
        rows.append(_row_from(session, p, name_cache, dname_cache))
    return rows


def get_prescription(session: Session, principal: Principal, rx_id: int) -> PrescriptionRow:
    if not principal.has(Permission.PRESCRIPTIONS_VIEW):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_VIEW.value)
    p = session.get(Prescription, rx_id)
    if p is None:
        raise NotFoundError("Prescription", rx_id)
    return _row_from(session, p, {}, {})


# ------------------------------------------------------------------------- create / update


def create_prescription(session: Session, principal: Principal, data: PrescriptionInput) -> Prescription:
    if not principal.has(Permission.PRESCRIPTIONS_CREATE):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_CREATE.value)
    pid, did, vid = _resolve_links(session, data)
    rx = Prescription(
        visit_id=vid,
        patient_id=pid,
        dentist_id=did,
        chief_complaint=(data.chief_complaint or "").strip(),
        on_examination=(data.on_examination or "").strip(),
        advice=(data.advice or "").strip(),
        notes=(data.notes or "").strip(),
        finalized=False,
        created_by=principal.user_id,
    )
    session.add(rx)
    session.flush()
    _set_medicines(session, rx.id, data.medicines)
    audit_record(
        session, principal, "prescription.create",
        entity_type="prescription", entity_id=rx.id,
        summary=f"Drafted prescription for patient {pid}.",
    )
    return rx


def update_prescription(
    session: Session, principal: Principal, rx_id: int, data: PrescriptionInput
) -> Prescription:
    if not principal.has(Permission.PRESCRIPTIONS_EDIT):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_EDIT.value)
    rx = session.get(Prescription, rx_id)
    if rx is None:
        raise NotFoundError("Prescription", rx_id)
    if rx.finalized:
        raise ValidationError(
            "Finalized prescriptions cannot be edited. Clone it to make changes.",
            field="finalized",
        )
    if data.patient_id is not None and data.patient_id != rx.patient_id:
        p = session.get(Patient, data.patient_id)
        if p is None or p.deleted_at is not None:
            raise ValidationError("Selected patient does not exist.", field="patient_id")
        rx.patient_id = data.patient_id
    if data.dentist_id != rx.dentist_id:
        if data.dentist_id is not None:
            d = session.get(Dentist, data.dentist_id)
            if d is None or d.deleted_at is not None:
                raise ValidationError("Selected dentist does not exist.", field="dentist_id")
        rx.dentist_id = data.dentist_id
    rx.chief_complaint = (data.chief_complaint or "").strip()
    rx.on_examination = (data.on_examination or "").strip()
    rx.advice = (data.advice or "").strip()
    rx.notes = (data.notes or "").strip()
    _set_medicines(session, rx.id, data.medicines)
    session.flush()
    audit_record(
        session, principal, "prescription.update",
        entity_type="prescription", entity_id=rx.id,
        summary="Updated prescription draft.",
    )
    return rx


def finalize_prescription(session: Session, principal: Principal, rx_id: int) -> Prescription:
    if not principal.has(Permission.PRESCRIPTIONS_EDIT):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_EDIT.value)
    rx = session.get(Prescription, rx_id)
    if rx is None:
        raise NotFoundError("Prescription", rx_id)
    if rx.finalized:
        return rx
    med_count = session.scalar(
        select(func.count(PrescriptionMedicine.id)).where(PrescriptionMedicine.prescription_id == rx_id)
    ) or 0
    if med_count == 0 and not (rx.chief_complaint or rx.on_examination or rx.advice):
        raise ValidationError("Add at least one medicine or clinical notes before finalizing.")
    rx.finalized = True
    rx.finalized_at = local_now()
    session.flush()
    audit_record(
        session, principal, "prescription.finalize",
        entity_type="prescription", entity_id=rx.id,
        summary="Finalized prescription.",
    )
    return rx


def clone_prescription(session: Session, principal: Principal, rx_id: int) -> Prescription:
    if not principal.has(Permission.PRESCRIPTIONS_CREATE):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_CREATE.value)
    src = session.get(Prescription, rx_id)
    if src is None:
        raise NotFoundError("Prescription", rx_id)
    new_rx = Prescription(
        visit_id=src.visit_id,
        patient_id=src.patient_id,
        dentist_id=src.dentist_id,
        chief_complaint=src.chief_complaint,
        on_examination=src.on_examination,
        advice=src.advice,
        notes=src.notes,
        finalized=False,
        created_by=principal.user_id,
    )
    session.add(new_rx)
    session.flush()
    meds = []
    existing_meds = session.scalars(
        select(PrescriptionMedicine)
        .where(PrescriptionMedicine.prescription_id == src.id)
        .order_by(PrescriptionMedicine.idx.asc(), PrescriptionMedicine.id.asc())
    )
    for i, m in enumerate(existing_meds):
        meds.append(
            MedicineLine(
                idx=i,
                name=m.name,
                form=m.form or "",
                strength=m.strength or "",
                frequency_morning=bool(m.frequency_morning),
                frequency_noon=bool(m.frequency_noon),
                frequency_night=bool(m.frequency_night),
                meal_relation=m.meal_relation or "after",
                duration_days=m.duration_days or 0,
                quantity=m.quantity or "",
                instructions=m.instructions or "",
            )
        )
    _set_medicines(session, new_rx.id, meds)
    session.flush()
    audit_record(
        session, principal, "prescription.clone",
        entity_type="prescription", entity_id=new_rx.id,
        summary=f"Cloned prescription #{rx_id}.",
    )
    return new_rx


def delete_prescription(session: Session, principal: Principal, rx_id: int) -> None:
    if not principal.has(Permission.PRESCRIPTIONS_EDIT):
        raise PermissionDeniedError(permission=Permission.PRESCRIPTIONS_EDIT.value)
    rx = session.get(Prescription, rx_id)
    if rx is None:
        raise NotFoundError("Prescription", rx_id)
    if rx.finalized:
        raise ValidationError("Finalized prescriptions cannot be deleted.")
    session.delete(rx)
    session.flush()
    audit_record(
        session, principal, "prescription.delete",
        entity_type="prescription", entity_id=rx_id,
        summary="Deleted prescription draft.",
    )


# ------------------------------------------------------------------------- templates


def list_template_options(
    session: Session, section_key: str | None = None
) -> list[TemplateOptionRow]:
    stmt = select(ClinicalTemplateOption).where(ClinicalTemplateOption.is_active.is_(True))
    if section_key:
        stmt = stmt.where(ClinicalTemplateOption.section_key == section_key)
    stmt = stmt.order_by(
        ClinicalTemplateOption.section_key.asc(),
        ClinicalTemplateOption.sort_order.asc(),
        ClinicalTemplateOption.id.asc(),
    )
    out: list[TemplateOptionRow] = []
    for t in session.scalars(stmt):
        out.append(
            TemplateOptionRow(
                id=t.id,
                section_key=t.section_key,
                display_text=t.display_text,
                sort_order=t.sort_order or 0,
            )
        )
    return out


# ------------------------------------------------------------------------- helpers


def _resolve_links(session: Session, data: PrescriptionInput) -> tuple[int, int | None, int | None]:
    pid = data.patient_id
    if pid is None and data.visit_id is not None:
        v = session.get(Visit, data.visit_id)
        if v is None:
            raise ValidationError("Visit does not exist.", field="visit_id")
        pid = v.patient_id
    if pid is None:
        raise ValidationError("Patient is required.", field="patient_id")
    p = session.get(Patient, pid)
    if p is None or p.deleted_at is not None:
        raise ValidationError("Selected patient does not exist.", field="patient_id")
    did = data.dentist_id
    vid = data.visit_id
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


def _set_medicines(session: Session, rx_id: int, medicines: list[MedicineLine]) -> None:
    session.query(PrescriptionMedicine).filter(PrescriptionMedicine.prescription_id == rx_id).delete()
    session.flush()
    seen: set[str] = set()
    for i, m in enumerate(medicines):
        name = (m.name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        meal = (m.meal_relation or "after").lower()
        if meal not in MEAL_RELATIONS:
            meal = "after"
        form = (m.form or "").strip().lower()
        days = max(0, int(m.duration_days or 0))
        session.add(
            PrescriptionMedicine(
                prescription_id=rx_id,
                idx=i,
                name=name,
                form=form,
                strength=(m.strength or "").strip(),
                frequency_morning=bool(m.frequency_morning),
                frequency_noon=bool(m.frequency_noon),
                frequency_night=bool(m.frequency_night),
                meal_relation=meal,
                duration_days=days,
                quantity=(m.quantity or "").strip(),
                instructions=(m.instructions or "").strip(),
            )
        )


def _row_from(
    session: Session, rx: Prescription, p_cache: dict, d_cache: dict
) -> PrescriptionRow:
    if rx.patient_id in p_cache:
        pname = p_cache[rx.patient_id]
    else:
        p = session.get(Patient, rx.patient_id)
        pname = p.name if p is not None else "(deleted)"
        p_cache[rx.patient_id] = pname
    dname = "—"
    if rx.dentist_id is not None:
        if rx.dentist_id in d_cache:
            dname = d_cache[rx.dentist_id]
        else:
            d = session.get(Dentist, rx.dentist_id)
            dname = d.name if d is not None else "(deleted)"
            d_cache[rx.dentist_id] = dname
    meds: list[MedicineLine] = []
    med_rows = session.scalars(
        select(PrescriptionMedicine)
        .where(PrescriptionMedicine.prescription_id == rx.id)
        .order_by(PrescriptionMedicine.idx.asc(), PrescriptionMedicine.id.asc())
    )
    for m in med_rows:
        meds.append(
            MedicineLine(
                id=m.id,
                idx=m.idx or 0,
                name=m.name,
                form=m.form or "",
                strength=m.strength or "",
                frequency_morning=bool(m.frequency_morning),
                frequency_noon=bool(m.frequency_noon),
                frequency_night=bool(m.frequency_night),
                meal_relation=m.meal_relation or "after",
                duration_days=m.duration_days or 0,
                quantity=m.quantity or "",
                instructions=m.instructions or "",
            )
        )
    return PrescriptionRow(
        id=rx.id,
        visit_id=rx.visit_id,
        patient_id=rx.patient_id,
        patient_name=pname,
        dentist_id=rx.dentist_id,
        dentist_name=dname,
        date=rx.date,
        chief_complaint=rx.chief_complaint or "",
        on_examination=rx.on_examination or "",
        advice=rx.advice or "",
        notes=rx.notes or "",
        finalized=bool(rx.finalized),
        finalized_at=rx.finalized_at,
        created_by=rx.created_by,
        medicines=meds,
    )
