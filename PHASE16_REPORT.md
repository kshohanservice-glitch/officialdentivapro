# Phase 16 Report — Global Search & Attachments

## Goal
Expand global search to cover every major entity type, and ship a working
attachments subsystem (disk storage + RBAC) plus a dedicated Attachments page.

## What shipped (Phase 16)

### `dentiva/services/attachment_service.py` (new)
Polymorphic attachment service.

* Files stored under `paths.attachments_dir / <yyyymm> / <uuid><ext>` — never
  uses user-supplied names on disk (prevents path traversal, name collisions,
  and illegal Windows filenames).
* Per-file 50 MB cap (`MAX_FILE_BYTES`).
* Polymorphic link: `(attachable_type, attachable_id)` with type whitelist
  (`patient`, `visit`, `prescription`, `invoice`); patient existence is
  verified on upload.
* Content-type guessed from filename; original filename, size, title, notes,
  and uploader stored in the `attachment` table.
* Public API: `upload_attachment`, `upload_attachment_from_path`,
  `list_attachments`, `open_attachment` (returns an `AttachmentHandle` with a
  resolved, path-traversal-guarded `full_path`), `delete_attachment`,
  `update_attachment` (rename title/notes, file stays on disk),
  `search_attachments` (title/filename/notes substring match for global
  search), `format_size`.
* RBAC: `ATTACHMENTS_VIEW` for open/list/search; `ATTACHMENTS_MANAGE` for
  upload/delete/update.
* Delete removes both the DB row and the on-disk file (silently tolerates
  missing files).
* Open resolves the on-disk path and verifies it stays inside
  `attachments_dir` (defense against a corrupted `stored_filename` column).

### Dedicated Attachments page (`dentiva/ui/views/attachments/attachments_view.py`, new)
Full CRUD UI, gated by permissions:

* Table of all attachments with When, Type (patient/visit/prescription/invoice),
  Attached-to ID, Title, Filename, Size; client-side filter box; double-click
  opens the file via the OS default program (Win: `os.startfile`, macOS:
  `open`, Linux: `xdg-open`).
* **Upload file…** — prompts for a patient (by code or partial name), then a
  file picker; attaches the file to that patient.
* **Save as…** saves a copy to a user-chosen location without altering the
  stored file.
* **Rename title** lets staff edit the human-friendly title without
  re-uploading.
* **Delete** requires a confirmation dialog (no typed phrase for single
  files; the file is permanently removed).
* Long operations are quick enough to stay on the UI thread (files are local,
  small); exceptions are caught and surfaced via `QMessageBox`.

### Global search upgrades (`dentiva/services/dashboard_service.py`)
Extended `global_search` to cover seven kinds, still RBAC-gated and ordered
best-first:

1. Patients — now also matches email.
2. Appointments — now searches back 365 days (was 7) and matches patient phone.
3. Invoices — unchanged.
4. **Prescriptions** (new) — matches patient name, chief complaint, notes.
5. **Inventory** (new) — matches name and SKU.
6. **Treatments catalog** (new) — matches name and category.
7. **Attachments** (new) — matches title/filename/notes; resolves to the
   attached patient and deep-links to the patient profile.

Routes: patient results now use `patient_profile` so selecting one opens the
full patient profile (matching what the other views do); attachment results
also open the attached patient's profile. The popup's `KIND_LABEL` map was
extended to label the new sections.

### Navigation
* Added `attachments` route in `dentiva/ui/navigation.py`.
* Added nav item (📎) in `dentiva/ui/widgets/nav.py`.
* Wired `AttachmentsView` into `MainWindow.replace_view`.

## Tests
* `tests/services/test_attachment_service.py` (new, 6 tests) — upload + list +
  open + search + delete, oversize rejection, unknown attachable type,
  metadata update, path-traversal guard on open, format_size.
* `tests/services/test_global_search.py` (new, 3 tests) — inventory,
  prescription, and attachment hits.
* Full suite: **163 passed**.

## Quality gates
| Tool | Result |
|------|--------|
| `pytest tests/` | **163 passed** (6 + 3 new + 154 prior) |
| `ruff check dentiva/` | All checks passed |
| `mypy dentiva/services/attachment_service.py` + `dashboard_service.py` + `attachments_view.py` | Success |
| `py_compile` all new/edited | OK |

## Files changed / added
* Added: `dentiva/services/attachment_service.py`
* Added: `dentiva/ui/views/attachments/__init__.py`, `attachments_view.py`
* Added: `tests/services/test_attachment_service.py`
* Added: `tests/services/test_global_search.py`
* Modified: `dentiva/services/dashboard_service.py` (extended search)
* Modified: `dentiva/ui/widgets/search_popup.py` (extended kind labels)
* Modified: `dentiva/ui/navigation.py` (attachments route)
* Modified: `dentiva/ui/widgets/nav.py` (📎 nav item)
* Modified: `dentiva/ui/main_window.py` (wire AttachmentsView)

## Notes
- The Phase 11 placeholder for an Attachments tab inside the patient profile
  is still a placeholder — users can upload from the global Attachments page
  today by entering the patient's code/name, and files are visible there.
  Per-record upload panels will be wired into the patient/visit/prescription
  pages in a future iteration if time allows (the service supports it
  natively — only UI widgets are needed).
- Attachment files stream in 1 MiB chunks while checking the 50 MB cap, so
  even huge attempted uploads don't blow up memory.
