# Phase 4 Report — Dashboard, Global Search & Notifications

**Status:** Phase 4 complete. 49/49 tests pass. `ruff` and `mypy` clean. Ready for review/merge before Phase 5.

## What shipped

### Live dashboard (`dentiva/services/dashboard_service.py` → `load_dashboard`)
Six operational stat tiles, all RBAC-aware (tiles for entities the principal cannot view are hidden rather than showing misleading zeros):
- **Today's appointments** — non-cancelled appointments between 00:00 and 23:59 Asia/Dhaka
- **Checked in** — appointments currently in `checked_in` / `in_progress`
- **Waiting in queue** — `QueueEntry` rows with status `waiting` / `with_dentist` and no `finished_at`
- **Today's revenue** — sum of non-reversed payments recorded today (integer paisa, formatted as ৳X,XXX.XX)
- **Pending invoices** — count + outstanding balance for posted, unpaid/partial, non-voided invoices
- **Low-stock alerts** — inventory items where `current_qty ≤ min_level_qty` (reorder threshold)

Below the tiles:
- **Upcoming appointments card** — next 12 appointments from 30 min ago through end-of-day, with patient name, time, dentist, reason, status-coloured foreground
- **Alerts card** — unread notifications, pending-invoice summary, low-stock summary

The dashboard auto-refreshes every 60 seconds and again every time the view becomes visible (so navigating back after creating an invoice shows updated revenue immediately).

### Global search (`Ctrl+K` / `Ctrl+F`)
- `global_search(session, principal, query)` service searches across **patients** (name, phone, patient code), **appointments** (patient name, reason; last 7 days + future), and **invoices** (number, patient name).
- Results are grouped by kind, capped at 20 (configurable), and automatically filtered to entities the principal can view (patients.view is required for patient hits, appointments.view for appointment hits, invoices.view for invoice hits).
- Floating popup (`GlobalSearchPopup`) with:
  - 150 ms debounce so typing fast doesn't thrash the DB
  - Bold section headers (Patients / Appointments / Invoices)
  - Keyboard nav: ↑/↓ to move, Enter to select, Esc to dismiss
  - Selecting a result emits `result_selected(route, entity_id)` → main window navigates to the target view and refreshes it
- Shortcuts `Ctrl+K` and `Ctrl+F` both open the popover (application-scope so they work from any view).

### Notifications center
- `add_notification(session, user_id, kind, title, message)` creates a row; user_id=None means global (visible to all users).
- `notification_summary(session, principal)` returns unread count + latest 10 items.
- `mark_notifications_read(session, principal)` marks all of the user's (plus global) notifications as read and timestamps `read_at`.
- Bell button in the header shows an unread badge (`🔔3`) and opens a dropdown listing notifications with relative-time stamps (just now / Nm / Nh ago / dd Mon YYYY). Unread items are bold, read items are gray.
- Mark-all-read button at the top of the dropdown.
- Badge auto-refreshes every 30 seconds and after every mark-as-read.

### Date helpers (`dentiva/core/dates.py`)
Added three naive-local helpers needed for accurate "today" queries against the schema's naive Asia/Dhaka datetime columns:
- `local_now()` → naive datetime in Asia/Dhaka
- `start_of_day(d)` → 00:00:00 local
- `end_of_day(d)` → 23:59:59.999999 local

### Main window / navigation wiring
- `MainWindow` now takes `session_factory` + `principal` in its constructor (was previously constructed with just display strings), so authenticated views can be late-bound after login.
- `navigate_to(route)` now closes transient popovers (search/notifications) and calls `.refresh()` on the destination view if it exposes one, so the dashboard, patients list, etc. refresh when you navigate to them.
- Dashboard placeholder from Phase 2 is replaced with the live `DashboardView` in the same late-binding pattern used for Staff & Users in Phase 3.
- Search popup floats over the central widget; notifications popup anchors to the bottom-right of the bell button.
- Notification popup positioning is re-anchored on each open so it stays next to the bell regardless of window resize.

### Styling (`assets/themes/default.qss`)
Added `#DpSearchPopup`, `#DpNotifPopup`, `#DpSearchInput`, `#DpSearchResults`, `#DpNotifList`, `#DpUpcomingList`, `#DpAlertsList`, and `#DpPopupTitle` selectors so the new widgets match the existing design tokens.

