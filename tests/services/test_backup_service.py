"""Tests for backup_service."""
from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path

import pytest
from dentiva.config import update_config
from dentiva.core.dates import TZ
from dentiva.models import Patient
from dentiva.services import backup_service


def _paths():
    from dentiva.paths import paths as p
    return p


pytestmark = pytest.mark.usefixtures("session_factory")


def _mk_patient(sess, code):
    p = Patient(name="Pat " + code, phone="01700000000", gender="male", patient_code=code)
    sess.add(p)
    sess.commit()
    return p


def test_create_backup_produces_valid_zip(session, admin_principal, tmp_data_dir):
    # Put something in attachments and logos dirs to verify they're packed.
    att_dir = _paths().attachments_dir
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "hello.txt").write_text("attached-content", encoding="utf-8")
    logo_dir = _paths().logos_dir
    logo_dir.mkdir(parents=True, exist_ok=True)
    (logo_dir / "logo.png").write_bytes(b"\x89PNG-rubbish")

    _mk_patient(session, "BKP-001")
    session.commit()

    target = Path(tmp_data_dir) / "manual-backups"
    progress_calls = []

    def _p(msg, cur, tot):
        progress_calls.append((msg, cur, tot))

    res = backup_service.create_backup(
        admin_principal, target_dir=target, progress=_p,
    )
    assert res.path.exists()
    assert res.path.suffix == ".zip"
    assert res.size_bytes > 0
    assert res.file_count >= 3  # db + 1 attach + 1 logo
    assert res.db_checksum and len(res.db_checksum) == 64

    with zipfile.ZipFile(res.path, "r") as zf:
        names = zf.namelist()
        assert backup_service.MANIFEST_NAME in names
        assert backup_service.DB_NAME_IN_ARCHIVE in names
        assert any(n.startswith("attachments/") for n in names)
        assert any(n.startswith("logos/") for n in names)
        manifest = json.loads(zf.read(backup_service.MANIFEST_NAME).decode("utf-8"))
        assert manifest["version"] == backup_service.BACKUP_VERSION
        assert manifest["db"]["sha256"] == res.db_checksum
        assert len(manifest["attachments"]) == 1
        assert len(manifest["logos"]) == 1
    # Progress callback was called.
    assert progress_calls
    # Backup list (of the target dir) shows the file.
    entries = backup_service.list_backups_in(target)
    assert any(e["filename"] == res.path.name for e in entries)


def test_backup_metadata_format_size(admin_principal, tmp_data_dir):
    target = Path(tmp_data_dir) / "fmt"
    res = backup_service.create_backup(admin_principal, target_dir=target)
    assert backup_service.format_size(res.size_bytes).endswith(("B", "KB", "MB"))


def test_auto_backup_due_logic():
    now = dt.datetime.now(TZ)
    # No last backup → due
    update_config(last_backup_at="", backup_interval_days=7)
    assert backup_service.auto_backup_due() is True
    # Fresh backup → not due
    update_config(last_backup_at=now.isoformat(timespec="seconds"),
                  backup_interval_days=7)
    assert backup_service.auto_backup_due() is False
    # Old backup > interval → due
    old = (now - dt.timedelta(days=8)).isoformat(timespec="seconds")
    update_config(last_backup_at=old, backup_interval_days=7)
    assert backup_service.auto_backup_due() is True
    # interval 0 → disabled
    update_config(backup_interval_days=0)
    assert backup_service.auto_backup_due() is False
    # Restore reasonable default for other tests
    update_config(backup_interval_days=7, last_backup_at="")


def test_set_backup_dir_rejects_without_permission(session, tmp_data_dir):
    from dentiva.core.errors import PermissionDeniedError
    from dentiva.core.permissions import Principal
    powerless = Principal(user_id=999, username="x", display_name="x",
                          permissions=[], is_superuser=False)
    with pytest.raises(PermissionDeniedError):
        backup_service.set_backup_dir(Path(tmp_data_dir) / "other", powerless)


def test_restore_requires_confirmation_phrase(session, admin_principal, tmp_data_dir):
    target = Path(tmp_data_dir) / "r1"
    res = backup_service.create_backup(admin_principal, target_dir=target)
    with pytest.raises(ValueError):
        backup_service.restore_backup(admin_principal, res.path, confirmation="nope")


def test_restore_rejects_corrupted_checksum(session, admin_principal, tmp_data_dir):
    target = Path(tmp_data_dir) / "r2"
    res = backup_service.create_backup(admin_principal, target_dir=target)
    # Tamper with the DB inside the zip.
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(res.path, "r") as zin:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == backup_service.DB_NAME_IN_ARCHIVE:
                    data = b"CORRUPT" + data[7:]
                zout.writestr(item, data)
    res.path.write_bytes(buf.getvalue())
    with pytest.raises(RuntimeError):
        backup_service.restore_backup(admin_principal, res.path, confirmation="RESTORE")


def test_corrupt_zip_metadata_marked(session, admin_principal, tmp_data_dir):
    bad = Path(tmp_data_dir) / "bad"
    bad.mkdir()
    f = bad / (backup_service.BACKUP_FILE_PREFIX + "20260101-000000" + backup_service.BACKUP_FILE_SUFFIX)
    f.write_bytes(b"not-a-zip")
    entries = backup_service.list_backups_in(bad)
    assert len(entries) == 1
    assert entries[0].get("corrupt") is True
