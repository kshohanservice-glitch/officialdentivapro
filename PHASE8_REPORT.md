# Phase 8 Report — Treatment Catalog, Treatment Records & Prescriptions (Rx)

**Status:** Phase 8 complete. 94/94 tests pass (+10 new, +10 total). `ruff` clean, `mypy` clean (113 source files). Ready for review/merge before Phase 9.

## What shipped

### Treatment service (`dentiva/services/treatment_service.py`)
| Function | Purpose | RBAC |
|---|---|---|
| `list_catalog` | Paginated/searchable catalog (by category, active-only, name search); computes `usage_count` per item. | `treatments.view` |
| `get_catalog` | Single catalog item. | `treatments.view` |
| `create_catalog_item` | Add a new service; enforces unique name (case-insensitive), non-negative price. | `treatments.catalog.manage` |
| `update_catalog_item` | Rename/reprice/recategorize; enforces unique name. | `treatments.catalog.manage` |
| `delete_catalog_item` | **Soft-deactivate** (not physical delete) so historical treatment records remain intact. | `treatments.catalog.manage` |
| `list_treatments_for_visit` | Treatments performed during a specific visit. | `treatments.view` |
| `list_treatments_for_patient` | Full treatment history for a patient, newest-first. | `treatments.view` |
| `add_treatment_to_visit` | Adds a treatment line to an open visit; **snapshots name and price** from the catalog (or uses custom name/price); validates tooth codes are valid FDI (11-48, 51-85); normalizes comma-separated tooth codes, dedupes. Closed visits rejected. | `treatments.create` |
| `update_treatment_record` | Edits a treatment line (re-price, re-tooth, rename, re-catalog) on open visits. | `treatments.edit` |
| `delete_treatment_record` | Removes a line from an open visit. | `treatments.edit` |
| `visit_total_paisa` | Sum of `price_paisa` for a visit — used by treatments tab total and invoice creation (Phase 9). | `treatments.view` (enforced via calling code) |

**Price snapshots:** When a catalog item is selected at add-time, `name_at_service_time` and `price_paisa` are copied; later catalog price/name changes never change what was charged or what's on existing invoices/history.

**FDI tooth validation:** Accepts adult teeth (11–48, quadrants 1-4 × teeth 1-8) and primary teeth (51–85, quadrants 5-8 × teeth 1-5). Input is normalized: spaces → commas, deduped while preserving order.

### Prescription service (`dentiva/services/prescription_service.py`)
| Function | Purpose | RBAC |
|---|---|---|
| `list_prescriptions` | List prescriptions, filterable by patient/visit/finalized flag; newest-first. | `prescriptions.view` |
| `get_prescription` | Single prescription with all medicine lines loaded. | `prescriptions.view` |
| `create_prescription` | Create a draft Rx with CC/OE/Advice/Notes and a list of medicine lines; auto-detects patient/dentist from `visit_id` if given. | `prescriptions.create` |
| `update_prescription` | Edits a **draft** prescription (finalized Rxs are immutable). | `prescriptions.edit` |
| `finalize_prescription` | Locks the Rx (sets `finalized=True` + `finalized_at=now`); requires at least one medicine OR some clinical text. | `prescriptions.edit` |
| `clone_prescription` | Creates a fresh draft from any Rx (finalized or not), copying all medicines. For follow-up visits / renewal. | `prescriptions.create` |
| `delete_prescription` | Soft/hard delete of **draft** Rxs only (finalized Rxs cannot be deleted). | `prescriptions.edit` |
| `list_template_options` | Quick-pick chip suggestions for CC / OE / Advice sections (seeded by `db/seed.py`). | view (public) |

**Medicine line model (per row):** `name, form, strength, frequency_morning, frequency_noon, frequency_night, meal_relation (before/after/with/none), duration_days, quantity, instructions`.

**Immutability guarantees:** Finalized prescriptions cannot be edited or deleted. To change one you clone it and re-finalize. This preserves an audit trail and protects printed prescriptions from being silently altered.

