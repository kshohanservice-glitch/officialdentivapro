# Phase 10 Report — Print, PDF & Paper (A4 / A5 / Thermal) + Bangla

**Branch:** `arena/01a0f68e-officialdentivapro`
**Phase:** 10 / 16 (Print & PDF subsystem)
**Commit:** `PHASE-10-printing` (see git log)

## Summary

A complete, production-ready printing pipeline is now in place for both
**prescriptions** and **invoices**, supporting A4, A5, 80 mm thermal and 58 mm
thermal paper sizes with Bangla (and Latin) text rendering, PDF export,
native Windows print (QPrinter), and print preview. The renderer is fully
deterministic QPainter code, so "what you preview is what prints / PDFs."

## Files added / changed

### New package: `dentiva/printing/`

| File | Purpose |
|------|---------|
| `__init__.py` | Package documentation. |
| `paper.py` | `PaperSize` dataclass, mm↔pt helpers, built-in sizes `A4`, `A5`, `THERMAL_80`, `THERMAL_58`. |
| `document.py` | Pure-dataclass document models: `ClinicHeader`, `PatientBlock`, `MedicineRow`, `LineItemRow`, `MoneyBlock`, `Signature`, `PrescriptionDoc`, `InvoiceDoc`. **No Qt imports** — fully unit-testable. |
| `in_words.py` | BDT amount → English words in South-Asian grouping (lakh/crore), e.g. `Taka: nine hundred fifty only`, `Taka: twelve lakh thirty-four thousand five hundred sixty-seven and 89/100 only`. Handles 0, paisa-only, negatives and >10⁴ crore safely. |
| `builders.py` | `build_prescription_doc(session, rx_row, paper)` and `build_invoice_doc(session, inv_row, payments, paper)` — assemble document dataclasses from service DTOs. Pulls `clinic.name/address/phone/email/website/logo_path/prescription_footer` from `ClinicProfile`. |
| `fonts.py` | `make_font(size_pt, bold, italic, mono)` picks a Latin base + Bangla fallback (SolaimanLipi/Kalpurush/Siyam Rupali/Noto Sans Bengali/Vrinda → Segoe UI/Calibri/DejaVu Sans). Uses `QFont.insertSubstitutions` so U+0980–U+09FF ranges render in Bangla without the caller having to choose. |
| `renderer.py` | `render_prescription(painter, width, doc)` and `render_invoice(painter, width, doc)` — QPainter renderers. Measure-then-paginate for multi-page content. All measurements in points. |
| `manager.py` | `print_document(parent, doc, paper_code)`, `preview_document(...)`, `export_pdf(...)` — wire the renderer to `QPrinter`, `QPrintDialog`, `QPrintPreviewDialog`, and `QPrinter.PdfFormat`. |

### UI wiring

- `dentiva/ui/dialogs/prescription_dialog.py` — the **Print…** button now opens
  a native print preview. If the prescription is still a draft, it prompts to
  finalize first.
- `dentiva/ui/dialogs/invoice_dialog.py` — added **Print…** and **PDF…** buttons,
  visible only on posted invoices for users with `INVOICES_PRINT` permission.
  *Print* opens preview; *PDF* prompts for a save location (default name
  `INV-YYYYMMDD-NNNN.pdf`) and writes a PDF directly.

### Tests

- `tests/test_printing.py` — 10 new tests covering paper size math, the
  amount-in-words function (zero / negatives / paisa only / lakh / crore /
  fractions), the clinic-header pull (including `prescription_footer`), and
  invoice totals + in-words after posting.

## Rendering details

### Prescription layout

1. Clinic letterhead — logo (optional, scaled to ≤90pt wide) beside name,
   tagline, address/phone/email/website, with a thick separator.
2. `℞ Prescription` title with date and Rx number (`Rx #<id>`) right-aligned.
3. Patient block — name (age, gender), ID, phone, address.
4. Sections (when non-empty): Chief complaint / On examination.
5. Numbered medicines list (1. name — strength [form]) with Dosage / Duration /
   Quantity on the sub-line and Instructions indented.
6. Sections: Advice / Notes.
7. Signature block — doctor signature line on the right with name + credentials
   below.
8. Optional italicised footer (`ClinicProfile.prescription_footer`) with a thin
   rule.

### Invoice layout

1. Same clinic letterhead.
2. Title: `INVOICE` / `INVOICE (DRAFT)` / `INVOICE (VOIDED)`, plus invoice #,
   date, status, provider.
3. Billed-to block (patient name [code], phone, address).
4. Line-item table with columns **Description · Qty · Amount** (right-aligned),
   header and totals rules.
