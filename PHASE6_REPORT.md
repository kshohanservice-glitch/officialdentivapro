# Phase 6 Report — Patient profile & dental chart

**Status:** Phase 6 complete. 75/75 tests pass. `ruff` and `mypy` clean. Ready for review/merge before Phase 7.

## What shipped

### Visit service (`dentiva/services/visit_service.py`)
Full visit + dental-chart service layer with RBAC and audit:

| Function | Purpose | RBAC |
|---|---|---|
| `list_visits(session, principal, patient_id)` | Newest-first visit list with embedded findings. | `visits.view` |
| `get_visit(session, principal, visit_id)` | Single visit with dentist name + findings. | `visits.view` |
| `create_visit(session, principal, patient_id, VisitInput)` | Opens a visit with notes + findings, increments `visit_count`, updates `last_visit_at`, refreshes `age_cache`, writes audit event. | `visits.create` |
| `update_visit(session, principal, visit_id, VisitInput)` | Edits notes/findings on an **open** visit; refuses closed visits. | `visits.edit` |
| `close_visit(session, principal, visit_id)` | Marks visit closed (finalises the chart snapshot for that encounter). | `visits.edit` |
| `set_tooth_finding(session, principal, visit_id, tooth_code, finding_code)` | Atomically replaces a single tooth's finding on an open visit. | `chart.edit` |
| `latest_chart_state(session, patient_id)` | Returns `{tooth_code: finding_code}` for the *most recent* finding per tooth across all visits — used to paint the "current state of the mouth" in the chart widget. | Caller-gated (intended for patient-profile view which already enforces `visits.view`). |
| `list_teeth(session, pediatric=False)` | Returns tooth references in chart-draw order. | None |
| `ada_equivalent(fdi_code)` | FDI → ADA Universal notation mapper (used for annotation in the chart). | Pure helper. |

**`FINDINGS`** palette (code, label, color) — 14 clinical conditions used by both service validation and UI palette:

| Code | Label | Color |
|---|---|---|
| healthy | Healthy | green |
| caries | Caries | red |
| filled | Filled | blue |
| missing | Missing | gray |
| rct | Root Canal | purple |
| crown | Crown | amber |
| bridge | Bridge | brown |
| implant | Implant | dark green |
| extraction | Extraction | dark red |
| impacted | Impacted | dark gray |
| sealant | Sealant | cyan |
| fracture | Fracture | red |
| abscess | Abscess | orange |
| plaque | Plaque/Calculus | indigo |

Validation rules:
- Unknown tooth codes and unknown finding codes raise `ValidationError`.
- Closed visits cannot be edited (chart or notes).
- Invalid/nonexistent dentist raises `ValidationError`.
- Findings are replaced per-tooth per-visit; passing `healthy` removes any existing finding on that tooth for this visit (so a user can mark a previously-restored tooth as healthy again).

### Dental chart widget (`dentiva/ui/widgets/dental_chart.py`)
Interactive FDI dental-chart QGraphicsScene widget:
- Supports both **adult** (permanent, 32 teeth, quadrants 1-4) and **pediatric** (deciduous, 20 teeth, quadrants 5-8) layouts.
- Renders each tooth as a rounded rectangle with a midline indicator, labelled with both FDI code and ADA Universal notation underneath.
- Palette of 14 findings rendered as toggleable tool-buttons with colored swatches.
- Clicking a tooth paints it with the selected finding color and emits `tooth_clicked` and `finding_changed(tooth_code, finding_code)` signals.
- Hover tooltip shows tooth code + current finding label.
- Read-only mode (`editable=False`) hides the palette (used for historical views).
- Dashed midline divider between left/right quadrants.
- Scene auto-fits on resize.