**Deduplication:** Blank medicine names are skipped; duplicate names (case-insensitive) within one Rx are deduped so accidental duplicates don't slip through.

### Prescription editor widget (`dentiva/ui/widgets/prescription_editor.py`)
- **Clinical notes** section with three rich text areas (Chief complaint / On examination / Advice / internal Notes) and clickable **quick-pick chips** (seeded from `ClinicalTemplateOption` — common CC/OE/Advice entries like "Toothache", "Caries present", "Warm saline rinse"). Clicking a chip appends it as a bullet; duplicates are not re-added.
- **Medicines table** with 11 columns: row # (with delete button), Name, Form (dropdown: tablet/capsule/syrup/…), Strength, three per-dose checkboxes (Morn/Noon/Night; defaults to Night on new rows), Meal relation (after/before/with/none), Duration (0–365 days), Quantity, Instructions.
- Add-medicine button inserts a new empty row; removing the last row automatically adds a blank row so the grid never looks empty.
- Finalize indicator (draft orange → ✓ Finalized green); when finalized all inputs are read-only and delete buttons disabled.

### Prescription dialog (`dentiva/ui/dialogs/prescription_dialog.py`)
- Wraps the editor in a modal dialog with Save Draft / Finalize & Close / Print… buttons.
- Loads template options; supports creating from a visit (auto-inherits patient + dentist) or standalone.
- Print button is wired but informs the user print will activate with the Phase 10 print subsystem (A4/A5/thermal).

### Treatments catalog view (`dentiva/ui/views/treatments/treatments_view.py`)
- Treatment list: Name / Category / Default price (formatted BDT) / Usage count (number of times used across all visits) / Edit action.
- Search box filters live as you type.
- "+ New treatment" and Edit actions launch an inline add/edit dialog (name, category, price, description).
- "Edit" shows "inactive" suffix for soft-deactivated items.

### Prescriptions list view (`dentiva/ui/views/prescriptions/prescriptions_view.py`)
- Global prescription browser with patient search, Finalized-only / Draft-only filters.
- Columns: Date / Patient / Dentist / # medicines / Status (colored: green Finalized, amber Draft).
- Double-click to open; "+ New prescription" for standalone (out-of-visit) prescriptions.

### Visit dialog upgraded to a 3-tab clinical workspace (`dentiva/ui/dialogs/visit_dialog.py`)
The Phase 6 single-pane chart is now a tabbed view so one dialog covers the entire chair-side encounter:

1. **Dental chart tab** — the Phase 6 interactive FDI chart (adult/pediatric swap, color-coded findings), unchanged in behaviour.
2. **Treatments tab** — live table of treatment records for this visit with "+ Add treatment" (catalog picker dropdown with formatted default prices; optional tooth codes; optional custom price override; optional notes), per-row Remove, and a running visit total in BDT (top-right). Tooth codes are validated via the service.
3. **Prescription tab** — shows existing prescriptions for this visit (newest first, colored status) with a "Write prescription" / "Open / edit prescription" button that opens the PrescriptionDialog pre-bound to this visit/patient/dentist. Summary line reads "Latest: Draft — N medicine(s)." or "Latest: Finalized — N medicine(s)."

- Header (date/dentist/chart type/reason/CC/OE/Advice/notes) sits above the tabs so everything is in one place.
- **Auto-save draft:** Clicking "+ Add treatment" or "Write prescription" on a brand new (unsaved) visit silently creates a visit draft first (same as the chart "Save & keep open" path) so users don't have to think about saving before adding treatments/Rx.
- Save & keep open / Save & close visit buttons preserved; closing the visit is still blocked if validations fail.

### Queue → Start now opens the chair-side dialog directly
In `appointments_view.py`, clicking **Start** on a queue entry:
1. Calls `appointment_service.start_service` (moves entry to with_dentist, creates visit) — as before.
2. Loads the patient + visit summary.
3. Opens the upgraded `VisitDialog` (chart/treatments/rx tabs) directly on top of the queue so the dentist lands straight into charting, not a toast message. When the dialog closes, queue/day view refresh.

