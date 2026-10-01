"""Treatment catalog and per-visit treatment records.

Price snapshots: when a treatment is added to a visit, the catalog price is
copied to `price_paisa` and the catalog name to `name_at_service_time` so
future edits to the catalog never change billed history. Tooth codes are
stored as a comma-separated string of FDI tooth numbers ("36,46").
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import Dentist, Patient, TreatmentCatalog, TreatmentRecord, Visit
from dentiva.services.audit_service import record as audit_record

# ------------------------------------------------------------------------- DTOs


@dataclass
class TreatmentCatalogRow:
    id: int
    name: str
    description: str
    category: str
    default_price_paisa: int
    is_active: bool
    usage_count: int = 0


@dataclass
class TreatmentCatalogInput:
    name: str = ""
    description: str = ""
    category: str = ""
    default_price_paisa: int = 0
    is_active: bool = True


@dataclass
class TreatmentRecordRow:
    id: int
    visit_id: int
    patient_id: int
    patient_name: str
    dentist_id: int | None
    dentist_name: str
    catalog_id: int | None
    name_at_service_time: str
    description: str
    tooth_codes: str
    price_paisa: int
    notes: str
    created_at: dt.datetime
    created_by: int | None


@dataclass
class TreatmentRecordInput:
    catalog_id: int | None = None
    name_at_service_time: str = ""
    description: str = ""
    tooth_codes: str = ""
    price_paisa: int = 0
    notes: str = ""


# --------------------------------------------------------------- catalog


def list_catalog(
    session: Session,
    principal: Principal,
    *,
    category: str | None = None,
    active_only: bool = False,
    search: str | None = None,
    limit: int = 500,
) -> list[TreatmentCatalogRow]:
    if not principal.has(Permission.TREATMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_VIEW.value)
    stmt = select(TreatmentCatalog)
    if category:
        stmt = stmt.where(TreatmentCatalog.category == category)
    if active_only:
        stmt = stmt.where(TreatmentCatalog.is_active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(TreatmentCatalog.name.ilike(like))
    stmt = stmt.order_by(TreatmentCatalog.category.asc(), TreatmentCatalog.name.asc()).limit(limit)

    counts_rows = session.execute(
        select(TreatmentRecord.catalog_id, func.count(TreatmentRecord.id))
        .where(TreatmentRecord.catalog_id.is_not(None))
        .group_by(TreatmentRecord.catalog_id)
    ).all()
    counts = {cid: n for cid, n in counts_rows}

    rows: list[TreatmentCatalogRow] = []
    for t in session.scalars(stmt):
        rows.append(
            TreatmentCatalogRow(
                id=t.id,
                name=t.name,
                description=t.description or "",
                category=t.category or "",
                default_price_paisa=t.default_price_paisa or 0,
                is_active=bool(t.is_active),
                usage_count=int(counts.get(t.id, 0)),
            )
        )
    return rows


def get_catalog(session: Session, principal: Principal, catalog_id: int) -> TreatmentCatalogRow:
    if not principal.has(Permission.TREATMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_VIEW.value)
    t = session.get(TreatmentCatalog, catalog_id)
    if t is None:
        raise NotFoundError("TreatmentCatalog", catalog_id)
    return TreatmentCatalogRow(
        id=t.id,
        name=t.name,
        description=t.description or "",
        category=t.category or "",
        default_price_paisa=t.default_price_paisa or 0,
        is_active=bool(t.is_active),
    )


def create_catalog_item(session: Session, principal: Principal, data: TreatmentCatalogInput) -> TreatmentCatalog:
    if not principal.has(Permission.TREATMENTS_CATALOG_MANAGE):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_CATALOG_MANAGE.value)
    _validate_catalog(data)
    existing = session.scalar(
        select(TreatmentCatalog).where(func.lower(TreatmentCatalog.name) == data.name.strip().lower())
    )
    if existing is not None:
        raise ValidationError(
            f"A treatment named '{data.name.strip()}' already exists.", field="name"
        )
    item = TreatmentCatalog(
        name=data.name.strip(),
        description=(data.description or "").strip(),
        category=(data.category or "").strip(),
        default_price_paisa=max(0, int(data.default_price_paisa)),
        is_active=bool(data.is_active),
    )
    session.add(item)
    session.flush()
    audit_record(
        session, principal, "treatment.catalog.create",
        entity_type="treatment_catalog", entity_id=item.id,
        summary=f"Added treatment '{item.name}' (৳{item.default_price_paisa / 100:.2f}).",
    )
    return item


def update_catalog_item(
    session: Session, principal: Principal, catalog_id: int, data: TreatmentCatalogInput
) -> TreatmentCatalog:
    if not principal.has(Permission.TREATMENTS_CATALOG_MANAGE):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_CATALOG_MANAGE.value)
    t = session.get(TreatmentCatalog, catalog_id)
    if t is None:
        raise NotFoundError("TreatmentCatalog", catalog_id)
    _validate_catalog(data)
    name = data.name.strip()
    dup = session.scalar(
        select(TreatmentCatalog)
        .where(func.lower(TreatmentCatalog.name) == name.lower())
        .where(TreatmentCatalog.id != catalog_id)
    )
    if dup is not None:
        raise ValidationError(f"A treatment named '{name}' already exists.", field="name")
    t.name = name
    t.description = (data.description or "").strip()
    t.category = (data.category or "").strip()
    t.default_price_paisa = max(0, int(data.default_price_paisa))
    t.is_active = bool(data.is_active)
    session.flush()
    audit_record(
        session, principal, "treatment.catalog.update",
        entity_type="treatment_catalog", entity_id=t.id,
        summary=f"Updated treatment '{t.name}'.",
    )
    return t


def delete_catalog_item(session: Session, principal: Principal, catalog_id: int) -> None:
    """Soft-deactivate; do not physically delete so historical records remain."""
    if not principal.has(Permission.TREATMENTS_CATALOG_MANAGE):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_CATALOG_MANAGE.value)
    t = session.get(TreatmentCatalog, catalog_id)
    if t is None:
        raise NotFoundError("TreatmentCatalog", catalog_id)
    t.is_active = False
    session.flush()
    audit_record(
        session, principal, "treatment.catalog.deactivate",
        entity_type="treatment_catalog", entity_id=t.id,
        summary=f"Deactivated treatment '{t.name}'.",
    )


def _validate_catalog(data: TreatmentCatalogInput) -> None:
    if not data.name or not data.name.strip():
        raise ValidationError("Treatment name is required.", field="name")
    if data.default_price_paisa < 0:
        raise ValidationError("Price cannot be negative.", field="default_price_paisa")


# ----------------------------------------------------------- records


def list_treatments_for_visit(
    session: Session, principal: Principal, visit_id: int
) -> list[TreatmentRecordRow]:
    if not principal.has(Permission.TREATMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_VIEW.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    stmt = (
        select(TreatmentRecord)
        .where(TreatmentRecord.visit_id == visit_id)
        .order_by(TreatmentRecord.id.asc())
    )
    pname = _patient_name(session, v.patient_id)
    return [
        _row_from(r, pname, _dentist_name(session, r.dentist_id))
        for r in session.scalars(stmt)
    ]


def list_treatments_for_patient(
    session: Session, principal: Principal, patient_id: int, *, limit: int = 200
) -> list[TreatmentRecordRow]:
    if not principal.has(Permission.TREATMENTS_VIEW):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_VIEW.value)
    p = session.get(Patient, patient_id)
    if p is None:
        raise NotFoundError("Patient", patient_id)
    stmt = (
        select(TreatmentRecord)
        .where(TreatmentRecord.patient_id == patient_id)
        .order_by(TreatmentRecord.created_at.desc())
        .limit(limit)
    )
    pname = p.name
    return [
        _row_from(r, pname, _dentist_name(session, r.dentist_id))
        for r in session.scalars(stmt)
    ]


def add_treatment_to_visit(
    session: Session, principal: Principal, visit_id: int, data: TreatmentRecordInput
) -> TreatmentRecord:
    if not principal.has(Permission.TREATMENTS_CREATE):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_CREATE.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    if v.closed_at is not None:
        raise ValidationError("Cannot add treatment to a closed visit.")
    if data.tooth_codes:
        _validate_tooth_codes(data.tooth_codes)

    name = data.name_at_service_time.strip()
    price = int(data.price_paisa)
    if data.catalog_id is not None:
        cat = session.get(TreatmentCatalog, data.catalog_id)
        if cat is None:
            raise ValidationError("Selected treatment does not exist.", field="catalog_id")
        if not name:
            name = cat.name
        if not price:
            price = cat.default_price_paisa
    if not name:
        raise ValidationError("Treatment name is required.", field="name_at_service_time")
    if price < 0:
        raise ValidationError("Price cannot be negative.", field="price_paisa")

    rec = TreatmentRecord(
        visit_id=visit_id,
        patient_id=v.patient_id,
        dentist_id=v.dentist_id,
        catalog_id=data.catalog_id,
        name_at_service_time=name,
        description=(data.description or "").strip(),
        tooth_codes=_normalise_tooth_codes(data.tooth_codes),
        price_paisa=price,
        notes=(data.notes or "").strip(),
        created_by=principal.user_id,
    )
    session.add(rec)
    session.flush()
    audit_record(
        session, principal, "treatment.record.create",
        entity_type="treatment_record", entity_id=rec.id,
        summary=f"Added '{rec.name_at_service_time}' to visit {visit_id} (৳{rec.price_paisa / 100:.2f}).",
    )
    return rec


def update_treatment_record(
    session: Session, principal: Principal, record_id: int, data: TreatmentRecordInput
) -> TreatmentRecord:
    if not principal.has(Permission.TREATMENTS_EDIT):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_EDIT.value)
    r = session.get(TreatmentRecord, record_id)
    if r is None:
        raise NotFoundError("TreatmentRecord", record_id)
    v = session.get(Visit, r.visit_id)
    if v is not None and v.closed_at is not None:
        raise ValidationError("Cannot edit a treatment on a closed visit.")
    if data.tooth_codes:
        _validate_tooth_codes(data.tooth_codes)

    name = data.name_at_service_time.strip() if data.name_at_service_time else r.name_at_service_time
    price = int(data.price_paisa) if data.price_paisa else r.price_paisa
    if data.catalog_id is not None and data.catalog_id != r.catalog_id:
        cat = session.get(TreatmentCatalog, data.catalog_id)
        if cat is None:
            raise ValidationError("Selected treatment does not exist.", field="catalog_id")
        r.catalog_id = data.catalog_id
        if not data.name_at_service_time:
            name = cat.name
        if not data.price_paisa:
            price = cat.default_price_paisa
    if price < 0:
        raise ValidationError("Price cannot be negative.", field="price_paisa")
    r.name_at_service_time = name
    r.description = (data.description or r.description).strip()
    if data.tooth_codes is not None:
        r.tooth_codes = _normalise_tooth_codes(data.tooth_codes)
    r.price_paisa = price
    r.notes = (data.notes or r.notes).strip()
    session.flush()
    audit_record(
        session, principal, "treatment.record.update",
        entity_type="treatment_record", entity_id=r.id,
        summary=f"Updated treatment record '{r.name_at_service_time}'.",
    )
    return r


def delete_treatment_record(session: Session, principal: Principal, record_id: int) -> None:
    if not principal.has(Permission.TREATMENTS_EDIT):
        raise PermissionDeniedError(permission=Permission.TREATMENTS_EDIT.value)
    r = session.get(TreatmentRecord, record_id)
    if r is None:
        raise NotFoundError("TreatmentRecord", record_id)
    v = session.get(Visit, r.visit_id)
    if v is not None and v.closed_at is not None:
        raise ValidationError("Cannot remove a treatment from a closed visit.")
    name = r.name_at_service_time
    session.delete(r)
    session.flush()
    audit_record(
        session, principal, "treatment.record.delete",
        entity_type="treatment_record", entity_id=record_id,
        summary=f"Removed treatment '{name}' from visit.",
    )


def visit_total_paisa(session: Session, visit_id: int) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(TreatmentRecord.price_paisa), 0))
            .where(TreatmentRecord.visit_id == visit_id)
        )
        or 0
    )


# ----------------------------------------------------------- helpers


def _row_from(r: TreatmentRecord, patient_name: str, dentist_name: str) -> TreatmentRecordRow:
    return TreatmentRecordRow(
        id=r.id,
        visit_id=r.visit_id,
        patient_id=r.patient_id,
        patient_name=patient_name,
        dentist_id=r.dentist_id,
        dentist_name=dentist_name,
        catalog_id=r.catalog_id,
        name_at_service_time=r.name_at_service_time,
        description=r.description or "",
        tooth_codes=r.tooth_codes or "",
        price_paisa=r.price_paisa or 0,
        notes=r.notes or "",
        created_at=r.created_at,
        created_by=r.created_by,
    )


def _patient_name(session: Session, pid: int) -> str:
    p = session.get(Patient, pid)
    return p.name if p is not None else "(deleted)"


def _dentist_name(session: Session, did: int | None) -> str:
    if did is None:
        return "—"
    d = session.get(Dentist, did)
    return d.name if d is not None else "(deleted)"


_VALID_TEETH = {f"{q}{t}" for q in range(1, 5) for t in range(1, 9)} | {
    f"{q}{t}" for q in range(5, 9) for t in range(1, 6)
}


def _validate_tooth_codes(codes: str) -> None:
    if not codes or not codes.strip():
        return
    for c in _normalise_tooth_codes(codes).split(","):
        if c and c not in _VALID_TEETH:
            raise ValidationError(
                f"Invalid tooth code '{c}'. Use two-digit FDI numbers (e.g. 36, 46, 55).",
                field="tooth_codes",
            )


def _normalise_tooth_codes(codes: str) -> str:
    parts = [p.strip() for p in (codes or "").replace(" ", ",").split(",") if p.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return ",".join(out)
