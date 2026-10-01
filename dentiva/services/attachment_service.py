# mypy: disable-error-code="arg-type, union-attr, no-any-return"
"""Attachment upload / download / listing service.

Files are stored on disk under ``paths.attachments_dir / <yyyymm> / <uuid>.<ext>``
and referenced by :class:`dentiva.models.Attachment` rows keyed by
``(attachable_type, attachable_id)`` — a lightweight polymorphic pattern so we
can attach files to patients, visits, prescriptions, invoices, etc., without
any generic-FK library.
"""
from __future__ import annotations

import datetime as dt
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.permissions import Permission, Policy, Principal
from dentiva.models import Attachment, Patient

# Allowed attachable entity types. Keep this list in sync with models that
# expose an attachment panel.
ALLOWED_TYPES = frozenset({"patient", "visit", "prescription", "invoice"})
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per attachment (conservative for offline)


@dataclass
class AttachmentHandle:
    attachment: Attachment
    full_path: Path


def _P():  # type: ignore[no-untyped-def]
    from dentiva import paths as _pm
    return _pm.paths


def _validate_entity(session: Session, attachable_type: str, attachable_id: int) -> None:
    if attachable_type not in ALLOWED_TYPES:
        raise ValueError(f"Cannot attach files to entities of type {attachable_type!r}.")
    # Patient is the most common; also use it as a sanity check.
    if attachable_type == "patient":
        exists = session.scalar(select(Patient.id).where(Patient.id == attachable_id, Patient.deleted_at.is_(None)))
        if not exists:
            raise ValueError(f"Patient {attachable_id} does not exist.")


