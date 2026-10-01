"""Clinic profile service: first-run setup and later profile updates."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.errors import ConflictError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.core.validators import validate_email, validate_non_empty, validate_phone
from dentiva.models import ClinicProfile
from dentiva.paths import paths

from .audit_service import record as audit_record

log = logging.getLogger(__name__)


def get_clinic(session: Session) -> ClinicProfile | None:
    return session.scalar(select(ClinicProfile).limit(1))


def is_setup_complete(session: Session) -> bool:
    cp = get_clinic(session)
    return bool(cp and cp.setup_completed)


def save_logo(file_bytes: bytes, original_name: str) -> str:
    """Save a logo file into the data logos directory and return its absolute path."""
    paths.logos_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower() or ".png"
    # Sanitise — allow only image extensions.
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
        raise ValidationError("Unsupported image format. Use PNG, JPG, BMP, GIF, or WEBP.", field="logo")
    target = paths.logos_dir / f"clinic_logo{suffix}"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(file_bytes)
    tmp.replace(target)
    return str(target)


def save_logo_from_path(src_path: str | Path) -> str:
    src = Path(src_path)
    if not src.exists() or not src.is_file():
        raise ValidationError("Logo file not found.", field="logo")
    return save_logo(src.read_bytes(), src.name)


def setup_clinic(
    session: Session,
    *,
    name: str,
    address: str = "",
    phone: str = "",
    email: str = "",
    tagline: str = "",
    logo_path: str = "",
    prescription_footer: str = "",
) -> ClinicProfile:
    """Create or update the single clinic profile row during first-run setup.

    This does NOT mark setup as complete (the setup wizard does so after
    creating the initial dentist(s) and administrator).
    """
    name = validate_non_empty(name, "name", label="Clinic name")
    phone = validate_phone(phone, "phone")
    email = validate_email(email, "email")
    if logo_path and not Path(logo_path).exists():
        raise ValidationError("Logo file could not be found.", field="logo")

    cp = get_clinic(session)
    if cp is None:
        cp = ClinicProfile()
        session.add(cp)

    cp.name = name
    cp.address = address or ""
    cp.phone = phone
    cp.email = email
    cp.tagline = tagline or ""
    cp.logo_path = logo_path or ""
    cp.prescription_footer = prescription_footer or ""
    session.flush()
    audit_record(session, None, "clinic.setup", entity_type="clinic_profile",
                 entity_id=cp.id, summary=f"Clinic profile saved for '{name}'.")
    return cp


def mark_setup_complete(session: Session) -> ClinicProfile:
    cp = get_clinic(session)
    if cp is None:
        raise ConflictError("Clinic profile must be created before setup can be marked complete.")
    cp.setup_completed = True
    session.flush()
    audit_record(session, None, "clinic.setup_complete", entity_type="clinic_profile",
                 entity_id=cp.id, summary="First-run setup completed.")
    return cp


def update_clinic(session: Session, principal: Principal, **fields) -> ClinicProfile:
    from dentiva.core.errors import PermissionDeniedError
    if not principal.has(Permission.CLINIC_PROFILE_MANAGE):
        raise PermissionDeniedError(permission=Permission.CLINIC_PROFILE_MANAGE.value)
    cp = get_clinic(session)
    if cp is None:
        raise ConflictError("Clinic profile does not exist.")
    for k, v in fields.items():
        if hasattr(cp, k):
            setattr(cp, k, v)
    session.flush()
    audit_record(session, principal, "clinic.update", entity_type="clinic_profile",
                 entity_id=cp.id, summary="Clinic profile updated.")
    return cp