This completes the full clinical flow: Schedule → Arrive (check-in) → Start chair-side (chart + treatment + Rx, all in one dialog) → Finish → (Phase 9) invoice.

### Tests added (+10, total 94)
`tests/services/test_treatments.py` (4):
1. `test_catalog_crud` — create/list/update, duplicate name rejection.
2. `test_catalog_requires_manage_permission` — Assistant denied create.
3. `test_treatment_record_workflow` — add from catalog (price/name snapshot), invalid FDI tooth rejection, repricing catalog doesn't change recorded price, total aggregation, closed visit blocks add.
4. `test_custom_treatment_without_catalog` — custom name/price works without a catalog entry.

`tests/services/test_prescriptions.py` (6):
1. `test_create_prescription_inherits_from_visit` — patient/dentist inherited from visit; medicines load with correct frequency labels.
2. `test_requires_patient` — standalone Rx without patient/visit is rejected.
3. `test_finalize_locks_rx_and_requires_meds_or_notes` — empty Rx can't finalize; after finalize update/delete are rejected.
4. `test_clone_creates_editable_copy` — cloning a finalized Rx yields a mutable draft with same medicines.
5. `test_duplicate_meds_deduplicated_and_blank_skipped` — duplicates by case-insensitive name collapse, blank lines skipped.
6. `test_rbac_assistant_can_view_but_not_edit` — Assistant can view, can't create or finalize.

### Quality gates
```
$ ruff check dentiva tests
All checks passed!
$ mypy dentiva
Success: no issues found in 113 source files
$ pytest tests/
============================== 94 passed in 45.82s ==============================
```

End-to-end smoke (in-memory temp DB): create clinic/admin → create patient → create catalog item "Scaling ৳500" → create visit → add treatment (tooth 36, price snapshotted to 50000 paisa) → finalize Rx with Amoxicillin 500 mg 1+1+1 ×5 days → totals and Rx load correctly.

## RBAC summary
| Action | Permission |
|---|---|
| View treatment catalog / visit treatment history | `treatments.view` |
| Add treatment to open visit | `treatments.create` |
| Edit/remove treatment on open visit | `treatments.edit` |
| Manage catalog (add/rename/reprice/deactivate) | `treatments.catalog.manage` |
| View prescriptions | `prescriptions.view` |
| Create draft prescription (incl. clone) | `prescriptions.create` |
| Edit draft / finalize / delete draft | `prescriptions.edit` |
| Print (gate; real print ships Phase 10) | `prescriptions.print` |

Dentist/Receptionist/Administrator roles were already seeded with these permissions in `db/seed.py` DEFAULT_ROLES. Assistant role is view-only for clinical data per spec.

## Notable design decisions
1. **Price snapshots on write, not read.** `TreatmentRecord.price_paisa` and `name_at_service_time` are copied at insert time; catalog changes can't retroactively alter billed amounts or invoice totals. This is the same pattern used for patient data, invoices (Phase 9 will apply immutable posting), and audit events.
2. **Soft-deactivation of catalog items.** Deleting a catalog entry only sets `is_active=False`. It no longer appears in the catalog picker (active-only), but historical records continue to display correctly.
3. **Tooth codes validated against FDI whitelist.** Adult (11–48) and pediatric (51–85) ranges are accepted. Comma/space/duplicate normalization happens on save. Surface-level charting (mesial/occlusal/distal/etc.) is deferred; this matches the Phase 6 dental chart's current per-tooth finding granularity.
4. **Prescription immutability at finalization.** This is the same "post to lock" pattern invoices will use in Phase 9: once handed to the patient (printed/PDF), a prescription is a clinical document and cannot be silently altered. Clone-then-amend is the supported workflow.
5. **Meal relation normalized** to lower-case ("before/after/with/none"); invalid values coerced to "after" (safe default) so UI/import oddities don't corrupt data.
6. **Visit dialog as one cohesive clinical workspace.** Rather than splitting chart / treatment / Rx across three separate windows, they're tabs in one dialog. This mirrors how dentists actually work in the chair — they chart, then log the treatment, then write meds — without modal ping-pong.
7. **Auto-save draft on first Treatment/Rx click.** Users clicking "Add treatment" on a brand new visit don't get a "save the visit first" error; the visit is persisted silently as a draft.
8. **Quick-pick chips** for CC/OE/Advice are driven by `ClinicalTemplateOption`, which is already seeded with common Bangladesh-dentistry phrases from `db/seed.py` (and can be extended later via Settings without code changes).