### Tests (49 total)
Added `tests/services/test_dashboard.py` (7 tests):
1. `test_dashboard_loads_empty_state` — clinic name, zero tiles right after setup
2. `test_dashboard_counts_today_appointments_and_payments` — creates a patient + appt + posted invoice + payment + queue entry + low-stock item and asserts every tile reflects them
3. `test_dashboard_rbac_hides_tiles_for_receptionist` — creates a receptionist user and verifies the permission set matches seed expectations
4. `test_global_search_finds_patient_and_invoice` — creates a patient + invoice and confirms both appear in search results with correct kinds/titles
5. `test_global_search_min_length` — empty/whitespace returns [ ]
6. `test_notifications_roundtrip` — add → unread count → mark all read → count = 0
7. `test_notifications_include_global` — user_id=None notifications are delivered to all users

Added two unit tests for `local_now` / `start_of_day` / `end_of_day`.

### Quality gates
```
$ ruff check dentiva tests
All checks passed!

$ mypy dentiva
Success: no issues found in 97 source files

$ pytest tests/
============================== 49 passed in 14.37s ==============================
```

## RBAC behavior summary
| Tile / feature | Required permission |
|---|---|
| Today's appointments / Checked in | `appointments.view` |
| Waiting in queue | `queue.manage` |
| Today's revenue | any of `payments.view`, `invoices.view`, `accounting.view`, `reports.financial.view` |
| Pending invoices | `invoices.view` |
| Low stock | `inventory.view` |
| Upcoming appointments | `appointments.view` + `patients.view` |
| Search → patients | `patients.view` |
| Search → appointments | `appointments.view` + `patients.view` |
| Search → invoices | `invoices.view` + `patients.view` |
| Notifications | always visible (populated per-user) |

## Notable design decisions
1. **Naive local datetimes.** The schema stores naive timestamps in Asia/Dhaka (consistent with how bootstrap and QueueEntry default to `datetime.now(tz=TZ).replace(tzinfo=None)`). The new `local_now/start_of_day/end_of_day` helpers use the same convention so "today" queries are accurate and timezone-safe without forcing a migration on the existing schema.
2. **Graceful degradation, not hard errors.** `load_dashboard` and `global_search` return empty/zero values for sections the principal cannot see rather than raising. The dashboard is a composite surface used by every role; raising would lock out users who only have partial permissions. The UI layer double-checks permissions to hide empty tiles.
3. **Debounced search** (150 ms) keeps the UI responsive while avoiding N+1 queries per keystroke.
4. **Notifications auto-mark-read on open**, which is the expected UX for a bell dropdown. A "Mark all read" button is still provided.
5. **Idempotent seed data** continues to be assumed; dashboard queries never create reference data.

## Known intentional deferrals
- Opening a search result and selecting the exact record in the target list (e.g., opening the Patients view filtered to that patient) — target views (Patients, Appointments, Invoices) are still placeholders; deep-linking will be added when each destination view is implemented (Phases 5–8). The search popup already navigates to the correct route and passes `entity_id`; the signal is wired for future views to consume.
- Push/sound notifications — deferred; in-app list covers v1.
- Click-through on alerts (e.g., clicking a low-stock alert takes you to Inventory) — will be wired once Inventory view is live (Phase 9).
- The global search currently covers patients/appointments/invoices. Payments, prescriptions, staff, and treatments will be added as their respective views are built.

## Files changed
- Added: `dentiva/services/dashboard_service.py`, `dentiva/ui/widgets/search_popup.py`, `dentiva/ui/widgets/notifications_popup.py`, `tests/services/test_dashboard.py`
- Modified: `dentiva/core/dates.py`, `dentiva/app.py`, `dentiva/ui/main_window.py`, `dentiva/ui/navigation.py`, `dentiva/ui/views/dashboard/dashboard_view.py`, `assets/themes/default.qss`, `tests/unit/test_dates.py`

## Next (Phase 5) — Patients module
Pending your explicit "Continue". Planned: patient list (searchable by name/phone/code), new/Edit patient dialog (validation for BD phone, age cache on save), soft-delete with typed confirmation, medical history/allergies fields, last-visit tracking, visit-count maintenance, and audit events for create/update/delete.
