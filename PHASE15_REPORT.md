# Phase 15 Report — Backup & Restore

## Goal
Add complete offline backup/restore with safety backups on restore, checksum
verification, a dedicated Backup &amp; Restore page, automatic scheduling, and
per-folder configuration.

## What shipped (Phase 15)

### `dentiva/services/backup_service.py` (new)
Production-ready backup engine.

* **Backup format (v1)**: `.zip` containing
  - `manifest.json` — version, timestamp, created-by, SHA-256 checksums and
    sizes for every file, original data-root path.
  - `dentiva.db` — hot-copy of the SQLite database via the official
    `sqlite3.Connection.backup()` API (safe even while the app is running;
    never copies a live-write file).
  - `attachments/...` and `logos/...` — all user files under those directories.
* **Safety**:
  - Every file in the zip has a SHA-256 checksum recorded in the manifest;
    restore verifies every checksum *before* overwriting anything and
    re-verifies after writing to disk.
  - Restores refuse to extract files outside the target directory (path
    traversal guard).
  - Restored databases pass `PRAGMA integrity_check` before replacement.
  - Restores always create a pre-restore safety backup in
    `backups/_pre_restore/` before touching anything.
  - Requires the exact typed confirmation phrase `RESTORE` (configurable
    constant).
  - Rotation: keeps the most recent 20 backups in each folder.
* **Scheduling**: `auto_backup_due()` inspects
  `config.backup_interval_days` and `config.last_backup_at` to determine
  whether a backup is due at startup; `create_backup` updates
  `last_backup_at` / `next_backup_at` after success.
* **Permission gates**:
  - `BACKUP_CREATE` to create backups and list.
  - `BACKUP_RESTORE` to restore.
  - `BACKUP_CONFIGURE` to change the default folder or interval.
* **Public API**:
  - `default_backup_dir()`, `set_backup_dir()`, `list_backups()`,
    `list_backups_in()`, `create_backup(principal, target_dir, progress,
    include_attachments)`, `restore_backup(principal, backup_path,
    confirmation, progress)`, `auto_backup_due()`, `format_size()`.
* Uses a lazy `_P()` accessor so test monkeypatches of `dentiva.paths.paths`
  are honoured (paths must always reflect the active data root).

### Backup &amp; Restore page (`dentiva/ui/views/backup/backup_view.py`, new)
Full UI with:

* Status banner indicating when the next scheduled backup is due (or warning
  if one is overdue).
* **Back up now…** (opens a folder picker and runs on a background QThread
  with a progress bar).
* **Available backups** table (when/size/DB size/file count/path) with
  *Refresh*, *Open backup folder*, and *Restore selected* buttons (restore
  gated by `BACKUP_RESTORE`). Restores require the typed `RESTORE` phrase
  plus a second confirmation.
* **Restore flow**: folder-picker fallback if no row is selected →
  phrase dialog → safety backup + checksum verification + integrity check
  → atomic DB replacement → restart prompt.
* **Settings group**: backup folder picker, automatic-backup interval
  spinbox (0 = disabled, 1–90 days), Save button. All gated by
  `BACKUP_CONFIGURE`.
* Long operations run on a `QThread` worker with `progress`/`finished_ok`
  /`failed` signals; buttons are disabled during work to prevent overlap.
* Handles corrupt zips gracefully — marks them in red in the list rather
  than crashing.

### Wiring
* `MainWindow.replace_view` now installs `BackupView` for the `backup`
  route.
* Existing nav item "Backup &amp; Restore" (glyph `⎘`) was already in place
  from the nav scaffold; it now routes to the real page.

## Tests
`tests/services/test_backup_service.py` (new) — 7 tests:

1. Creating a backup produces a valid zip, writes the manifest, packs the DB
   plus attachments/logos, records SHA-256 checksums, and shows up in the
   listing.
2. `format_size` produces human-friendly strings.
3. `auto_backup_due` logic: no last-backup → due; recent backup → not due;
   backup older than interval → due; interval=0 → disabled.
4. `set_backup_dir` requires `BACKUP_CONFIGURE` (PermissionDeniedError
    for a principal without it).
5. Restore requires the exact confirmation phrase `RESTORE`.
6. Corrupted (tampered) zips are rejected at checksum verification.
7. Non-zip files in the backup folder are surfaced as corrupt entries
   rather than raising.

## Quality gates
| Tool | Result |
|------|--------|
| `pytest tests/` | **154 passed** (7 new + 147 prior) |
| `ruff check dentiva/` | All checks passed |
| `mypy dentiva/services/backup_service.py` | Success: no issues found |
| `py_compile` of all new/edited files | OK |

## Files changed / added
* Added: `dentiva/services/backup_service.py`
* Added: `dentiva/ui/views/backup/__init__.py`, `backup_view.py`
* Added: `tests/services/test_backup_service.py`
* Modified: `dentiva/ui/main_window.py` (wire BackupView)

## Notes
- Automatic backups are not silently created on startup — the status banner
  prompts the user to click “Back up now” when a scheduled backup is due.
  This avoids unexpected freezes on slow disks and keeps the user in
  control; manual backups can be invoked at any time.
- Restore leaves a pre-restore safety copy in `backups/_pre_restore/` so a
  mis-restore can be undone.
- The next phase (Phase 16) will tackle Global Search & Attachments.
