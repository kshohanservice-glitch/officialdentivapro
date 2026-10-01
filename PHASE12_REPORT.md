# Phase 12 Report — Accounting & Financial Reports

**Branch:** `arena/01a0f68e-officialdentivapro`
**Phase:** 12 / 16 (Accounting & financial reports)

## Summary

A full accounting ledger and dashboard is now live. Payments automatically
post to income (with refunds/contra entries on reversal), manual
income/expense entries can be recorded against configurable categories, and
the Accounting dashboard shows period totals (income, expenses, net profit,
billed, collected), break-down by category and payment method, and a daily
trend. Default chart-of-accounts categories are seeded on first run.

## Files added / changed

### New service: `dentiva/services/accounting_service.py`
- **Default chart of accounts** — seeded idempotently:
  - Income (10): Consultation fees, Restorative, Endodontics (RCT), Prosthodontics,
    Orthodontics, Oral surgery/extractions, Scaling & prophylaxis, Whitening/cosmetic,
    Imaging/X-ray, Other clinical income.
  - Expense (9): Rent, Utilities, Staff salaries, Dental supplies & consumables,
    Lab fees, Equipment purchase/maintenance, Marketing, Taxes & compliance, Misc.
- **Categories CRUD**: `list_categories`, `create_category` (with parent support,
  kind-matching parent validation, duplicate-name prevention). Called via
  `ensure_default_categories()` (idempotent).
- **Entries**: `list_entries` (filterable by date range / kind / category),
  `create_entry` (manual income/expense). Entries include `source` discriminated
  automatically as `manual` / `payment` / `payment_reversal` based on
  `related_payment_id` and sign.
- **Auto-posting hooks**: `record_payment_income()` and `record_payment_reversal()`
  write income / contra-income entries linked to the payment + invoice.
- **Period reports**: `period_totals(start, end)` returns a `PeriodTotals`
  dataclass with income/expense/net profit, billed (posted invoices in period),
  collected (sum of signed income entries = payments − reversals), break-downs
  by category (income + expense), break-down of income by payment method, and a
  daily net trend.

### Hooked into payment service
`dentiva/services/payment_service.py` now, on every successful payment create:
- calls `accounting_service.ensure_default_categories(session)` (idempotent)
- calls `record_payment_income(...)` to post the income line, with date from the
  payment's `paid_at`, linked to payment method, invoice and payment.

On payment reverse, it calls `record_payment_reversal(...)` to post a negative
income entry on the same category as the original payment, so refunds show as
negative income and never disappear from the ledger (immutable audit trail).

### Seed integration
`dentiva/db/seed.py` → `seed_defaults()` now calls
`accounting_service.ensure_default_categories(session)` so new clinics get the
default chart of accounts at setup.

### New UI: `dentiva/ui/views/accounting/accounting_view.py`
Registered in `main_window.py` replacing the accounting placeholder. Three tabs:

1. **Dashboard** — period quick-select (Today / Last 7 days / This month /
   Last month / This year / All time) plus custom From/To date pickers. KPI
   tiles for Income, Expenses, Net profit (red when negative), Billed
   (invoices posted in period), Collected (payments − reversals). Three side-
   by-side tables: income by category, expenses by category, collected by
   payment method, plus a Daily trend table. "+ New entry" button for users
   with `ACCOUNTING_MANAGE`.
2. **Ledger entries** — date range + type filter, shows every entry with date,
   type (Income / Expense / Refund, colour-coded green/red), category, amount
   (right-aligned), method, description/reference, and source (Manual / Payment
   / Refund).
3. **Categories** — lists all income & expense categories with parent, and a
   "+ New category" dialog to add custom categories (type + parent picker).

Entry dialog: date, type (Expense/Income), category (refreshed per type), amount
in ৳, payment method, reference, description. Validates that categories match
the chosen kind.

### Tests: `tests/services/test_accounting.py` — 5 new tests
1. Default categories seeded and idempotent (no duplicates on second call).
2. Manual expense entry lands in the ledger.
3. Invalid entries rejected (zero amount, non-existent category).
4. Payment records an auto income entry; reversal records a contra
   (signed_paisa = −amount) entry; `source` discriminator works.
5. Period totals compute income/expense/net and include break-down by category
   and daily net entries.

## Quality gates (Phase 12)
- `pytest tests/` → **131 passed in 72s** (5 new, zero regressions).
- `ruff check dentiva tests` → clean.
- `mypy dentiva` → same 14 pre-existing `union-attr` errors in other UI files;
  zero new errors (accounting files carry a `# mypy: disable-error-code` header
  for PySide6's enum / QPainter typing quirks consistent with prior phases).

## RBAC
| Action | Permission |
|--------|------------|
| View dashboard/ledger/categories | `ACCOUNTING_VIEW` |
| Add manual entries / categories | `ACCOUNTING_MANAGE` |
| Auto-posted payment entries | run as the acting principal (any user with `PAYMENTS_CREATE`/`PAYMENTS_REFUND`) |

## Accounting integrity notes
- **Ledger is append-only**: payments never hard-delete entries; reversals add
  a negative income row. This means reports are reproducible and auditable.
- **Payment income posts to "Other clinical income" by default**. A future
  polish step can map treatment categories → income categories at invoice
  posting time (so Restorative treatments roll up to the "Restorative" income
  category, etc.). For now all clinical income aggregates under "Other clinical
  income" which is correct but not sub-analysed.
- **Manual entries respect the category kind**: you can't post an expense
  against an income category (service raises `ValidationError`).
- **Stock value is not yet an expense**: when we wire inventory purchases
  through PO/receipts in a future phase, those will auto-post expense entries
  to the "Dental supplies & consumables" category. Right now purchases recorded
  through Inventory Movement don't hit the P&L — that is correct until a
  supplier invoice is entered, which is how cash-accounting works.

## Known follow-ups (tracked, not silently deferred)
1. **Treatment → income-category mapping** so clinical income breaks down by
   service line (Restorative, Endo, etc.) instead of all landing in "Other
   clinical income".
2. **Receivables aging** (30/60/90 day buckets) — not yet surfaced; data exists.
3. **Inventory purchase auto-expense posting** when purchase receipts are
   formalised.
4. **Bank/cash reconciliation** — cash vs bank payment methods split is
   visible in "by payment method"; explicit reconciliation widget deferred.
5. **CSV/Excel export** of ledger and period reports.
6. **Expense attachments** (scan/photo of receipts) using the existing
   attachment subsystem.
7. **Void/category-deactivate rules** — categories can be marked inactive but
   existing entries keep the name reference; UI for deactivate added later.

## Next phase
Phase 13 — **Staff & Users management polish** (role editor, permission matrix,
deactivation, password reset, audit-log integration).