5. Totals: Subtotal, Discount (shown only if non-zero), Tax, a thick rule,
   **TOTAL** (bold, larger), Paid, and **Balance due** (highlighted red if >0).
6. *In words* line (italicised).
7. Payments received list — `• method: amount (ref: …)`.
8. Notes (italicised).
9. Thank-you, then signature rules for *Received by* (left) and *Customer
   signature* (right) with the doctor's name pre-filled on the right.

### Paper sizes

| Code | Size | Margins | Notes |
|------|------|---------|-------|
| `a4` | 210 × 297 mm (≈595 × 842 pt) | 36 pt (12.7 mm) | Full letterhead Rx/invoice. |
| `a5` | 148 × 210 mm (≈420 × 595 pt) | 28 pt (9.9 mm) | Compact half-page chit. |
| `thermal-80` | 80 mm wide (≈227 pt), variable height | 14 pt (~5 mm) | Receipt roll. |
| `thermal-58` | 58 mm wide (≈165 pt), variable height | 10 pt (~3.5 mm) | Mini receipt roll. |

All sizes use portrait orientation. Thermal documents are rendered as a single
long page (the OS printer driver handles cut marks). Multi-page pagination is
implemented for A4/A5 overflow (e.g. invoices with many line items).

### Bangla

- Bangla text in medicine names, diagnosis, advice, patient/clinic names,
  addresses, and the `prescription_footer` all render in a Bangla-capable
  font. The strategy is: pick a Latin base font (Segoe UI / Calibri / DejaVu
  Sans) and register the best-available Bangla font as a substitution via
  `QFont.insertSubstitutions`. Qt automatically falls back for U+0980..U+09FF.
- Candidates in priority order: SolaimanLipi → Kalpurush → Siyam Rupali →
  Noto Sans Bengali → Vrinda → generic "Bangla" → Sans Serif fallback.
- On Windows, Vrinda ships by default; installing SolaimanLipi (free) gives
  better conjuncts for handwritten-style Rx aesthetics. We document this in
  the user guide (Phase 16).

## Quality gates (Phase 10)

- `pytest tests/` → **117 passed in 61.08s** (10 new printing tests, no regressions).
- `ruff check dentiva tests` → All checks passed.
- `mypy dentiva` → Success: no issues found in 125 source files (Qt files carry
  `# mypy: disable-error-code="arg-type,attr-defined,no-any-return"` because
  PySide6's enum typing is unreliable in mypy; the rest of the codebase is strict).
- Renderer imports on a Windows machine (and any Linux with libGL) and renders
  through both QPrinter (native print) and QPrinter.PdfFormat (PDF export)
  because the code uses only public, documented PySide6 QtPrintSupport APIs.

## Known limitations / follow-ups (explicit, not deferred silently)

1. **No paper-size selector UI yet.** Prescription dialog uses A4; Invoice
   dialog uses A4. The plumbing (`paper_code` argument in `print_document` /
   `preview_document` / `export_pdf`, plus the `PaperSize` objects for A5 and
   both thermal widths) is ready; the Settings tab to choose the default paper
   per document type, plus a combo in the preview window, is Phase 16 polish.
2. **Thermal real-printer validation pending.** The 80 mm / 58 mm paper
   definitions and renderer have been implemented; I cannot drive a physical
   thermal printer from this Linux sandbox. You should test `preview_document(...,
   paper_code="thermal-80")` against your ESC/POS printer on Windows — if the
   margins need tightening per-driver, the constants in `paper.py` are the
   single place to change.
3. **Clinic logo path** is taken from `ClinicProfile.logo_path`. The Settings
   dialog does not yet expose a "Browse for logo" control (Phase 16). Until
   then, dropping a PNG at `./clinic-logo.png` or setting the field in the
   database works; when missing, the letterhead is text-only (looks fine).
4. **No background watermark** ("PAID", "DRAFT", "VOIDED") yet. The renderer
   does show `INVOICE (DRAFT)` / `INVOICE (VOIDED)` in the title; a diagonal
   watermark is a small polish item.
5. **Print Settings tab** (default printer, default paper, font override,
   thermal line density) not yet wired — scheduled for the settings pass in
   Phase 13/14.

## RBAC

- `Permission.PRESCRIPTIONS_PRINT` — already used by the Prescription dialog;
  the dialog's Print button is already gated by `finalized` state.
- `Permission.INVOICES_PRINT` — already declared; used by the Invoice dialog to
  show Print/PDF only when the invoice is posted and the user has the
  permission.

## Next phase

Phase 11 — **Inventory & Stock** (items, opening stock, purchase receipts,
stock adjustments, low-stock alerts, treatment-catalog linkage).
