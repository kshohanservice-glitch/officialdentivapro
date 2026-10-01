"""Seed/default data for a fresh Dentiva Pro installation.

This module provides helpers that populate lookup tables (payment methods,
default clinical template options, tooth reference, designations) and the
default role set so that the database is usable immediately after setup.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.permissions import Permission
from dentiva.models import (
    ClinicalTemplateOption,
    Designation,
    PaymentMethod,
    PermissionAssignment,
    Role,
    ToothReference,
)

log = logging.getLogger(__name__)


DEFAULT_ROLES: tuple[dict, ...] = (
    {"name": "Administrator", "description": "Full access to all features.", "is_system": True, "permissions": "ALL"},
    {"name": "Dentist", "description": "Clinical features; no financial reports or user management.", "is_system": True,
     "permissions": [
        Permission.PATIENTS_VIEW, Permission.PATIENTS_CREATE, Permission.PATIENTS_EDIT, Permission.PATIENTS_EXPORT,
        Permission.VISITS_VIEW, Permission.VISITS_CREATE, Permission.VISITS_EDIT,
        Permission.DENTAL_CHART_VIEW, Permission.DENTAL_CHART_EDIT,
        Permission.PRESCRIPTIONS_VIEW, Permission.PRESCRIPTIONS_CREATE, Permission.PRESCRIPTIONS_EDIT, Permission.PRESCRIPTIONS_PRINT,
        Permission.TREATMENTS_VIEW, Permission.TREATMENTS_CREATE, Permission.TREATMENTS_EDIT,
        Permission.APPOINTMENTS_VIEW, Permission.APPOINTMENTS_CREATE, Permission.APPOINTMENTS_EDIT, Permission.APPOINTMENTS_CANCEL,
        Permission.QUEUE_MANAGE, Permission.INVOICES_CREATE, Permission.INVOICES_VIEW, Permission.INVOICES_PRINT,
        Permission.PAYMENTS_CREATE, Permission.PAYMENTS_VIEW,
        Permission.SETTINGS_VIEW, Permission.NOTIFICATIONS_MANAGE, Permission.SEARCH_GLOBAL,
        Permission.ATTACHMENTS_VIEW, Permission.ATTACHMENTS_MANAGE, Permission.VIEW_REPORTS,
     ]},
    {"name": "Receptionist", "description": "Patient intake, appointments, queue, and recording payments.", "is_system": True,
     "permissions": [
        Permission.PATIENTS_VIEW, Permission.PATIENTS_CREATE, Permission.PATIENTS_EDIT, Permission.PATIENTS_EXPORT,
        Permission.VISITS_VIEW, Permission.VISITS_CREATE,
        Permission.APPOINTMENTS_VIEW, Permission.APPOINTMENTS_CREATE, Permission.APPOINTMENTS_EDIT, Permission.APPOINTMENTS_CANCEL,
        Permission.QUEUE_MANAGE,
        Permission.INVOICES_CREATE, Permission.INVOICES_VIEW, Permission.INVOICES_PRINT,
        Permission.PAYMENTS_CREATE, Permission.PAYMENTS_VIEW,
        Permission.INVENTORY_VIEW,
        Permission.SETTINGS_VIEW, Permission.NOTIFICATIONS_MANAGE, Permission.SEARCH_GLOBAL,
        Permission.ATTACHMENTS_VIEW, Permission.ATTACHMENTS_MANAGE, Permission.PRINTERS_MANAGE,
     ]},
    {"name": "Assistant", "description": "Clinical assisting; view-only access to patients/queue/inventory.", "is_system": True,
     "permissions": [
        Permission.PATIENTS_VIEW, Permission.VISITS_VIEW,
        Permission.APPOINTMENTS_VIEW, Permission.QUEUE_MANAGE,
        Permission.DENTAL_CHART_VIEW, Permission.PRESCRIPTIONS_VIEW, Permission.TREATMENTS_VIEW,
        Permission.INVENTORY_VIEW, Permission.SETTINGS_VIEW, Permission.SEARCH_GLOBAL,
        Permission.ATTACHMENTS_VIEW,
     ]},
    {"name": "Accountant", "description": "Financial reports, accounting entries, payment tracking.", "is_system": True,
     "permissions": [
        Permission.PATIENTS_VIEW,
        Permission.INVOICES_VIEW, Permission.INVOICES_PRINT, Permission.INVOICES_VOID,
        Permission.PAYMENTS_VIEW, Permission.PAYMENTS_CREATE, Permission.PAYMENTS_REFUND,
        Permission.ACCOUNTING_VIEW, Permission.ACCOUNTING_MANAGE,
        Permission.FINANCIAL_REPORTS_VIEW, Permission.FINANCIAL_SETTINGS_MANAGE,
        Permission.INVENTORY_VIEW, Permission.INVENTORY_ADJUST,
        Permission.SETTINGS_VIEW, Permission.VIEW_REPORTS, Permission.DATA_EXPORT,
        Permission.SEARCH_GLOBAL, Permission.BACKUP_CREATE, Permission.BACKUP_CONFIGURE,
     ]},
)


DEFAULT_PAYMENT_METHODS: tuple[dict, ...] = (
    {"code": "cash",    "name": "Cash",    "sort_order": 1},
    {"code": "bkash",   "name": "bKash",   "sort_order": 2},
    {"code": "nagad",   "name": "Nagad",   "sort_order": 3},
    {"code": "rocket",  "name": "Rocket",  "sort_order": 4},
    {"code": "upay",    "name": "Upay",    "sort_order": 5},
    {"code": "card",    "name": "Card",    "sort_order": 6},
    {"code": "bank",    "name": "Bank Transfer", "sort_order": 7},
    {"code": "other",   "name": "Other",   "sort_order": 99},
)


DEFAULT_DESIGNATIONS: tuple[str, ...] = ("BDS", "DDS", "DMD", "FCPS", "MS", "MDS", "PhD", "Consultant")


CLINICAL_CC: tuple[str, ...] = (
    "Pain", "Swelling", "Bleeding gums", "Bad breath", "Sensitivity to cold",
    "Sensitivity to hot", "Broken tooth", "Mobile tooth", "Difficulty chewing",
    "Gum swelling", "Tooth discoloration",
)
CLINICAL_OE: tuple[str, ...] = (
    "Generalized caries", "Gingival caries", "Gingivitis", "Periodontal pocket",
    "Periodontitis", "Pulpitis", "Impacted tooth (wisdom)", "Dry socket",
    "Attrition", "Erosion", "Mobility grade I", "Mobility grade II", "Mobility grade III",
    "Fractured tooth", "Halitosis", "BDR (Basic Dental Restoration)",
    "BDC (Basic Dental Care)",
)
CLINICAL_ADVICE: tuple[str, ...] = (
    "Maintain oral hygiene", "Brush twice daily", "Use soft bristle brush",
    "Warm saline rinse", "Avoid hot/cold/sweet", "Medication as prescribed",
    "Review after 7 days", "Follow up if pain persists", "Soft diet for 3 days",
    "Avoid smoking/tobacco", "Regular dental check-up every 6 months",
)


def _seed_payment_methods(session: Session) -> None:
    for m in DEFAULT_PAYMENT_METHODS:
        existing = session.scalar(select(PaymentMethod).where(PaymentMethod.code == m["code"]))
        if existing is None:
            session.add(PaymentMethod(**m, is_active=True))


def _seed_designations(session: Session) -> None:
    for name in DEFAULT_DESIGNATIONS:
        existing = session.scalar(select(Designation).where(Designation.name == name))
        if existing is None:
            session.add(Designation(name=name, is_active=True))


def _seed_roles(session: Session) -> None:
    for role_def in DEFAULT_ROLES:
        existing = session.scalar(select(Role).where(Role.name == role_def["name"]))
        if existing is None:
            role = Role(
                name=role_def["name"],
                description=role_def["description"],
                is_system=role_def["is_system"],
            )
            session.add(role)
            session.flush()
            perms = role_def["permissions"]
            if perms == "ALL":
                perms = list(Permission)
            # Deduplicate
            seen = set()
            for perm in perms:
                if perm.value in seen:
                    continue
                seen.add(perm.value)
                session.add(PermissionAssignment(role_id=role.id, permission=perm.value))


def _seed_clinical_options(session: Session) -> None:
    existing_count = session.scalar(select(ClinicalTemplateOption).limit(1))
    if existing_count:
        return
    for section, items in (
        ("cc", CLINICAL_CC),
        ("oe", CLINICAL_OE),
        ("advice", CLINICAL_ADVICE),
    ):
        for idx, text in enumerate(items):
            session.add(ClinicalTemplateOption(
                section_key=section, display_text=text, sort_order=idx, is_active=True,
            ))


def _seed_tooth_reference(session: Session) -> None:
    """Populate the tooth reference table with FDI notation (adult 11-48 and pediatric 51-85)."""
    existing = session.scalar(select(ToothReference).limit(1))
    if existing:
        return
    # FDI adult quadrants: 1 upper-right, 2 upper-left, 3 lower-left, 4 lower-right.
    # Numbering per tooth 1-8 starting at midline.
    adult = []
    # Tooth names simplified for reference.
    for quadrant in (1, 2, 3, 4):
        for tooth in range(1, 9):
            code = f"{quadrant}{tooth}"
            # Provide ADA (universal) equivalent for convenience.
            ada = _fdi_to_ada(quadrant, tooth, pediatric=False)
            name = _tooth_name(quadrant, tooth, pediatric=False)
            adult.append((code, name, quadrant, False, ada))
    # Pediatric (5-8 quadrants), teeth 1-5 per quadrant.
    for quadrant in (5, 6, 7, 8):
        for tooth in range(1, 6):
            code = f"{quadrant}{tooth}"
            ada = _fdi_to_ada(quadrant, tooth, pediatric=True)
            name = _tooth_name(quadrant, tooth, pediatric=True)
            adult.append((code, name, quadrant, True, ada))
    # Order for chart drawing: upper right → upper left, then lower right → lower left.
    order = 1
    # Insert in display order: upper (Q2 then Q1), then lower (Q3 then Q4) for adult, same for pediatric.
    ordered: list[tuple] = []
    for q, teeth in [(2, range(1, 9)), (1, range(8, 0, -1)),
                     (3, range(1, 9)), (4, range(8, 0, -1))]:
        for t in teeth:
            code = f"{q}{t}"
            match = next(row for row in adult if row[0] == code)
            ordered.append((*match, order))
            order += 1
    for q, teeth in [(6, range(1, 6)), (5, range(5, 0, -1)),
                     (7, range(1, 6)), (8, range(5, 0, -1))]:
        for t in teeth:
            code = f"{q}{t}"
            match = next(row for row in adult if row[0] == code)
            ordered.append((*match, order))
            order += 1
    for code, name, quadrant, is_ped, ada, idx in ordered:
        session.add(ToothReference(
            code=code, name=name, quadrant=quadrant,
            is_pediatric=is_ped, order_index=idx, notation_ada=ada,
        ))


def _tooth_name(quadrant: int, tooth: int, *, pediatric: bool) -> str:
    if pediatric:
        base = {1: "Primary central incisor", 2: "Primary lateral incisor",
                3: "Primary canine", 4: "Primary first molar", 5: "Primary second molar"}
        return base.get(tooth, f"Tooth {quadrant}{tooth}")
    # Adult
    if tooth == 1:
        return "Central incisor"
    if tooth == 2:
        return "Lateral incisor"
    if tooth == 3:
        return "Canine"
    if tooth == 4:
        return "First premolar"
    if tooth == 5:
        return "Second premolar"
    if tooth == 6:
        return "First molar"
    if tooth == 7:
        return "Second molar"
    if tooth == 8:
        return "Third molar (wisdom)"
    return f"Tooth {quadrant}{tooth}"


def _fdi_to_ada(quadrant: int, tooth: int, *, pediatric: bool) -> str:
    """FDI → Universal (ADA) notation, used for reference/display only."""
    if not pediatric:
        adult_map = {
            (1, 8): "1", (1, 7): "2", (1, 6): "3", (1, 5): "4", (1, 4): "5",
            (1, 3): "6", (1, 2): "7", (1, 1): "8",
            (2, 1): "9", (2, 2): "10", (2, 3): "11", (2, 4): "12", (2, 5): "13",
            (2, 6): "14", (2, 7): "15", (2, 8): "16",
            (3, 1): "24", (3, 2): "23", (3, 3): "22", (3, 4): "21", (3, 5): "20",
            (3, 6): "19", (3, 7): "18", (3, 8): "17",
            (4, 8): "32", (4, 7): "31", (4, 6): "30", (4, 5): "29", (4, 4): "28",
            (4, 3): "27", (4, 2): "26", (4, 1): "25",
        }
        return adult_map.get((quadrant, tooth), "")
    # Pediatric ADA A-T
    ped_map = {
        (5, 5): "A", (5, 4): "B", (5, 3): "C", (5, 2): "D", (5, 1): "E",
        (6, 1): "F", (6, 2): "G", (6, 3): "H", (6, 4): "I", (6, 5): "J",
        (7, 1): "T", (7, 2): "S", (7, 3): "R", (7, 4): "Q", (7, 5): "P",
        (8, 5): "K", (8, 4): "L", (8, 3): "M", (8, 2): "N", (8, 1): "O",
    }
    return ped_map.get((quadrant, tooth), "")


def seed_defaults(session: Session) -> None:
    """Populate default lookup rows if they don't yet exist."""
    _seed_payment_methods(session)
    _seed_designations(session)
    _seed_roles(session)
    _seed_clinical_options(session)
    _seed_tooth_reference(session)
    session.flush()