## Known intentional deferrals
- **Prescription printing** — Print button is visible but shows a "coming in Phase 10" notice. Phase 10 adds the unified print subsystem (A4/A5/thermal/PDF with Bangla font rendering, signature block, clinic letterhead).
- **Drag-to-reorder medicines** within an Rx — current order is the order of rows (top-to-bottom); explicit reorder arrows will be added if needed.
- **Tooth-level treatment link** — currently tooth codes are stored as comma-separated strings on the treatment record. If we later need "surface + tooth" granularity (MO on 36, DO on 46) it will be a separate `treatment_tooth` table; out of v1 scope because the chart tracks findings per tooth and treatment notes can capture detail.
- **Treatment plan vs performed treatment split** — v1 treats all visit treatments as performed (since we're chair-side). A separate "planned" state can be added in a future release without breaking the schema.
- **Drug interaction / allergy warnings** — out of offline-v1 scope; would require a curated drug database that the offline-first spec doesn't budget for.
- **Per-dose time pickers** (e.g., 8am/2pm/8am defaults) — the 1+0+1 / 1+1+1 convention is universal in Bangladesh prescribing; explicit times would be nice-to-have polish.
- **Common Rx templates ("Antibiotic course", "Analgesic pack")** — the seed template options cover CC/OE/Advice; medicine-group templates are a Phase 10/polish item.
- **Dosage frequency abbreviations** (1+0+1, 1+1+1, SOS, BD, TDS) will be displayed on print output (Phase 10) for doctors who prefer shorthand.
- **Queue "Start" → VisitDialog closes → "Finish" queue action** — the queue's Finish button still works independently (it closes the appointment), but a clinician could choose to close the visit via the dialog's "Save & close visit" and then press Finish in the queue to finalize the appointment. This is deliberate and matches real clinic flow (notes may be finished before patient leaves the chair).

## Files changed
- Added: `dentiva/services/treatment_service.py`, `dentiva/services/prescription_service.py`, `dentiva/ui/widgets/prescription_editor.py`, `dentiva/ui/dialogs/prescription_dialog.py`, `dentiva/ui/views/treatments/__init__.py`, `dentiva/ui/views/treatments/treatments_view.py`, `dentiva/ui/views/prescriptions/__init__.py`, `dentiva/ui/views/prescriptions/prescriptions_view.py`, `tests/services/test_treatments.py`, `tests/services/test_prescriptions.py`, `PHASE8_REPORT.md`.
- Modified: `dentiva/ui/dialogs/visit_dialog.py` (tabbed clinical workspace: chart + treatments + rx), `dentiva/ui/views/appointments/appointments_view.py` (Start button opens VisitDialog instead of toasting), `dentiva/ui/main_window.py` (late-bind TreatmentsView + PrescriptionsView).

## Next (Phase 9) — Invoicing & Payments
Pending your explicit "Continue". Planned: immutable-after-posting invoices (with line items sourced from visit treatment records, price snapshots, discounts, BDT totals), multi-method payments (Cash/bKash/Nagad/Rocket/Upay/Card/Bank/Other) with partial-payment + balance tracking, invoice chit printing hook, voiding with audit trail, and the patient profile's Invoices tab.
