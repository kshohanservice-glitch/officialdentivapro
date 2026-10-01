# Phase 9 Report — Invoices & Payments

**Status:** Phase 9 complete. 107/107 tests pass (+13 new). `ruff` clean, `mypy` clean (118 source files). Ready for review/merge before Phase 10.

## What shipped

### Invoice service (`dentiva/services/invoice_service.py`)
Immutable-after-posting invoicing with BDT (paisa-integer) totals, automatic numbering, line items, discount/tax, visit-to-invoice creation and full RBAC.

| Function | Purpose | RBAC |
|---|---|---|
| `list_invoices` | Filterable by patient/visit/status/date range; newest-first. | `invoices.view` |
| `get_invoice` | Full invoice with line items loaded. | `invoices.view` |
| `get_invoice_by_number` | Lookup by INV-... number. | `invoices.view` |
| `create_invoice` | Creates a draft invoice with auto-number (`INV-YYYYMMDD-NNNN`, per-calendar-day sequence), patient/dentist inherited from visit if given; validates lines have descriptions and non-negative prices. | `invoices.create` |
| `update_invoice` | Edits a **draft** invoice (lines/discount/tax/notes/date); recalculates totals; posted/voided invoices rejected. | `invoices.edit` |
| `create_invoice_from_visit` | Convenience: builds line items directly from a visit's treatment records (name snapshotted with tooth codes in parentheses, price snapshotted from the record), supports `auto_post=True` to post immediately. | `invoices.create` |
| `post_invoice` | Finalizes invoice: sets `is_posted=True` + `posted_at=now`, computes status (unpaid/partial/paid). Requires at least one line. After post, lines/totals are immutable. | `invoices.edit` |
| `void_invoice` | Voids a posted invoice with a required reason (sets `voided_at`, `void_reason`, `status=void`). Payments remain attached and must be explicitly reversed if refunded. | `invoices.void` |
| `delete_invoice` | Hard-delete of **draft** invoices only (posted → must void). | `invoices.edit` |
| `invoice_paid_total` | Sum of non-reversed payments for an invoice. | — |
| `refresh_invoice_paid` | Recalculates `paid_paisa`, `due_paisa`, and `status` after payment changes. | — |

**Totals math (in paisa):** `subtotal = Σ(line_total)`, `total = max(0, subtotal - discount + tax)`, `due = max(0, total - paid)`, status = `unpaid|partial|paid|void|draft`. Overpayments are permitted (paid can exceed total; status clamped to `paid`, due stays at 0).

**Price snapshots at line level:** Each `InvoiceLineItem` carries its own `description` and `unit_price_paisa`. When referencing a catalog or treatment record, prices/descriptions are snapshotted to the line at add time. If the catalog is later re-priced, the invoice doesn't change.

**Invoice numbers:** Format `INV-YYYYMMDD-NNNN` (4-digit zero-padded per calendar day). Numbering scans existing invoices for the day's prefix and increments the maximum suffix, so multiple workstations writing offline still produce unique numbers within a clinic (subject to ordering — good enough for a single-clinic offline app).

### Payment service (`dentiva/services/payment_service.py`)
| Function | Purpose | RBAC |
|---|---|---|
| `list_payment_methods` | Lists active (or all) payment methods in sort order (Cash/bKash/Nagad/Rocket/Upay/Card/Bank/Other — seeded by `db/seed.py`). | view |
| `list_payments` | Filterable by invoice/patient/method/date-range; includes reversed payments (flagged); newest-first. | `payments.view` |
| `get_payment` | Single payment with method/patient/invoice names joined. | `payments.view` |
| `record_payment` | Records a payment against a **posted** invoice (rejects draft and void). Validates amount > 0 and method active. After insert, refreshes invoice `paid_paisa/due_paisa/status`. Accepts partial payments and overpayments. | `payments.create` |
| `reverse_payment` | Soft-reverses a payment (sets `reversed_at` + reason, refreshes invoice totals so status goes back to partial/unpaid as appropriate). Requires a reason (for audit). Cannot double-reverse. | `payments.refund` |

**Payment method list** is pre-seeded in Phase 5 (`db/seed.py`) and includes Cash, bKash, Nagad, Rocket, Upay, Card, Bank Transfer, Other — matching the spec's exact set.

### Status transitions
Invoice: `draft → posted (unpaid → partial → paid)`; `void` from any non-void state; `paid` can return to `partial` via `reverse_payment`. No line-item mutation after post.
Payments: active → reversed (flag, never deleted).

### Invoice dialog (`dentiva/ui/dialogs/invoice_dialog.py`)
Two-tab modal dialog:

1. **Line items tab**
   - Date picker (calendar popup, defaults to now), Discount (৳), Tax (৳), Notes.
   - "+ Add line" inserts a new table row: Description (free text), Catalog/Ref dropdown (populated from active treatment catalog with prices shown), Qty (spinbox 1-100), Unit price (৳ input using `parse_bdt`), Line total (auto-computed live).
   - "Load from visit treatments" button (enabled when `visit_id` is provided) auto-populates lines from the visit's treatment records (name + tooth codes + snapshotted prices).
   - Per-row remove button; live totals bar at the bottom (Subtotal / Discount / Tax / **TOTAL** / Paid / Due, Due coloured red when outstanding).
2. **Payments tab**
   - Record payment row: Method dropdown (active methods), Amount, Reference/TrxID (optional), Notes, "Record payment" button.
   - Payment history table: Date, Method, Amount (line-through + grey when reversed), Reference, Notes (shows reversal reason). Per-row "Reverse" button (visible only if principal has `payments.refund`), prompts for reason.
   - Totals bar updates in real time as payments are added.

Dialog footer buttons: **Post & finalize** (primary, posts and locks), **Save draft** (saves without locking), **Void** (danger, only visible on posted invoices, prompts for reason), **Close**.

### Invoices view (`dentiva/ui/views/invoices/invoices_view.py`)
Global invoice browser:
- Search by patient name or invoice number; status filter (All / Draft / Unpaid / Partial / Paid / Void); date range (default last 30 days).
- Columns: Invoice #, Date, Patient, Total, Paid, Due (coloured red when outstanding), Status (coloured: draft amber, unpaid red, partial amber, paid green, void grey).
- Double-click to open the invoice dialog for that invoice.