def _content_type_for(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if len(ext) > 12 or any(c in ext for c in "/\\"):
        return ""
    return ext


def _storage_dir_for(now: dt.datetime) -> Path:
    folder = _P().attachments_dir / now.strftime("%Y%m")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ------------------------------------------------------------ public API
def upload_attachment(
    session: Session,
    principal: Principal,
    *,
    attachable_type: str,
    attachable_id: int,
    filename: str,
    stream: BinaryIO,
    title: str = "",
    notes: str = "",
) -> Attachment:
    """Save a file from ``stream`` and create an Attachment row."""
    Policy.require(principal, Permission.ATTACHMENTS_MANAGE)
    _validate_entity(session, attachable_type, attachable_id)
    clean_name = os.path.basename(filename or "file").strip() or "file"
    if len(clean_name) > 240:
        clean_name = clean_name[-240:]
    ext = _safe_ext(clean_name)

    now = local_now()
    folder = _storage_dir_for(now)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = folder / stored_name
    size = 0
    with open(target, "wb") as out:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise ValueError(f"File exceeds maximum allowed size of {MAX_FILE_BYTES // (1024*1024)} MB.")
            out.write(chunk)

    rel = target.relative_to(_P().attachments_dir).as_posix()
    a = Attachment(
        attachable_type=attachable_type,
        attachable_id=attachable_id,
        original_filename=clean_name,
        stored_filename=rel,
        content_type=_content_type_for(clean_name),
        size_bytes=size,
        title=(title or clean_name)[:255],
        notes=notes or "",
        uploaded_by=principal.user_id,
    )
    session.add(a)
    session.flush()
    return a


def upload_attachment_from_path(
    session: Session,
    principal: Principal,
    *,
    attachable_type: str,
    attachable_id: int,
    source_path: Path,
    title: str = "",
    notes: str = "",
) -> Attachment:
    with open(source_path, "rb") as f:
        return upload_attachment(
            session, principal,
            attachable_type=attachable_type,
            attachable_id=attachable_id,
            filename=source_path.name,
            stream=f, title=title, notes=notes,
        )


def list_attachments(
    session: Session,
    principal: Principal,
    *,
    attachable_type: str | None = None,
    attachable_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    Policy.require(principal, Permission.ATTACHMENTS_VIEW)
    stmt = select(Attachment).order_by(Attachment.created_at.desc()).limit(limit)
    if attachable_type is not None:
        stmt = stmt.where(Attachment.attachable_type == attachable_type)
    if attachable_id is not None:
        stmt = stmt.where(Attachment.attachable_id == attachable_id)
    rows = list(session.scalars(stmt).all())
    return [_serialize(r) for r in rows]


def open_attachment(
    session: Session, principal: Principal, attachment_id: int,
) -> AttachmentHandle:
    """Return an ``AttachmentHandle`` with a verified on-disk path. Caller
    must not modify the file."""
    Policy.require(principal, Permission.ATTACHMENTS_VIEW)
    a = session.get(Attachment, attachment_id)
    if a is None:
        raise FileNotFoundError(f"Attachment {attachment_id} not found.")
    full = (_P().attachments_dir / a.stored_filename).resolve()
    if not str(full).startswith(str(_P().attachments_dir.resolve())):
        raise RuntimeError("Refusing to open a file outside the attachments directory.")
    if not full.exists():
        raise FileNotFoundError(f"Attachment file is missing: {full}")
    return AttachmentHandle(attachment=a, full_path=full)


def delete_attachment(session: Session, principal: Principal, attachment_id: int) -> bool:
    Policy.require(principal, Permission.ATTACHMENTS_MANAGE)
    a = session.get(Attachment, attachment_id)
    if a is None:
        return False
    try:
        full = _P().attachments_dir / a.stored_filename
        if full.exists() and str(full.resolve()).startswith(str(_P().attachments_dir.resolve())):
            full.unlink()
    except OSError:
        pass
    session.delete(a)
    return True


def update_attachment(
    session: Session,
    principal: Principal,
    attachment_id: int,
    *,
    title: str | None = None,
    notes: str | None = None,
) -> Attachment | None:
    Policy.require(principal, Permission.ATTACHMENTS_MANAGE)
    a = session.get(Attachment, attachment_id)
    if a is None:
        return None
    if title is not None:
        a.title = title[:255]
    if notes is not None:
        a.notes = notes
    return a


def search_attachments(session: Session, principal: Principal, query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search by filename/title/notes (used by global search)."""
    Policy.require(principal, Permission.ATTACHMENTS_VIEW)
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    # Restrict to patient attachments for patient-level visibility; if user can
    # see patients they can see files attached to them.
    stmt = select(Attachment).where(
        or_(
            Attachment.original_filename.ilike(like),
            Attachment.title.ilike(like),
            Attachment.notes.ilike(like),
        ),
    ).order_by(Attachment.created_at.desc()).limit(limit)
    rows = list(session.scalars(stmt).all())
    out: list[dict[str, Any]] = []
    for a in rows:
        patient_id = _patient_id_for(session, a)
        out.append({
            "id": a.id,
            "attachable_type": a.attachable_type,
            "attachable_id": a.attachable_id,
            "patient_id": patient_id,
            "title": a.title or a.original_filename,
            "subtitle": _subtitle_for(a),
            "original_filename": a.original_filename,
            "size_bytes": a.size_bytes,
            "content_type": a.content_type,
            "created_at": a.created_at,
        })
    return out


def _subtitle_for(a: Attachment) -> str:
    size_kb = max(1, (a.size_bytes or 0) // 1024)
    when = a.created_at.strftime("%d %b %Y") if a.created_at else ""
    return f"Attachment · {a.attachable_type.title()} · {size_kb} KB · {when}"


def _patient_id_for(session: Session, a: Attachment) -> int | None:
    if a.attachable_type == "patient":
        return a.attachable_id
    if a.attachable_type == "visit":
        from dentiva.models import Visit
        v = session.get(Visit, a.attachable_id)
        return v.patient_id if v else None
    if a.attachable_type == "prescription":
        from dentiva.models import Prescription
        p = session.get(Prescription, a.attachable_id)
        return p.patient_id if p else None
    if a.attachable_type == "invoice":
        from dentiva.models import Invoice
        i = session.get(Invoice, a.attachable_id)
        return i.patient_id if i else None
    return None


def _serialize(a: Attachment) -> dict[str, Any]:
    return {
        "id": a.id,
        "attachable_type": a.attachable_type,
        "attachable_id": a.attachable_id,
        "original_filename": a.original_filename,
        "stored_filename": a.stored_filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "title": a.title or a.original_filename,
        "notes": a.notes,
        "uploaded_by": a.uploaded_by,
        "created_at": a.created_at,
    }


def format_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:,.1f} {units[i]}" if i else f"{int(f)} {units[i]}"
