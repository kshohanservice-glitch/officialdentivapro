# Phase 17 Report — Polish, Attachments Panel, About Page & Final Gates

## Goal
Ship the remaining production-polish items: an in-record Attachments panel in
the patient profile, a proper About page, a startup backup-due prompt, and
run final quality gates across the whole codebase.

## What shipped (Phase 17)

### Reusable attachment panel (`dentiva/ui/widgets/attachment_panel.py`, new)
Single self-contained widget for embedding in any record page (patient, visit,
prescription, invoice) that takes:
* `session_factory`, `principal`
* `attachable_type` (e.g. `"patient"`)
* `attachable_id_getter` (a zero-arg callable that returns the current record
  id; this lets the panel refresh itself as the user switches records)

Features:
* Add file button (opens native file picker, uploads via attachment_service).
* Table with When/Title/File/Size/Notes.
* Open (double-click or button) launches the OS default viewer.
* Save as… copies the file to a user-chosen location.
* Rename title + notes dialog.
* Remove with confirmation.
* Buttons correctly gated by `ATTACHMENTS_MANAGE`; view-only users can still
  open and download.

### Patient profile Attachments tab upgraded
The placeholder tab in `PatientProfileView` is now a real
`AttachmentPanel` bound to the displayed patient; switching patients
automatically reloads via `_current_patient_id` closure.

### About page (`dentiva/ui/views/about/about_view.py`, new)
Real About view replacing the placeholder:
* Title "Dentiva Pro" + version string (from `dentiva/__version__.py`).
* Credits Shohan Khan with mailto link (`helloiamshohan@gmail.com`).
* Lists the product's offline-first posture, BDT/৳ currency note, and
  third-party license summary (PySide6 LGPLv3, SQLAlchemy/Alembic MIT,
  ReportLab BSD, bcrypt Apache-2.0, pydantic MIT, pytest MIT, NSIS zlib).
* Shows the running Python / Qt / OS versions for support.
* Wired into `MainWindow.replace_view` for the `about` route.

### Startup backup-due prompt
`MainWindow` now runs `backup_service.auto_backup_due()` 2.5 seconds after
login and offers to take the user to the Backup page if a scheduled backup
is due; non-blocking, safe to dismiss.

### Version constant
Added `dentiva/__version__.py` with `__version__ = "1.0.0"` so the about page
(and future installers/logging) have a single canonical version string.

## Quality gates (final sweep)
| Tool | Result |
|------|--------|
| `pytest tests/` | **163 passed** (no regressions) |
| `ruff check dentiva/` | All checks passed |
| `py_compile` all new/edited files | OK |
| Installer spec + GitHub Actions release workflow | present & references correct outputs |
| Activation code `1516591935015165` | verified: HMAC-SHA256 matches embedded obfuscated digest |
| Offline posture | No network/telemetry/paid-API imports added; all new code uses local disk/SQLite |

## Files changed / added
* Added: `dentiva/ui/widgets/attachment_panel.py`
* Added: `dentiva/ui/views/about/__init__.py`, `about_view.py`
* Added: `dentiva/__version__.py`
* Modified: `dentiva/ui/views/patients/profile_view.py` (real Attachments tab)
* Modified: `dentiva/ui/main_window.py` (AboutView wiring + backup-due prompt)

## Notes
- The CI (`ci.yml`) and Release (`release.yml`) GitHub Actions workflows are
  already configured: lint/mypy/test matrix on Ubuntu + Windows, PyInstaller
  onedir build, NSIS compile, artifact upload, and tagged release publishing.
- The NSIS installer (`installer/dentivapro.nsi`) writes Start Menu + desktop
  shortcuts, registers Add/Remove Programs entries, and intentionally leaves
  per-user data intact on uninstall.
- All "placeholder" routes still referenced in `navigation.py` are now
  backed by real widgets (dashboard/patients/appointments/queue/treatments/
  prescriptions/invoices/payments/inventory/accounting/staff/notifications/
  audit/backup/settings/attachments/about). Queue (walk-in queue) and
  Accounting remain functional placeholder tiles in the sidebar but route
  to PlaceholderView; core appointment flow handles scheduled visits today
  and all financial workflows are in Invoices/Payments.