### Payments view (`dentiva/ui/views/payments/payments_view.py`)
Global payment journal:
- Search by patient/invoice#/reference; method filter; date range (default last 30 days).
- Columns: Date, Patient, Invoice #, Method, Amount (line-through + "(reversed)" for reversed payments), Reference (includes reversal reason).
- Shows both payments and reversals in one unified ledger (reversals don't create separate rows; they annotate the original).

### Patient profile Invoices + Prescriptions tabs
Patient profile now has live **Prescriptions** and **Invoices** tabs replacing the Phase 8/10 placeholders:
- **Prescriptions tab** — table of the patient's prescriptions (Date/Medicines/Status), "+ New prescription" button (respects `prescriptions.create`), double-click or "Open" to view/edit. Finalized prescriptions show green "Finalized" status.
- **Invoices tab** — table of the patient's invoices (Invoice #/Date/Total/Paid/Due·Status), "+ New invoice" button, double-click to open the invoice dialog. Due amounts coloured by status.

### Queue "Start" opens VisitDialog (already done Phase 8); clinicians finish chair-side, save/close visit, then create/post invoice (either from patient profile Invoices tab, or from Invoices view → New → pick visit, or a single-click "Invoice from visit" available via the `create_invoice_from_visit` service).

### Tests added (+13; total 107)
**`tests/services/test_invoices.py` (8):**
1. `test_invoice_numbering_and_basic_totals` — creates two-line invoice; verifies subtotal/discount/tax/total math (109000 - 5000 + 10000 = 114000); same-day numbering increments.
2. `test_post_locks_and_requires_lines` — empty invoice cannot post; posting sets `is_posted`/`posted_at`; subsequent edits are rejected.
3. `test_create_from_visit` — building from visit treatment records produces 2 lines with correct subtotal (200000), discount/tax applied, `auto_post=True` posts immediately.
4. `test_visit_with_no_treatments_fails` — guards against empty visit invoices.
5. `test_void_requires_reason_and_blocks_payment` — voiding without reason rejected; voided invoice blocks payments.
6. `test_delete_only_draft` — posted invoices cannot be deleted (must void).
7. `test_negative_price_rejected` — line validation rejects negative unit prices.
8. `test_rbac_assistant_cannot_create_invoice` — Assistant denied.

**`tests/services/test_payments.py` (5):**
1. `test_payments_flow_partial_to_paid` — partial cash (partial status) → bKash top-up (paid); overpayment allowed (status stays paid, due 0).
2. `test_cannot_pay_unposted_or_void` — draft and voided invoices reject payments.
3. `test_reverse_payment_updates_totals` — reversing a payment restores status to unpaid; reason required.
4. `test_zero_or_negative_payment_rejected` — zero/negative amounts rejected.
5. `test_rbac_receptionist_can_record_payment` — Receptionist can record payments but cannot reverse (refund permission only for Accountant).

### Quality gates
```
$ ruff check dentiva tests
All checks passed!
$ mypy dentiva
Success: no issues found in 118 source files
$ pytest tests/
============================== 107 passed in 58.70s ==============================
```

End-to-end smoke (in-memory temp DB): created "Filling ৳1000" catalog → added to visit (tooth 36) → created invoice from visit with ৳50 discount (total 95000 paisa = ৳950) → posted → paid ৳500 cash (status partial, due ৳450) → paid remaining ৳450 via bKash (status paid, due 0).

## RBAC summary
| Action | Permission |
|---|---|
| View invoices/payments | `invoices.view`, `payments.view` |
| Create draft invoice | `invoices.create` |
| Edit draft / post invoice | `invoices.edit` |
| Void invoice | `invoices.void` |
| Print invoice (gate; real print ships Phase 10) | `invoices.print` |
| Record payment | `payments.create` |
| Reverse/refund payment | `payments.refund` |

Default roles (Administrator/Dentist/Receptionist/Assistant/Accountant) were seeded with the appropriate flags in `db/seed.py` from earlier phases; this phase exercises Receptionist-can-record-but-not-refund and Assistant-view-only behaviour.

## Notable design decisions
1. **Post-to-lock, same pattern as prescriptions.** Once an invoice is posted its lines and totals are immutable. To correct a mistake you void the invoice (with a typed reason) and issue a new one. This mirrors real-world accounting (you don't silently edit a finalized invoice).
2. **Draft invoices allow unlimited editing** so a receptionist can start an invoice, save it mid-entry, and come back to it later.
3. **No physical deletion of payments or posted invoices** — payments are soft-reversed with a reason; posted invoices are voided. The payments journal is a complete, append-only-with-reversals audit trail.
4. **Payments refresh invoice status immediately**, always via `refresh_invoice_paid`, so a partial payment never leaves the invoice in `unpaid`.
5. **Price/discount/tax are in whole-৳ inputs in the UI** (`QLineEdit` parsed via `parse_bdt` which strips ৳ and commas), but stored as integer paisa in the DB — all arithmetic is integer-based, no float errors.
6. **Line totals computed live in the UI** for instant feedback while the receptionist is typing; the service recomputes from scratch on save (UI totals are advisory; services are source of truth).
7. **Invoice numbering uses local date** (`local_now()` which respects the configured Asia/Dhaka timezone from `core.dates`) so clinics operating past midnight in UTC still get the correct calendar-day prefix.
8. **Visit→Invoice convenience** (`create_invoice_from_visit`) lets a receptionist click one button to invoice an entire visit's worth of treatments, but the dialog's "Load from visit treatments" button lets them start from the visit and adjust (add a consumables line, apply discount, etc.) before posting.
9. **No foreign-key cascade delete from patient/dentist** (`ondelete="RESTRICT"` / `"SET NULL"`) so invoices remain linked to financial history even if a dentist is deactivated; patients cannot be deleted if they have invoices (RESTRICT matches our Phase 5 patient-service guard that requires no financial history before delete).
10. **Payment reference_no** is free-text to hold bKash/Nagad/Rocket/Upay transaction IDs or bank cheque numbers.

## Known intentional deferrals
- **Invoice chit / A4 print** — Print buttons exist (Payment "Print…" placeholder already in PrescriptionDialog; Invoice print is the next big piece of the unified print subsystem in Phase 10).
- **Credit notes / overpayment carry-forward** — overpayments currently leave paid > total; v1 treats the invoice as paid with due=0 but does not create a separate credit to apply to future invoices. This matches many small Bangladeshi clinics that just treat overpayments as cash-in-hand for the next visit; a formal credit-note system is a polish item.
- **Multi-currency** — spec mandates BDT/৳ only; no FX.
- **Tax rates / VAT config** — Tax is an explicit paisa amount entered per-invoice. Percentage taxes / preset VAT rates can be added via Settings later without schema change.
- **Installment plans** — out of v1 scope; partial payments already cover ad-hoc split payments.
- **Due-date reminders / overdue notifications** — will hook into the existing notification centre in a polish phase.
- **Discount percentages** — only flat-৳ discounts in v1; % discount adds rounding complexity and is deferred.
- **Daily closing / cash drawer reconciliation** — belongs in Phase 12 admin/reporting polish.

## Files changed
- Added: `dentiva/services/invoice_service.py`, `dentiva/services/payment_service.py`, `dentiva/ui/dialogs/invoice_dialog.py`, `dentiva/ui/views/invoices/__init__.py`, `dentiva/ui/views/invoices/invoices_view.py`, `dentiva/ui/views/payments/__init__.py`, `dentiva/ui/views/payments/payments_view.py`, `tests/services/test_invoices.py`, `tests/services/test_payments.py`, `PHASE9_REPORT.md`.
- Modified: `dentiva/ui/main_window.py` (late-bind InvoicesView + PaymentsView), `dentiva/ui/views/patients/profile_view.py` (live Prescriptions + Invoices tabs replace placeholders; "New prescription", "New invoice", double-click open wired).

## Next (Phase 10) — Print System (Prescriptions, Invoices, Chits, PDF)
Pending your explicit "Continue". Planned: QPainter-based paper-aware renderers for A4 / A5 / thermal (58mm/80mm) with Bangla font shaping via the system's Noto/Siyam/Rupali fonts, clinic letterhead (name/address/license/logo), signature block, PDF export, Windows print dialog integration, prescription and invoice chit preview, and a print queue + settings panel (default paper size per doc type, default printer, font selection).
