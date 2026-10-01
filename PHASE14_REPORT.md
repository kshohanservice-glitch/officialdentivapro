# Phase 14 Report — Notifications, Reminders & Settings UI

## Goal
Add automatic in-app notification generation, a dedicated Notifications page, and
a unified Settings page covering clinic profile, notification preferences, and
print defaults.

## What shipped (Phase 14)

### `dentiva/services/notification_service.py` (new)
Idempotent notification-generation engine and CRUD helpers.

* **Settings layer** (stored in `AppSetting`, typed + validated):
  - `notif.appt_reminder.enabled` (bool)
  - `notif.appt_reminder.lead_minutes` (int, 5–1440, default 30)
  - `notif.today_summary.enabled` (bool)
  - `notif.low_stock.enabled` (bool)
  - `notif.overdue_invoice.enabled` (bool)
  - `notif.overdue_invoice.days` (int, 1–365, default 7)
  - `print.prescription.paper` / `print.invoice.paper` (str: a4/a5/thermal-80/thermal-58)
* **Episode-state deduplication**: per-kind processed-id lists persisted in
  `AppSetting["notif.episode_state"]` (capped at 200/kind) so restarts do not
  re-emit duplicates.
* **Four idempotent generators**, all producing broadcast notifications
  (`user_id=None`) so every logged-in user sees them:
  1. `appt_upcoming` — scheduled appointments within the configured lead window.
  2. `day_summary` — count of today's scheduled appointments, emitted once per day.
  3. `low_stock` — `InventoryItem`s where `current_qty < min_level_qty`.
  4. `overdue_invoice` — posted invoices (`is_posted=True`) with
     `due_paisa > 0` and `posted_at` older than the threshold.
* **UI helpers**: `list_notifications`, `unread_count`, `mark_read`,
  `mark_all_read`, `delete_all_read` (housekeeping: prunes read notifications
  older than a configurable threshold, default 1 day).
* **Permission gate**: `list_settings` requires `Permission.NOTIFICATIONS_MANAGE`
  via `Policy.require`; all other read/write helpers work for any active user
  (notifications are a broadcast in-box).

### Background generation
`MainWindow` now runs `generate_notifications` + `delete_all_read` on a 60-second
timer (with a 1.5-second single-shot after login) and refreshes the header bell
badge afterwards. On exception it logs and continues so a notification bug can
never crash the shell.

### Header bell popup (`dentiva/ui/widgets/notifications_popup.py`)
Refactored to use `notification_service.list_notifications`,
`notification_service.unread_count`, and `notification_service.mark_all_read`
instead of the deprecated `dashboard_service` shims, so the popup and the
dedicated Notifications page use one code path.

### Notifications page (`dentiva/ui/views/notifications/notifications_view.py`, new)
Full in-box view with:

* Filter dropdown: All / Unread only / each kind.
* Table showing When, Type, Title, Message, Status (unread rows bold).
* Mark-all-read and Refresh buttons.
* Uses `UnitOfWork` for all DB access.

### Settings page (`dentiva/ui/views/settings/settings_view.py`, new)
`QTabWidget` with three tabs:

1. **Clinic** — name, phone, email, address, tagline, prescription footer,
   logo browse/clear; saves through `clinic_service.setup_clinic` (preserving
   the existing logo path to avoid re-validating previously-saved files).
   Gated by `Permission.CLINIC_PROFILE_MANAGE`.
2. **Notifications** — toggles + spinboxes for all five notification settings;
   gated by `Permission.NOTIFICATIONS_MANAGE` (or superuser).
3. **Printing** — default paper for prescriptions and invoices;
   gated by `Permission.PRINTERS_MANAGE` (or superuser).

### Navigation
* `dentiva/ui/widgets/nav.py`: added **Notifications** nav item (visible to all
  logged-in users, bell glyph "✉").
* `dentiva/ui/navigation.py`: already had the `notifications` placeholder route;
  real `NotificationsView` and `SettingsView` are wired via `MainWindow.replace_view`.
* `MainWindow.replace_view` now installs real views for `notifications` and
  `settings` after login.

## Tests
`tests/services/test_notification_service.py` (new) — 9 tests covering:

* Default values and integer-out-of-range rejection.
* Upcoming-appointment emission + inter-tick dedup.
* Day-summary emission once per calendar day.
* Low-stock emission when enabled, suppression when disabled, and dedup.
* Overdue-invoice detection on a posted unpaid invoice past threshold.
* Mark-all-read and housekeeping delete of aged read notifications.
* Kind and status filters on listing.

## Quality gates
| Tool | Result |
|------|--------|
| `pytest tests/` (with `-p no:pytest-qt` — no libGL in sandbox) | **147 passed** (9 new + 138 prior) |
| `ruff check dentiva/` | All checks passed |
| `mypy dentiva/services/notification_service.py` | Success: no issues found |
| `py_compile` of all new/edited files | OK |

## Files changed / added
* Added: `dentiva/services/notification_service.py`
* Added: `dentiva/ui/views/notifications/__init__.py`, `notifications_view.py`
* Added: `dentiva/ui/views/settings/settings_view.py`
* Added: `tests/services/test_notification_service.py`
* Modified: `dentiva/ui/main_window.py` (timer wiring, view registration)
* Modified: `dentiva/ui/navigation.py` (route entry)
* Modified: `dentiva/ui/widgets/nav.py` (nav items)
* Modified: `dentiva/ui/widgets/notifications_popup.py` (shared service use)

## Notes
- The legacy `dashboard_service.notification_summary` / `mark_notifications_read`
  / `add_notification` helpers remain defined (no code references them anymore)
  and can be removed in a follow-up cleanup if desired; they were left in place
  to avoid breaking any external callers that might exist.
- Backups remain as the Phase 15 placeholder route; that phase will flesh out
  the `backup` view, scheduling, and pre-restore safety backups.