### Visit dialog (`dentiva/ui/dialogs/visit_dialog.py`)
Create/edit visit modal:
- Patient name + code shown read-only at top.
- DateTime picker (calendar popup) for visit date/time, defaulting to now.
- Dentist selector populated from `list_dentists()` (respects RBAC for visibility).
- Chart type selector (adult / pediatric) that swaps the chart widget on the fly without losing findings on teeth whose codes exist in both layouts (codes never overlap between adult/pediatric, so state is cleared when switching — documented & safe).
- Reason / Chief complaint / On examination / Advice / Notes fields.
- Embedded interactive dental chart palette.
- Two save modes: **Save & keep open** and **Save & close visit** (finalises).
- Inline error label for service-layer ValidationErrors.

### Patient profile view (`dentiva/ui/views/patients/profile_view.py`)
Tabbed profile page that replaces a placeholder when you open a patient:
- Header: back button ("← Patients") → emits `back_requested` (wired to navigate back to Patients list), patient name, Edit and (per role) Delete buttons.
- Metadata strip: code, phone, gender, age, blood group, last visit, visit count.
- **Summary tab:** field grid (code/phone/emergency/email/gender/age/DOB/blood) plus a Clinical Information card showing address, chief complaint, medical history, allergies, notes.
- **Visits & Chart tab:** left pane has "+ New visit" button + visit list (date, dentist, status, reason); selecting a visit rebuilds the right pane with a read-only dental chart showing that visit's findings (auto-detects pediatric vs adult based on findings) plus rich detail text (date/dentist/status/reason/CC/OE/advice/per-tooth findings). Above the list, a "Current dental chart" shows the latest state of the mouth across all visits — exactly what a clinician expects.
- **Prescriptions / Invoices / Attachments** tabs are placeholder cards (populated in Phases 8, 10, 11).

### Navigation & deep-linking
- New dynamic route `"patient_profile"` is registered in `navigation.py` but not pre-populated in the stack — the profile is created lazily per patient to keep memory low.
- `MainWindow.open_patient_profile(patient_id)` replaces any existing profile widget, constructs a fresh `PatientProfileView`, loads the patient, and switches the stack.
- `MainWindow._on_search_result` now routes `patients` hits to `open_patient_profile()` instead of just navigating to the list, so pressing Enter on a patient in Ctrl+K/Ctrl+F global search opens their profile directly.
- Patients list emits `patient_opened(pid)` on double-click / Open button; main window routes it to `open_patient_profile`.
- Profile's back button returns to Patients list.
- `navigate_to()` now calls `refresh()` on the target view, so returning from a profile to the list refreshes it.

### Fix / consistency
- `audit_service.record()` was switched to `local_now()` in Phase 5 — confirmed still consistent with the rest of the schema.
- Staff users table now uses `#DpDataTable` object name so it picks up shared table styling; Patients and Staff tables look identical.
- QSS added for `#DpDataTable` (cards-style borders, padded rows, bold header, primary-color selection) in Phase 5 — now also applies to any future data tables.

### Tests (75 total, +12)
Added:
- `tests/services/test_visits.py` (8 tests):
  1. `test_create_visit_records_visit_count_and_audit` — creates visit with caries + filled findings, asserts `visit_count==1`, `last_visit_at` set, findings round-trip, audit event recorded
  2. `test_invalid_finding_or_tooth_rejected` — bad tooth code and bad finding code both raise ValidationError
  3. `test_close_visit_prevents_further_edits` — closed visit rejects `set_tooth_finding`
  4. `test_latest_chart_state_merges_visits` — latest finding per tooth wins across two visits (46 goes caries → filled)
  5. `test_rbac_denies_assistant_create` — Assistant (view-only) cannot create visits
  6. `test_list_visits_ordered_newest_first`
  7. `test_set_tooth_finding_adds_to_open_visit`
  8. `test_findings_constants_have_color` — palette entries have colors
- `tests/unit/test_dental_chart.py` (4 tests):
  1. Adult FDI→ADA mapping spot-checks (18→1, 11→8, 21→9, 28→16, 38→17, 31→24, 41→25, 48→32)
  2. Pediatric FDI→ADA (55→E, 65→J, 75→P, 85→O)
  3. Invalid codes return ""
  4. Finding palette complete / has colors and labels

