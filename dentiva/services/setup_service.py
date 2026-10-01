"""First-run setup wizard orchestration.

Atomic multi-step setup: clinic profile → dentist(s) → admin user → mark
complete. The entire operation runs inside a single transaction so partial
failures never leave the database half-configured.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.auth.password import DEFAULT_ROUNDS, hash_password
from dentiva.core.errors import ValidationError
from dentiva.core.permissions import Principal
from dentiva.db.seed import seed_defaults
from dentiva.models import ClinicProfile, Dentist, Role, User

from .audit_service import record as audit_record
from .clinic_service import (
    is_setup_complete,
    mark_setup_complete,
    save_logo_from_path,
    setup_clinic,
)
from .dentist_service import _ensure_designations

log = logging.getLogger(__name__)


@dataclass
class DentistSetupInput:
    name: str
    designations: list[str] = field(default_factory=list)
    qualifications: str = ""
    certifications: str = ""
    registration_no: str = ""
    phone: str = ""
    email: str = ""
    signature_path: str = ""
    photo_path: str = ""
    notes: str = ""


@dataclass
class SetupInput:
    clinic_name: str
    admin_username: str
    admin_password: str
    admin_display_name: str = ""
    clinic_address: str = ""
    clinic_phone: str = ""
    clinic_email: str = ""
    clinic_tagline: str = ""
    clinic_logo_path: str = ""
    prescription_footer: str = ""
    dentists: list[DentistSetupInput] = field(default_factory=list)


def run_setup(session: Session, data: SetupInput) -> ClinicProfile:
    """Execute the full first-run setup inside one transaction."""
    if is_setup_complete(session):
        raise ValidationError("Setup has already been completed.", field="_global")
    # Validate inputs BEFORE writing anything so a validation error rolls back
    # cleanly (UnitOfWork will roll back; we double-check here to raise a clear
    # error before any DB flush).
    if not (data.clinic_name or "").strip():
        raise ValidationError("Clinic name is required.", field="clinic_name")
    if not data.dentists:
        raise ValidationError("Please add at least one dentist before completing setup.",
                              field="dentists")
    if len(data.admin_username or "") < 3:
        raise ValidationError("Admin username must be at least 3 characters.", field="admin_username")
    if len(data.admin_password or "") < 6:
        raise ValidationError("Admin password must be at least 6 characters.", field="admin_password")

    # Ensure lookup tables are populated.
    seed_defaults(session)

    # 1. Clinic profile.
    logo_stored = ""
    if data.clinic_logo_path:
        logo_stored = save_logo_from_path(data.clinic_logo_path)
    cp = setup_clinic(
        session,
        name=data.clinic_name,
        address=data.clinic_address,
        phone=data.clinic_phone,
        email=data.clinic_email,
        tagline=data.clinic_tagline,
        logo_path=logo_stored,
        prescription_footer=data.prescription_footer,
    )

    # 2. Dentists.
    created_dentists: list[Dentist] = []
    for d_in in data.dentists:
        if not (d_in.name or "").strip():
            raise ValidationError("Each dentist must have a name.", field="dentist_name")
        d = Dentist(
            name=d_in.name.strip(),
            qualifications=d_in.qualifications or "",
            certifications=d_in.certifications or "",
            registration_no=d_in.registration_no or "",
            phone=d_in.phone or "",
            email=d_in.email or "",
            signature_path=d_in.signature_path or "",
            photo_path=d_in.photo_path or "",
            notes=d_in.notes or "",
            is_active=True,
        )
        d.designations = _ensure_designations(session, d_in.designations)
        session.add(d)
        session.flush()
        created_dentists.append(d)
        audit_record(session, None, "dentist.create", entity_type="dentist", entity_id=d.id,
                     summary=f"Dentist '{d.name}' created during setup.")

    # 3. Initial administrator user.
    admin_role = session.scalar(select(Role).where(Role.name == "Administrator"))
    admin_user = User(
        username=data.admin_username.strip().lower(),
        password_hash=hash_password(data.admin_password, rounds=DEFAULT_ROUNDS),
        display_name=data.admin_display_name or data.admin_username,
        role_id=admin_role.id if admin_role else None,
        is_superuser=True,
        is_active=True,
    )
    session.add(admin_user)
    session.flush()

    # 4. Mark setup complete.
    mark_setup_complete(session)

    principal = Principal(
        user_id=admin_user.id,
        username=admin_user.username,
        display_name=admin_user.display_name,
        permissions=list(admin_user.permissions_list()),
        is_superuser=True,
    )
    audit_record(session, principal, "setup.complete", entity_type="clinic_profile",
                 entity_id=cp.id,
                 summary=f"Setup completed with {len(created_dentists)} dentist(s).")
    return cp
