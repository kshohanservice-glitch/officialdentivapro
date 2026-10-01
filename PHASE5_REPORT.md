# Phase 5 Report — Patients module

**Status:** Phase 5 complete. 63/63 tests pass. `ruff` and `mypy` clean. Ready for review/merge before Phase 6.

## What shipped

### Patient service (`dentiva/services/patient_service.py`)
Complete CRUD + soft-delete + RBAC + audit + phone/email/code/DOB validation:

| Function | Purpose | RBAC |
|---|---|---|
| `list_patients(session, principal, query, limit, offset, include_deleted)` | Returns patients ordered by name; optional search across name/phone/code; excludes soft-deleted by default. | `patients.view` |
| `count_patients(session, principal, query)` | Pagination/UI count. | `patients.view` |
| `get_patient(session, patient_id, include_deleted=False)` | Fetch by id; raises `NotFoundError` for deleted records unless `include_deleted=True`. | None (caller's list check already covered) |
| `get_patient_by_code(session, code, include_deleted=False)` | Code lookup (used by future form/duplicate-code checks). | None |
| `create_patient(session, principal, PatientInput)` | Validates inputs, auto-generates patient code `P-000001`… when blank, normalises BD phone/email, computes `age_cache` from DOB, writes audit event. | `patients.create` |
| `update_patient(session, principal, patient_id, PatientInput)` | Validates, writes before/after diffs into audit log, prevents code reuse. | `patients.edit` |
| `delete_patient(session, principal, patient_id, confirmation_text)` | **Soft-delete** requiring typed confirmation `DELETE P-XXXXXX`; refuses to delete patients with posted non-voided invoices (financial integrity). | `patients.delete` |
| `record_visit(session, patient_id, when=None)` | Maintains `last_visit_at`, increments `visit_count`, refreshes `age_cache` — called by future visit/invoice services. Does not do RBAC (caller's operation already authenticated). | None |

Input validation rules:
- **Name** required (non-empty after strip).
- **Phone / emergency phone** — BD regex `^(?:\+?880|0)1[3-9]\d{8}$`; spaces/dashes/parens normalised out; optional.
- **Email** — RFC-ish regex; lowercased; optional.
- **Patient code** — 2–32 chars, letters/numbers/`-`, uppercased; unique across **all** patients including soft-deleted (no silent reuse). Auto-generated `P-{id:06d}` when left blank.
- **DOB** — must be ≤ today; if provided, `age_cache` is computed via `age_from_dob`.
- **Blood group** uppercased, free-text gender accepted (presets + editable).

Patient-input DTO (`PatientInput`) is a dataclass with every column mapped for easy UI binding.

### UI — Patient dialog (`dentiva/ui/dialogs/patient_dialog.py`)
Two dialogs:
1. **`PatientFormDialog`** — create/edit form with:
   - Patient code (auto-assigned placeholder, read-only on edit)
   - Full name (required)
   - DOB with calendar popup (no date by default, special-value placeholder so we don't accidentally set 1900-01-01)
   - Gender combobox (Male/Female/Other/blank)
   - Blood group combobox (A+/A-/B+/…/O-)
   - Phone / emergency phone with BD placeholder
   - Email
   - Address, chief complaint, medical history (multiline)
   - Allergies, notes
   - Save/Cancel buttons, inline error label at the bottom for service-layer ValidationErrors
   - On save, service exceptions are caught and displayed inline (field-specific errors mapped later; v1 shows them in the footer which is consistent with SetupWizard).
2. **`ConfirmDeleteDialog`** — the typed-confirmation dialog used by soft-delete, requiring `DELETE P-XXXXXX` before the Delete button activates.
3. Helper `confirm_delete_patient()` runs the dialog and calls the service, showing a warning `QMessageBox` if delete is refused (e.g. because of posted invoices).

### UI — Patients view (`dentiva/ui/views/patients/patients_view.py`)
The first real "list view" in the app:
- Title + subtitle with count (e.g. "124 patient(s) total" or "5 of 124 match").
- Search bar (clear-button enabled) with 200 ms debounce; searches name/phone/patient code.
- "+ New patient" primary button (hidden when principal lacks `patients.create`).
- QTableWidget with columns: Code, Name, Phone, Gender, Age, Blood, Last visit, Visits, plus an inline actions column containing Open / Edit / Delete (each enabled based on permission).
- Double-click opens a patient (Phase 6 will route to Patient Profile; v1 shows a status-bar message and emits a `patient_opened` signal).
- `refresh()` reloads from the service; `select_patient(patient_id)` supports deep-linking from global search (Ctrl+K/Ctrl+F now actually selects+opens a patient when you pick a Patients hit!).

### Global search deep-link
Phase 4 wired the signal but no view consumed it. Phase 5 makes the Patients view the first deep-linkable view: `MainWindow._on_search_result` now calls `select_patient(entity_id)` when the target is patients, so searching for a patient name and pressing Enter selects the row + "opens" it (stub that will navigate to the profile page in Phase 6).

### Wiring
- Patients view is late-bound after login (same pattern as Dashboard & Staff) in `MainWindow.__init__`.
- Navigation placeholder is kept during shell construction so the route is always valid.
- Staff table and Patients table both get `#DpDataTable` object name; QSS added to `assets/themes/default.qss` for consistent table styling (cards-style borders, header style, row padding, selection color matching primary).

### Bug fix / consistency
- `audit_service.record()` was previously using `datetime.utcnow()` while `AuditEvent.timestamp` defaults to local Asia/Dhaka naive time. Switched to `local_now()` for consistency so audit timestamps match the rest of the schema and relative-time rendering in the notifications popup.

### Tests (63 total, +14)
Added `tests/services/test_patients.py` (14 tests):
1. `test_create_patient_basic` — code auto-generated, `visit_count=0`, `created_by` set, audit event recorded
2. `test_create_patient_auto_codes_increment` — two patients get distinct codes
3. `test_name_required` — ValidationError on empty name
4. `test_phone_validation_bd` — accepts +880…, rejects "1234"
5. `test_email_validation` — rejects "not-an-email"
6. `test_dob_in_future_rejected` — future DOB raises
7. `test_dob_sets_age_cache` — DOB 1970-06-15 yields age 56 as of 2026-10-01
8. `test_patient_code_unique` — duplicate code rejected
9. `test_list_patients_search_and_rbac` — admin/recep/assistant list works, search by name/code filters correctly
10. `test_soft_delete_requires_typed_confirmation` — wrong text raises, correct text soft-deletes, hidden from default list, audit event recorded, `get_patient` raises `NotFoundError`
11. `test_delete_blocked_for_patient_with_posted_invoice` — integrity guard prevents deleting a patient with a posted non-voided invoice
12. `test_rbac_create_requires_permission` — Assistant (view-only) cannot create
13. `test_record_visit_increments_count` — visit_count goes 0→1, last_visit_at set, age_cache refreshed
14. `test_update_patient` — fields updated, audit `patient.update` event recorded

### Quality gates
```
$ ruff check dentiva tests
All checks passed!

$ mypy dentiva
Success: no issues found in 100 source files

$ pytest tests/
============================== 63 passed in 25.83s ==============================
```

## RBAC applied
| Action | Permission |
|---|---|
| List / search / view | `patients.view` |
| Create new patient | `patients.create` |
| Edit patient | `patients.edit` |
| Soft-delete patient | `patients.delete` |

The UI hides Edit/Delete buttons when the principal lacks the permission (Receptionists can create/edit/view; Assistant can only view; Administrator can do everything; Dentist can view/create/edit per seeded role). The service layer double-checks every permission, so even direct Python calls or future external API surfaces cannot bypass checks.

## Notable design decisions
1. **Soft delete, not hard delete.** `deleted_at` is set rather than removing the row, preserving referential integrity for audit/history/financial records. The UI and queries filter soft-deleted rows by default.
2. **Patient codes are unique forever.** Duplicate-code validation checks all patients including soft-deleted ones, so a deleted patient's code can never be silently reused (avoids medical-record mix-ups).
3. **Financial guard on delete.** Even with the correct typed confirmation, a patient with posted non-voided invoices cannot be deleted — the UI shows a warning directing the user to void/transfer first. This protects revenue records and prevents orphaned invoice rows.
4. **Auto age cache.** `age_cache` is computed on create/update and refreshed on every `record_visit()` so we never have to compute age from DOB on every dashboard list render.
5. **Debounced search (200 ms)** on the patients list and 150 ms on the global search popover keeps the DB from being hit on every keystroke.
6. **Audit diffs on update:** `update_patient` captures a before-snapshot and writes both `before_json` and `after_json` into `audit_event`, giving a full audit trail for privacy/liability compliance.
7. **DOB sentinel handling:** QDateEdit can't natively represent "no date" (its minimum date is 100 AD by default). We use `setSpecialValueText(" ")` + `minimumDate=1900-01-01` + a `_dob_set` flag toggled by `dateChanged` so users can clear DOB after setting it.
8. **Phone normalisation:** `validate_phone` strips spaces/dashes/parens before regex-matching, so users can type `017-1234 5678` and it saves cleanly. `+880` prefix is preserved when used.

## Known intentional deferrals
- Patient profile page (tabbed view with visits, chart, prescriptions, invoices, attachments) — Phase 6. The Patients list is fully functional for CRUD; "Open" currently shows a status-bar message and emits `patient_opened` signal ready for Phase 6 to consume.
- Patient photo upload (Phase 6 profile page).
- Import/export CSV (Phase 12 Admin Console); individual patient print (Phase 6 profile).
- Duplicate detection on similar-sounding/nearby phone numbers (nice-to-have; not in Phase 5 scope).
- Deleted-patients admin restore UI — `include_deleted=True` is implemented at the service layer for future admin view.

## Files changed
- Added: `dentiva/services/patient_service.py`, `dentiva/ui/dialogs/patient_dialog.py`, `dentiva/ui/views/patients/__init__.py`, `dentiva/ui/views/patients/patients_view.py`, `tests/services/test_patients.py`
- Modified: `dentiva/services/audit_service.py` (use `local_now()` instead of `utcnow()`), `dentiva/ui/main_window.py` (late-bind PatientsView, deep-link `select_patient` on search result), `dentiva/ui/navigation.py` (patients placeholder adjusted), `dentiva/ui/views/staff/staff_view.py` (`#DpDataTable` object name for shared styling), `assets/themes/default.qss` (data-table styling), existing tests are all green.

## Next (Phase 6) — Patient profile & dental chart
Pending your explicit "Continue". Planned: tabbed patient profile (Summary / Visits / Dental Chart / Prescriptions / Invoices / Attachments); per-encounter dental chart with FDI adult+pediatric tooth grid, condition painting (caries/filled/missing/root-canal/crown/bridge/implant/selected) persisted per encounter; timeline of visits; quick actions (new appointment, new invoice, new prescription) from profile.
