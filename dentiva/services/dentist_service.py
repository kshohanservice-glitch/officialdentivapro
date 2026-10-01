"""Dentist service — CRUD for dentists and designations."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.errors import NotFoundError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.db.seed import DEFAULT_DESIGNATIONS
from dentiva.models import Dentist, Designation

from .audit_service import record as audit_record

log = logging.getLogger(__name__)


def _ensure_designations(session: Session, names: Iterable[str]) -> list[Designation]:
    out: list[Designation] = []
    for name in names:
        cleaned = (name or "").strip()
        if not cleaned:
            continue
        existing = session.scalar(select(Designation).where(Designation.name == cleaned))
        if existing is None:
            existing = Designation(name=cleaned, is_active=True)
            session.add(existing)
            session.flush()
        out.append(existing)
    return out


def _save_image(src_path: str, target_dir_name: str) -> str:
    """Copy a file into the data directory and return the stored path."""
    from pathlib import Path

    from dentiva.core.errors import ValidationError
    from dentiva.paths import paths

    src = Path(src_path)
    if not src.exists() or not src.is_file():
        raise ValidationError("Image file not found.", field="image")
    suffix = src.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
        raise ValidationError("Unsupported image format. Use PNG, JPG, BMP, GIF, or WEBP.", field="image")
    target_dir = paths.logos_dir if target_dir_name == "logos" else paths.data_root / target_dir_name
    target_dir.mkdir(parents=True, exist_ok=True)
    import uuid
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"
    import shutil
    shutil.copy2(src, target)
    return str(target)


def list_dentists(session: Session, principal: Principal, *,
                  include_inactive: bool = False) -> list[Dentist]:
    from dentiva.core.errors import PermissionDeniedError
    # Anyone authenticated can see the dentist list (needed for appointments/visits),
    # but DENTISTS_MANAGE permission is required to edit them.
    if not principal.is_superuser and not principal.has(Permission.VISITS_VIEW) \
       and not principal.has(Permission.APPOINTMENTS_VIEW) \
       and not principal.has(Permission.DENTISTS_MANAGE):
        raise PermissionDeniedError(permission=Permission.VISITS_VIEW.value)
    q = select(Dentist)
    if not include_inactive:
        q = q.where(Dentist.deleted_at.is_(None))
    return list(session.scalars(q.order_by(Dentist.name)))


def get_dentist(session: Session, dentist_id: int) -> Dentist:
    d = session.get(Dentist, dentist_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("Dentist", dentist_id)
    return d


def create_dentist(
    session: Session,
    principal: Optional[Principal],
    *,
    name: str,
    designations: Iterable[str] = (),
    qualifications: str = "",
    certifications: str = "",
    registration_no: str = "",
    phone: str = "",
    email: str = "",
    signature_path: str = "",
    photo_path: str = "",
    notes: str = "",
) -> Dentist:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Dentist name is required.", field="name")
    d = Dentist(
        name=name,
        qualifications=qualifications or "",
        certifications=certifications or "",
        registration_no=registration_no or "",
        phone=phone or "",
        email=email or "",
        signature_path=signature_path or "",
        photo_path=photo_path or "",
        notes=notes or "",
        is_active=True,
    )
    desigs = _ensure_designations(session, designations)
    d.designations = desigs
    session.add(d)
    session.flush()
    # If principal is None this is a setup-wizard creation (pre-login).
    audit_record(session, principal, "dentist.create", entity_type="dentist",
                 entity_id=d.id, summary=f"Dentist '{name}' created.")
    return d


def update_dentist(session: Session, principal: Principal, dentist_id: int, **fields) -> Dentist:
    from dentiva.core.errors import PermissionDeniedError
    if not principal.has(Permission.DENTISTS_MANAGE):
        raise PermissionDeniedError(permission=Permission.DENTISTS_MANAGE.value)
    d = get_dentist(session, dentist_id)
    for k, v in fields.items():
        if k == "designations":
            d.designations = _ensure_designations(session, v or [])
        elif hasattr(d, k):
            setattr(d, k, v)
    session.flush()
    audit_record(session, principal, "dentist.update", entity_type="dentist",
                 entity_id=d.id, summary=f"Dentist '{d.name}' updated.")
    return d


def ensure_default_designations(session: Session) -> None:
    """Populate the default designations set if missing (used by setup)."""
    _ensure_designations(session, DEFAULT_DESIGNATIONS)
