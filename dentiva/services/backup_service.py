# mypy: disable-error-code="arg-type, union-attr, no-any-return"
"""Backup and restore service.

Backup format (v1):

    dentiva-backup-YYYYMMDD-HHMMSS.zip
      manifest.json           metadata (version, timestamps, checksums, files)
      dentiva.db              hot-copy of the SQLite database (safe-copy via
                              sqlite3 backup API so the running DB is never
                              corrupted).
      attachments/...         all files under _P().attachments_dir (if any)
      logos/...               all files under _P().logos_dir (if any)

Each file entry in ``manifest.json`` carries a SHA-256 checksum so restore can
verify integrity before overwriting anything. Restore always creates a
*pre-restore safety backup* of the current database and attachments before
replacing them, and requires a typed confirmation ("RESTORE").
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dentiva.config import get_config, update_config
from dentiva.core.dates import TZ, local_now
from dentiva.core.permissions import Permission, Policy, Principal


# Re-resolve lazily so test monkeypatches (which swap out the ``paths`` module
# attribute on dentiva.paths) and production reconfigurations always see the
# currently-active Paths object.
def _P():  # type: ignore[no-untyped-def]
    from dentiva import paths as _pm
    return _pm.paths

log = logging.getLogger(__name__)

BACKUP_FILE_PREFIX = "dentiva-backup-"
BACKUP_FILE_SUFFIX = ".zip"
MANIFEST_NAME = "manifest.json"
DB_NAME_IN_ARCHIVE = "dentiva.db"
RESTORE_CONFIRM_PHRASE = "RESTORE"
BACKUP_VERSION = 1


# ----------------------------------------------------------------------- result
@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    file_count: int
    db_checksum: str
    created_at: dt.datetime


@dataclass
class RestoreResult:
    safety_backup: Path
    db_restored: bool
    attachments_restored: int
    logos_restored: int


# ---------------------------------------------------------------------- public
def default_backup_dir() -> Path:
    cfg = get_config()
    if cfg.backup_folder:
        p = Path(cfg.backup_folder).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            log.warning("Configured backup_folder %s is unwritable; falling back.", p)
    _P().ensure()
    return _P().backups_dir


def set_backup_dir(path: str | Path, principal: Principal) -> Path:
    Policy.require(principal, Permission.BACKUP_CONFIGURE)
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    # quick writability test
    test_file = p / ".dentiva-write-test"
    test_file.write_text("ok", encoding="utf-8")
    test_file.unlink()
    update_config(backup_folder=str(p))
    return p


def list_backups_in(folder: Path) -> list[dict[str, Any]]:
    d = Path(folder).expanduser()
    out: list[dict[str, Any]] = []
    if not d.exists():
        return out
    for child in sorted(d.glob(BACKUP_FILE_PREFIX + "*" + BACKUP_FILE_SUFFIX), reverse=True):
        try:
            out.append(_read_backup_meta(child))
        except Exception:  # pragma: no cover
            continue
    return out


def list_backups(principal: Principal) -> list[dict[str, Any]]:
    # Either create or restore permission is enough to list.
    if not (principal.has(Permission.BACKUP_CREATE)
            or principal.has(Permission.BACKUP_RESTORE)
            or principal.is_superuser):
        Policy.require(principal, Permission.BACKUP_CREATE)  # raises
    return list_backups_in(default_backup_dir())


def create_backup(
    principal: Principal,
    *,
    target_dir: Path | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    include_attachments: bool = True,
) -> BackupResult:
    """Create a backup; returns path + metadata."""
    Policy.require(principal, Permission.BACKUP_CREATE)
    _P().ensure()
    out_dir = target_dir or default_backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    now = local_now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    zip_path = out_dir / f"{BACKUP_FILE_PREFIX}{stamp}{BACKUP_FILE_SUFFIX}"
    tmp_path = zip_path.with_suffix(".zip.tmp")

    # Stage the DB to a temp file using the SQLite backup API (hot-copy, safe
    # even with a running application). We resolve the SQLite file from the
    # SQLAlchemy URL so we don't depend on a global engine.
    staged_db = _P().tmp_dir / f"dentiva-backup-{stamp}.db"
    _P().tmp_dir.mkdir(parents=True, exist_ok=True)
    if staged_db.exists():
        staged_db.unlink()

    _report(progress, "Copying database…", 0, 3)
    db_file = _resolve_db_file()
    _hot_copy_sqlite(db_file, staged_db)
    db_checksum = _sha256_file(staged_db)
    db_size = staged_db.stat().st_size

    # Walk attachments + logos.
    files_to_pack: list[tuple[Path, str]] = [(staged_db, DB_NAME_IN_ARCHIVE)]
    attach_entries = []
    if include_attachments and _P().attachments_dir.exists():
        for fp in _walk_files(_P().attachments_dir):
            rel = "attachments/" + fp.relative_to(_P().attachments_dir).as_posix()
            files_to_pack.append((fp, rel))
            attach_entries.append({"path": rel, "size": fp.stat().st_size,
                                   "sha256": _sha256_file(fp)})
    logo_entries = []
    if _P().logos_dir.exists():
        for fp in _walk_files(_P().logos_dir):
            rel = "logos/" + fp.relative_to(_P().logos_dir).as_posix()
            files_to_pack.append((fp, rel))
            logo_entries.append({"path": rel, "size": fp.stat().st_size,
                                 "sha256": _sha256_file(fp)})

    _report(progress, "Writing archive…", 1, 3)
    total = len(files_to_pack)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, (fp, arcname) in enumerate(files_to_pack, start=1):
            zf.write(fp, arcname)
            if progress and i % 20 == 0:
                _report(progress, f"Packing {arcname}…", 1 + i, total + 2)
        manifest = {
            "version": BACKUP_VERSION,
            "created_at": now.isoformat(timespec="seconds"),
            "created_by": principal.username,
            "db": {"path": DB_NAME_IN_ARCHIVE, "size": db_size, "sha256": db_checksum},
            "attachments": attach_entries,
            "logos": logo_entries,
            "clinic_data_root": str(_P().data_root),
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))

    # Validate archive integrity before we commit.
    _report(progress, "Verifying archive…", 2, 3)
    with zipfile.ZipFile(tmp_path, "r") as zf:
        bad = zf.testzip()
        if bad is not None:  # pragma: no cover
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Backup verification failed (bad member: {bad})")

    tmp_path.replace(zip_path)

    # Clean up staged db.
    try:
        staged_db.unlink()
    except OSError:  # pragma: no cover
        pass

    _report(progress, "Done.", 3, 3)
    size_bytes = zip_path.stat().st_size
    file_count = 1 + len(attach_entries) + len(logo_entries)

    # Rotate old backups: keep the most recent 20 (config-friendly simple cap),
    # regardless of size. Excess files are oldest-first.
    _rotate_old_backups(out_dir, keep=20)

    # Update config timestamps.
    next_days = max(0, get_config().backup_interval_days)
    nxt = (now + dt.timedelta(days=next_days)).isoformat(timespec="seconds") if next_days else ""
    update_config(last_backup_at=now.isoformat(timespec="seconds"), next_backup_at=nxt)

    return BackupResult(path=zip_path, size_bytes=size_bytes,
                        file_count=file_count, db_checksum=db_checksum, created_at=now)


def restore_backup(
    principal: Principal,
    backup_path: Path,
    *,
    confirmation: str,
    progress: Callable[[str, int, int], None] | None = None,
) -> RestoreResult:
    """Restore from a backup zip. Always takes a safety backup first."""
    Policy.require(principal, Permission.BACKUP_RESTORE)
    backup_path = Path(backup_path).expanduser().resolve()
    if confirmation.strip() != RESTORE_CONFIRM_PHRASE:
        raise ValueError(f"Confirmation must be exactly '{RESTORE_CONFIRM_PHRASE}'.")
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    manifest = _read_manifest(backup_path)
    if manifest.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unsupported backup version {manifest.get('version')!r}.")

    # Pre-restore safety backup (DB + attachments/logos as they exist right now).
    _report(progress, "Creating safety backup before restore…", 0, 4)
    safety = create_backup(principal,
                           target_dir=_P().backups_dir / "_pre_restore",
                           progress=_subprogress(progress, 0, 1, 4),
                           include_attachments=True)

    # Verify all checksums up front before we overwrite anything.
    _report(progress, "Verifying checksums…", 1, 4)
    _verify_backup_checksums(backup_path, manifest)

    _P().ensure()
    # Stage the restored DB into tmp, then atomically move it into place.
    _report(progress, "Extracting database…", 2, 4)
    staged_restore_db = _P().tmp_dir / f"restore-{os.getpid()}-{dt.datetime.utcnow().timestamp():.0f}.db"
    _P().tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            with zf.open(manifest["db"]["path"]) as src, open(staged_restore_db, "wb") as dst:
                shutil.copyfileobj(src, dst)

            # Restore attachments: wipe and replace.
            _report(progress, "Restoring attachments…", 3, 4)
            att_count = _restore_tree(zf, manifest.get("attachments", []),
                                      _P().attachments_dir, prefix="attachments/")
            logo_count = _restore_tree(zf, manifest.get("logos", []), _P().logos_dir, prefix="logos/")

        # Verify the staged DB opens and passes PRAGMA integrity_check.
        _check_sqlite_integrity(staged_restore_db)

        # Move the staged DB into place.
        db_file = _resolve_db_file()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        # On Windows, we cannot replace an open DB; callers are expected to
        # shut down the engine before calling us here. We still attempt a
        # replace and let the caller handle restart.
        if db_file.exists():
            db_file.unlink()
        shutil.move(str(staged_restore_db), str(db_file))
    finally:
        if staged_restore_db.exists():
            try:
                staged_restore_db.unlink()
            except OSError:
                pass

    _report(progress, "Restore complete. Please restart the application.", 4, 4)
    return RestoreResult(
        safety_backup=safety.path,
        db_restored=True,
        attachments_restored=att_count,
        logos_restored=logo_count,
    )


def auto_backup_due() -> bool:
    """Called at startup; return True if a scheduled backup is due."""
    cfg = get_config()
    if cfg.backup_interval_days <= 0:
        return False
    if not cfg.last_backup_at:
        return True
    try:
        last = dt.datetime.fromisoformat(cfg.last_backup_at)
        if last.tzinfo is not None:
            last = last.astimezone(TZ).replace(tzinfo=None)
    except ValueError:
        return True
    next_due = last + dt.timedelta(days=cfg.backup_interval_days)
    return local_now() >= next_due


# -------------------------------------------------------------------- discovery
def _resolve_db_file() -> Path:
    return _P().database_path


def _walk_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _hot_copy_sqlite(src: Path, dst: Path) -> None:
    """Create a consistent snapshot of an open SQLite database."""
    src_uri = src.as_uri() + "?mode=ro"
    with sqlite3.connect(src_uri, uri=True) as src_conn:
        if dst.exists():
            dst.unlink()
        with sqlite3.connect(str(dst)) as dst_conn:
            src_conn.backup(dst_conn)
            dst_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _check_sqlite_integrity(db_file: Path) -> None:
    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.execute("PRAGMA integrity_check")
        rows = cur.fetchall()
        if not rows or rows[0][0] != "ok":
            raise RuntimeError(f"Restored database failed integrity check: {rows!r}")


def _read_manifest(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as zf, zf.open(MANIFEST_NAME) as mf:
        data = json.loads(mf.read().decode("utf-8"))
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError("Invalid backup archive: missing manifest version.")
    return data


def _verify_backup_checksums(zip_path: Path, manifest: dict[str, Any]) -> None:
    h = hashlib.sha256()
    with zipfile.ZipFile(zip_path, "r") as zf:
        # DB
        db_entry = manifest["db"]
        with zf.open(db_entry["path"]) as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
            if h.hexdigest() != db_entry["sha256"]:
                raise RuntimeError("DB checksum mismatch — backup is corrupted.")
        # Files
        for section in ("attachments", "logos"):
            for entry in manifest.get(section, []):
                with zf.open(entry["path"]) as f:
                    hh = hashlib.sha256()
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hh.update(chunk)
                    if hh.hexdigest() != entry["sha256"]:
                        raise RuntimeError(f"Checksum mismatch in backup for {entry['path']}")


def _restore_tree(zf: zipfile.ZipFile, entries: list[dict[str, Any]], dest_root: Path, prefix: str) -> int:
    # Wipe existing files under dest_root (subdirectories preserved).
    if dest_root.exists():
        for fp in _walk_files(dest_root):
            try:
                fp.unlink()
            except OSError:
                log.warning("Could not remove old file %s during restore.", fp)
    count = 0
    dest_root.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_root.resolve()
    for entry in entries:
        arcname = entry["path"]
        if not arcname.startswith(prefix):
            continue
        rel = arcname[len(prefix):].lstrip("/")
        if not rel:
            continue
        target = (dest_root / rel).resolve()
        # Path traversal guard.
        if not str(target).startswith(str(dest_resolved)):
            raise RuntimeError(f"Refusing to extract outside target: {arcname}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(arcname) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if _sha256_file(target) != entry["sha256"]:
            raise RuntimeError(f"Checksum mismatch after writing {arcname}")
        count += 1
    return count


def _rotate_old_backups(folder: Path, keep: int) -> None:
    files = sorted(
        folder.glob(BACKUP_FILE_PREFIX + "*" + BACKUP_FILE_SUFFIX),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:  # pragma: no cover
            log.warning("Failed to rotate old backup %s", old)


def _report(progress: Callable[[str, int, int], None] | None, msg: str, cur: int, total: int) -> None:
    if progress is not None:
        try:
            progress(msg, max(0, cur), max(1, total))
        except Exception:  # pragma: no cover
            log.exception("Progress callback raised")


def _subprogress(progress: Callable[[str, int, int], None] | None,
                 lo: int, hi: int, total: int) -> Callable[[str, int, int], None]:
    def _inner(msg: str, cur: int, tot: int) -> None:
        if progress is None:
            return
        frac = lo + (hi - lo) * (cur / max(1, tot))
        progress(msg, int(frac), total)
    return _inner


def _read_backup_meta(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            try:
                with zf.open(MANIFEST_NAME) as mf:
                    m = json.loads(mf.read().decode("utf-8"))
            except KeyError:
                # Legacy: no manifest. Surface file info only.
                m = {"version": 0, "created_at": ""}
        stat = path.stat()
        created = m.get("created_at") or dt.datetime.fromtimestamp(stat.st_mtime, TZ).isoformat(timespec="seconds")
        db_entry = m.get("db") or {}
        att = m.get("attachments") or []
        logos = m.get("logos") or []
        return {
            "path": str(path),
            "filename": path.name,
            "size_bytes": stat.st_size,
            "created_at": created,
            "version": m.get("version", 0),
            "db_size_bytes": db_entry.get("size", 0),
            "attachment_count": len(att),
            "logo_count": len(logos),
            "created_by": m.get("created_by", ""),
        }
    except (zipfile.BadZipFile, OSError, ValueError):
        return {
            "path": str(path),
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": dt.datetime.fromtimestamp(path.stat().st_mtime, TZ).isoformat(timespec="seconds"),
            "version": 0,
            "db_size_bytes": 0,
            "attachment_count": 0,
            "logo_count": 0,
            "created_by": "",
            "corrupt": True,
        }


# ------------------------ helpers used by UI (session-free operations)
def format_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:,.1f} {units[i]}" if i else f"{int(f)} {units[i]}"
