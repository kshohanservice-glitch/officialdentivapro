"""Tests for attachment_service."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from dentiva.models import Attachment, Patient
from dentiva.services import attachment_service


pytestmark = pytest.mark.usefixtures("session_factory")


def _mk_patient(sess, code):
    p = Patient(name="AttachPat " + code, phone="01700000001", gender="male", patient_code=code)
    sess.add(p); sess.commit(); return p


def test_upload_and_list_and_delete(session, admin_principal, tmp_data_dir):
    p = _mk_patient(session, "ATT-001")
    data = b"hello world" * 100
    a = attachment_service.upload_attachment(
        session, admin_principal,
        attachable_type="patient", attachable_id=p.id,
        filename="note.txt", stream=io.BytesIO(data),
        title="My note", notes="jottings",
    )
    session.commit()
    assert a.id > 0
    assert a.size_bytes == len(data)
    assert a.stored_filename.endswith(".txt")
    handle = attachment_service.open_attachment(session, admin_principal, a.id)
    assert handle.full_path.read_bytes() == data

    lst = attachment_service.list_attachments(
        session, admin_principal, attachable_type="patient", attachable_id=p.id,
    )
    assert len(lst) == 1
    assert lst[0]["title"] == "My note"

    # Search by title/filename.
    hits = attachment_service.search_attachments(session, admin_principal, "My note")
    assert any(h["id"] == a.id for h in hits)

    assert attachment_service.delete_attachment(session, admin_principal, a.id) is True
    session.commit()
    assert not handle.full_path.exists()
    assert attachment_service.list_attachments(session, admin_principal, attachable_type="patient", attachable_id=p.id) == []


def test_upload_rejects_oversize(session, admin_principal):
    p = _mk_patient(session, "ATT-002")
    big = b"x" * (attachment_service.MAX_FILE_BYTES + 10)
    with pytest.raises(ValueError):
        attachment_service.upload_attachment(
            session, admin_principal,
            attachable_type="patient", attachable_id=p.id,
            filename="big.bin", stream=io.BytesIO(big),
        )


def test_upload_rejects_unknown_type(session, admin_principal):
    with pytest.raises(ValueError):
        attachment_service.upload_attachment(
            session, admin_principal,
            attachable_type="unicorn", attachable_id=1,
            filename="x.txt", stream=io.BytesIO(b"x"),
        )


def test_update_metadata(session, admin_principal):
    p = _mk_patient(session, "ATT-003")
    a = attachment_service.upload_attachment(
        session, admin_principal, attachable_type="patient", attachable_id=p.id,
        filename="f.txt", stream=io.BytesIO(b"abc"),
    )
    session.commit()
    attachment_service.update_attachment(
        session, admin_principal, a.id, title="Renamed", notes="new",
    )
    session.commit()
    lst = attachment_service.list_attachments(session, admin_principal, attachable_type="patient", attachable_id=p.id)
    assert lst[0]["title"] == "Renamed"
    assert lst[0]["notes"] == "new"


def test_open_attachment_path_traversal_guard(session, admin_principal, tmp_data_dir):
    p = _mk_patient(session, "ATT-004")
    a = attachment_service.upload_attachment(
        session, admin_principal, attachable_type="patient", attachable_id=p.id,
        filename="g.txt", stream=io.BytesIO(b"g"),
    )
    session.commit()
    # Tamper with stored_filename to point outside.
    a.stored_filename = "../../etc/passwd"
    session.commit()
    with pytest.raises(RuntimeError):
        attachment_service.open_attachment(session, admin_principal, a.id)


def test_format_size():
    assert attachment_service.format_size(0) == "0 B"
    assert attachment_service.format_size(2048).endswith("KB")