### Quality gates
```
$ ruff check dentiva tests
All checks passed!

$ mypy dentiva
Success: no issues found in 104 source files

$ pytest tests/
============================== 75 passed in 32.00s ==============================
```

## RBAC applied
| Action | Permission |
|---|---|
| View visits / chart | `visits.view` |
| Create new visit | `visits.create` |
| Edit visit / mark chart | `visits.edit` + `chart.edit` |
| Edit patient (on profile) | `patients.edit` |
| Delete patient (on profile) | `patients.delete` |

UI hides the Edit/Delete/New-visit buttons when the principal lacks permission; service methods independently re-check permissions. Assistant role (view-only) cannot create visits; test coverage confirms.

## Notable design decisions
1. **Per-encounter chart history, not live-chart mutation.** Every dental-chart finding is attached to a `visit_id`; there is no "current chart" table. The current state of the mouth is computed as the most recent finding per tooth across all visits (`latest_chart_state`). This guarantees a complete audit trail — you can rewind to any visit and see exactly what the chart looked like that day — without requiring a separate snapshot mechanism.
2. **'Healthy' is an eraser.** Selecting Healthy in the palette removes any finding for that tooth on the *current* visit, letting the dentist correct mistakes. It never writes a 'healthy' row; it only deletes.
3. **Closed visits are immutable.** Once finalised, findings cannot be edited (the dialog checks status). To correct a mistake you open a new visit. This preserves medical-record integrity.
4. **record_visit is invoked by create_visit** so `last_visit_at`, `visit_count`, and `age_cache` stay correct automatically (future modules that create visits — e.g., walk-in checkups without chart entries — can call `create_visit` with empty findings and the counts still update).
5. **ADA notation as annotation, not primary key.** All storage and code use FDI (the global standard for clinical charting in Bangladesh/Asia/most of the world); ADA Universal is shown as a small grey label underneath each tooth for dentists trained in that system.
6. **Profile is lazily constructed** each time you open a patient so stale data doesn't persist across edits/visits; navigating away discards it.
7. **Auto pediatric detection** when viewing historical visits: if any finding tooth code starts with 5/6/7/8, the chart renders in pediatric layout automatically.

## Known intentional deferrals
- Actual tooth-click surface selection (occlusal/mesial/distal/buccal/lingual) — v1 marks the whole tooth with a single finding; per-surface charting will come in Phase 7 along with the full treatment-record flow (cavity surface selection matters mostly for fillings/RCT which are charted in detail then).
- Tooth notes and surface sub-selection on findings.
- Summary KPIs in the profile (total invoices, outstanding balance, next appointment) — those require Phase 7 Appointments and Phase 10 Invoices.
- Attachments tab (X-ray uploads) — Phase 11.
- Print/export patient summary — Phase 10+.
- Pediatric/adult toggle for creating a new visit on an adult patient who still has deciduous teeth — v1 defaults to adult but lets you switch via the dropdown before saving, which is sufficient for mixed-dentition cases.

## Files changed
- Added: `dentiva/services/visit_service.py`, `dentiva/ui/widgets/dental_chart.py`, `dentiva/ui/dialogs/visit_dialog.py`, `dentiva/ui/views/patients/profile_view.py`, `tests/services/test_visits.py`, `tests/unit/test_dental_chart.py`
- Modified: `dentiva/services/audit_service.py` (import grouping fix for the local_now change from Phase 5), `dentiva/ui/main_window.py` (dynamic profile route + deep-linking + PatientsView.signal wiring), `dentiva/ui/navigation.py` (registered patient_profile placeholder), `dentiva/ui/views/patients/__init__.py` (docstring), `dentiva/ui/views/staff/staff_view.py` (`#DpDataTable` shared object name).

## Next (Phase 7) — Appointments & Queue
Pending your explicit "Continue". Planned: calendar view (day/week), appointment CRUD dialog (patient picker, dentist, time, duration, reason, status), walk-in registration, queue board (drag-to-reorder, start/finish visit, per-dentist columns), appointment reminders shown in notifications, and marking arrived → creates or links a visit (Phase 6) so flow from appointment → visit → chart is complete.
