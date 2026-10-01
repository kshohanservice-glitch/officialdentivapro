"""Visit & dental-chart service: open/close visits, record tooth findings,
list visit history, and chart queries.

Per visit, the dentist selects a tooth and marks a condition (caries,
filling, missing, RCT, crown, etc.). The chart widget always shows the
*latest* finding per tooth across closed visits (the current state of the
mouth), but every historical finding is preserved (audit / clinical
history).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.dates import format_date, local_now
from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import (
    DentalChartFinding,
    Dentist,
    ToothReference,
    Visit,
)

from .audit_service import record as audit_record
from .patient_service import get_patient, record_visit

# Recognised clinical finding codes. Chart widget populates its palette
# from this list (order is palette order).
FINDINGS: tuple[tuple[str, str, str], ...] = (
    # code,         label,            color
    ("healthy",     "Healthy",        "#12B76A"),
    ("caries",      "Caries",         "#F04438"),
    ("filled",      "Filled",         "#2E90FA"),
    ("missing",     "Missing",        "#667085"),
    ("rct",         "Root Canal",     "#6941C6"),
    ("crown",       "Crown",          "#F79009"),
    ("bridge",      "Bridge",         "#B54708"),
    ("implant",     "Implant",        "#027A48"),
    ("extraction",  "Extraction",     "#B42318"),
    ("impacted",    "Impacted",       "#475467"),
    ("sealant",     "Sealant",        "#06AED4"),
    ("fracture",    "Fracture",       "#D92D20"),
    ("abscess",     "Abscess",        "#DC6803"),
    ("plaque",      "Plaque/Calculus","#4E5BA6"),
)
FINDING_CODE_TO_COLOR: dict[str, str] = {code: color for code, _label, color in FINDINGS}
FINDING_CODE_TO_LABEL: dict[str, str] = {code: label for code, label, _color in FINDINGS}


def ada_equivalent(fdi: str) -> str:
    """Return ADA Universal notation for a given FDI tooth code, or ''."""
    if len(fdi) != 2 or not fdi.isdigit():
        return ""
    q, n = int(fdi[0]), int(fdi[1])
    adult_map = {
        # FDI quadrant 1 (upper right): 18→11 = ADA 1→8.
        1: {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1},
        # FDI quadrant 2 (upper left): 21→28 = ADA 9→16.
        2: {1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 14, 7: 15, 8: 16},
        # FDI quadrant 3 (lower left): 38→31 = ADA 17→24.
        3: {1: 24, 2: 23, 3: 22, 4: 21, 5: 20, 6: 19, 7: 18, 8: 17},
        # FDI quadrant 4 (lower right): 41→48 = ADA 25→32.
        4: {1: 25, 2: 26, 3: 27, 4: 28, 5: 29, 6: 30, 7: 31, 8: 32},
    }
    ped_map = {
        5: {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"},
        6: {1: "F", 2: "G", 3: "H", 4: "I", 5: "J"},
        7: {1: "T", 2: "S", 3: "R", 4: "Q", 5: "P"},
        8: {1: "K", 2: "L", 3: "M", 4: "N", 5: "O"},
    }
    if q in adult_map and n in adult_map[q]:
        return str(adult_map[q][n])
    if q in ped_map and n in ped_map[q]:
        return str(ped_map[q][n])
    return ""


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class VisitInput:
    dentist_id: int | None = None
    visit_date: dt.datetime | None = None
    reason: str = ""
    chief_complaint: str = ""
    on_examination: str = ""
    advice: str = ""
    notes: str = ""
    is_pediatric: bool = False  # which chart layout to use
    # tooth_code -> finding_code  (only changed teeth need be listed)
    findings: dict[str, str] = field(default_factory=dict)


@dataclass
class FindingRow:
    tooth_code: str
    finding: str
    surface: str
    notes: str


@dataclass
class VisitSummary:
    id: int
    visit_date: dt.datetime
    dentist_name: str
    reason: str
    status: str
    chief_complaint: str
    on_examination: str
    advice: str
    notes: str
    findings: list[FindingRow]


# ---------------------------------------------------------------------------
# Listing / retrieval
# ---------------------------------------------------------------------------

def list_visits(session: Session, principal: Principal, patient_id: int, *, limit: int = 200) -> list[VisitSummary]:
    """Return visits for a patient (newest first) with their findings."""
    if not principal.has(Permission.VISITS_VIEW):
        raise PermissionDeniedError(permission=Permission.VISITS_VIEW.value)
    get_patient(session, patient_id)  # ensure patient exists
    rows = session.execute(
        select(
            Visit.id,
            Visit.visit_date,
            Visit.reason,
            Visit.status,
            Visit.chief_complaint,
            Visit.on_examination,
            Visit.advice,
            Visit.notes,
            Dentist.name.label("dentist_name"),
        )
        .outerjoin(Dentist, Dentist.id == Visit.dentist_id)
        .where(Visit.patient_id == patient_id)
        .order_by(Visit.visit_date.desc())
        .limit(limit)
    ).all()
    result: list[VisitSummary] = []
    for r in rows:
        findings = list(session.scalars(
            select(DentalChartFinding).where(DentalChartFinding.visit_id == r.id)
        ))
        result.append(VisitSummary(
            id=r.id,
            visit_date=r.visit_date,
            dentist_name=r.dentist_name or "—",
            reason=r.reason or "",
            status=r.status or "",
            chief_complaint=r.chief_complaint or "",
            on_examination=r.on_examination or "",
            advice=r.advice or "",
            notes=r.notes or "",
            findings=[FindingRow(f.tooth_code, f.finding, f.surface or "", f.notes or "") for f in findings],
        ))
    return result


def get_visit(session: Session, principal: Principal, visit_id: int) -> VisitSummary:
    if not principal.has(Permission.VISITS_VIEW):
        raise PermissionDeniedError(permission=Permission.VISITS_VIEW.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    findings = list(session.scalars(
        select(DentalChartFinding).where(DentalChartFinding.visit_id == visit_id)
    ))
    dentist_name = ""
    if v.dentist_id is not None:
        d = session.get(Dentist, v.dentist_id)
        dentist_name = d.name if d else ""
    return VisitSummary(
        id=v.id,
        visit_date=v.visit_date,
        dentist_name=dentist_name or "—",
        reason=v.reason or "",
        status=v.status or "",
        chief_complaint=v.chief_complaint or "",
        on_examination=v.on_examination or "",
        advice=v.advice or "",
        notes=v.notes or "",
        findings=[FindingRow(f.tooth_code, f.finding, f.surface or "", f.notes or "") for f in findings],
    )


def latest_chart_state(session: Session, patient_id: int, *, pediatric: bool = False) -> dict[str, str]:
    """Return the most recent finding per tooth across all closed + open visits,
    used to paint the "current state" background of the chart.
    """
    # Get the latest finding per tooth. SQLAlchemy Core group-by approach.
    # We approximate this in Python to keep it portable across SQLite/PostgreSQL
    # without window functions — visits are few per patient.
    stmt = (
        select(DentalChartFinding)
        .join(Visit, Visit.id == DentalChartFinding.visit_id)
        .where(Visit.patient_id == patient_id)
        .order_by(DentalChartFinding.tooth_code.asc(), Visit.visit_date.desc(), DentalChartFinding.id.desc())
    )
    findings = list(session.scalars(stmt))
    state: dict[str, str] = {}
    for f in findings:
        if f.tooth_code not in state:
            state[f.tooth_code] = f.finding
    return state


def list_teeth(session: Session, *, pediatric: bool = False) -> list[ToothReference]:
    """Return tooth references ordered for chart drawing. If pediatric is
    True, return only pediatric quadrants; otherwise adult. Both layouts
    share the same widget."""
    stmt = select(ToothReference).where(ToothReference.is_pediatric.is_(pediatric)).order_by(ToothReference.order_index)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def create_visit(session: Session, principal: Principal, patient_id: int, data: VisitInput) -> Visit:
    if not principal.has(Permission.VISITS_CREATE):
        raise PermissionDeniedError(permission=Permission.VISITS_CREATE.value)
    patient = get_patient(session, patient_id)
    dentist = None
    if data.dentist_id is not None:
        dentist = session.get(Dentist, data.dentist_id)
        if dentist is None or (hasattr(dentist, "deleted_at") and dentist.deleted_at is not None):
            raise ValidationError("Selected dentist does not exist.", field="dentist_id")
    visit_date = data.visit_date or local_now()
    v = Visit(
        patient_id=patient.id,
        dentist_id=dentist.id if dentist else None,
        visit_date=visit_date,
        reason=(data.reason or "").strip(),
        chief_complaint=(data.chief_complaint or "").strip(),
        on_examination=(data.on_examination or "").strip(),
        advice=(data.advice or "").strip(),
        notes=(data.notes or "").strip(),
        status="open",
        created_by=principal.user_id,
    )
    session.add(v)
    session.flush()
    _apply_findings(session, principal, v, data.findings)
    record_visit(session, patient.id, when=visit_date)
    audit_record(
        session, principal, "visit.create",
        entity_type="visit", entity_id=v.id,
        summary=f"Opened visit for {patient.name} on {format_date(visit_date.date())}.",
    )
    return v


def update_visit(session: Session, principal: Principal, visit_id: int, data: VisitInput) -> Visit:
    if not principal.has(Permission.VISITS_EDIT):
        raise PermissionDeniedError(permission=Permission.VISITS_EDIT.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    if v.status == "closed":
        raise ValidationError("Closed visits cannot be edited. Re-open first.")
    if data.dentist_id is not None and data.dentist_id != v.dentist_id:
        d = session.get(Dentist, data.dentist_id)
        if d is None:
            raise ValidationError("Selected dentist does not exist.", field="dentist_id")
        v.dentist_id = d.id
    if data.visit_date is not None:
        v.visit_date = data.visit_date
    v.reason = (data.reason or "").strip()
    v.chief_complaint = (data.chief_complaint or "").strip()
    v.on_examination = (data.on_examination or "").strip()
    v.advice = (data.advice or "").strip()
    v.notes = (data.notes or "").strip()
    _apply_findings(session, principal, v, data.findings)
    session.flush()
    audit_record(session, principal, "visit.update", entity_type="visit", entity_id=v.id,
                 summary="Updated visit notes/findings.")
    return v


def close_visit(session: Session, principal: Principal, visit_id: int) -> Visit:
    if not principal.has(Permission.VISITS_EDIT):
        raise PermissionDeniedError(permission=Permission.VISITS_EDIT.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    if v.status == "closed":
        return v
    v.status = "closed"
    v.closed_at = local_now()
    session.flush()
    audit_record(session, principal, "visit.close", entity_type="visit", entity_id=v.id,
                 summary="Closed visit.")
    return v


def set_tooth_finding(session: Session, principal: Principal, visit_id: int, tooth_code: str, finding_code: str) -> DentalChartFinding:
    """Add or replace the finding for a single tooth on an open visit."""
    if not principal.has(Permission.DENTAL_CHART_EDIT):
        raise PermissionDeniedError(permission=Permission.DENTAL_CHART_EDIT.value)
    v = session.get(Visit, visit_id)
    if v is None:
        raise NotFoundError("Visit", visit_id)
    if v.status == "closed":
        raise ValidationError("Cannot modify a closed visit's chart.")
    _apply_findings(session, principal, v, {tooth_code: finding_code})
    session.flush()
    f = session.scalar(
        select(DentalChartFinding).where(
            DentalChartFinding.visit_id == visit_id,
            DentalChartFinding.tooth_code == tooth_code,
        ).order_by(DentalChartFinding.id.desc()).limit(1)
    )
    return f  # type: ignore[return-value]


def _apply_findings(session: Session, principal: Principal, visit: Visit, findings: dict[str, str]) -> None:
    """Validate and persist a dict of {tooth_code: finding_code} for a visit.

    Existing findings for those teeth on this visit are replaced; teeth not
    mentioned are left untouched. Passing finding_code='healthy' removes any
    existing non-healthy finding on that tooth for this visit.
    """
    if not findings:
        return
    # Validate codes
    valid_teeth = {t.code for t in list(session.scalars(select(ToothReference)))}
    valid_findings = set(FINDING_CODE_TO_COLOR.keys())
    for tooth_code, code in findings.items():
        if tooth_code not in valid_teeth:
            raise ValidationError(f"Unknown tooth code: {tooth_code}", field="findings")
        if code not in valid_findings:
            raise ValidationError(f"Unknown finding: {code}", field="findings")
    # For each tooth in the dict, remove previous entries for this visit
    # and (unless 'healthy') insert a new one.
    for tooth_code, code in findings.items():
        olds = list(session.scalars(
            select(DentalChartFinding).where(
                DentalChartFinding.visit_id == visit.id,
                DentalChartFinding.tooth_code == tooth_code,
            )
        ))
        for o in olds:
            session.delete(o)
        if code != "healthy":
            session.add(DentalChartFinding(
                visit_id=visit.id,
                tooth_code=tooth_code,
                finding=code,
                surface="",
                notes="",
                created_by=principal.user_id,
            ))
