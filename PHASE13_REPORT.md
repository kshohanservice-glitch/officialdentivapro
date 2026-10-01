# Phase 13 Report — Staff, Users, Roles & Audit Log

**Branch:** `arena/01a0f68e-officialdentivapro`
**Phase:** 13 / 16 (Staff, Users, Roles & Audit log)

## Summary

Staff & Users management is fully fleshed out: role editor with a grouped
permission matrix (system roles are protected from edits), enhanced user CRUD
with edit dialog (username/display/role/password/active flag), activate/
deactivate (with self-deactivate guard), password reset, and a **Providers
(Dentists)** tab for managing clinical providers and their designations. A
brand-new **Audit log** page lets admins browse, filter (date range / action /
entity / user), and search the entire audit trail.

## Files added / changed

### Service: `dentiva/services/user_service.py` (extended)
New DTOs: `UserRow`, `RoleRow` (include permissions list, `is_system`,
description). New/improved functions:
- `list_users` now returns `UserRow` dataclasses (username, display, role, active,
  last login, must-change-pw, superuser).
- `list_roles` returns `RoleRow` with current permissions list and system flag.
- `create_role(name, description, permissions)` — creates a role and assigns
  the supplied permissions (validates each permission exists).
- `update_role(role_id, …)` — updates name/description and replaces permissions
  via `_replace_permissions` (delete + insert); system roles blocked from edit.
- `update_user(user_id, display_name, username)` — rename/display with 3-char
  minimum, duplicate-username guard.
- `activate_user(user_id)` — reactivates a user and clears failed-login locks.
- `deactivate_user(user_id)` — unchanged, self-deactivate still blocked.
- `reset_password` — unchanged.
- `available_permissions()` returns `(value, group, label)` tuples, grouped by
  functional area (Patients / Clinical / Appointments & Queue / Financial /
  Inventory / Staff & Users / System) for the UI permission matrix.
- Helper `_validate_permissions` and `_replace_permissions` (uses SQLAlchemy
  `delete()` for 2.0 compatibility).

### Service: `dentiva/services/audit_service.py` (extended)
- `list_events` now supports `start`, `end`, and `search` filters in addition
  to existing `action`, `entity_type`, `user_id`.
- New `list_actions(session, principal)` and `list_entity_types(session,
  principal)` helpers for the filter dropdowns.

### UI: `dentiva/ui/views/staff/staff_view.py` (rewritten)
Replaces the prior users-only page with three tabs:
1. **Users** — enhanced table with Status, Must-change-pw, Last login columns;
   New / Edit / Reset password / Activate·Deactivate buttons (gated by
   `USERS_CREATE`, `USERS_EDIT`, `USERS_RESET_PASSWORD`); double-click to edit.
   Edit dialog covers username, display name, role, password (blank = leave
   unchanged), and active toggle with proper guards (self-deactivate blocked
   at service layer).
2. **Roles** — lists roles (System / Custom badge), + New role and View/Edit
   buttons; role dialog shows a **grouped permission matrix** of checkboxes
   (Patients, Clinical, Appointments, Queue, Financial, Inventory, Staff &
   Users, System). System roles show all checkboxes disabled and a warning
   ("Clone it to customize"). Save button is disabled for system roles.
3. **Providers (Dentists)** — lists dentists with designations / phone / email;
   dialog to create/edit providers with name, phone, email, comma-separated
   designations (creates new `Designation` rows automatically via the existing
   `dentist_service`).

### UI: `dentiva/ui/views/audit/audit_view.py` (new)
Registered as a new **Audit log** nav item (under Administration). Features:
- Date range filter (default last 30 days).
- Action, Entity, User filter dropdowns (populated from actual data).
- Free-text search over the summary text.
- Table showing When / User (display name, or "system") / Action / Entity
  (#id) / Summary. Sorted newest-first, capped at 500 rows.
- RBAC-gated by `AUDIT_LOG_VIEW`.

### Nav & main window wiring
- `dentiva/ui/navigation.py` — added `"audit"` route.
- `dentiva/ui/widgets/nav.py` — added `Audit log` entry under Administration.
- `dentiva/ui/main_window.py` — routes loop includes `audit`, and the live
  `StaffUsersView` (replacing the placeholder) and `AuditView` are
  instantiated after login.
- `dentiva/db/seed.py` — unchanged (default roles/designations/payment methods
  already seeded; Role.is_system flag already existed).

### Tests: `tests/services/test_users_roles.py` — 7 new tests
1. Default roles are listed and include permission lists.
2. Role create with permission matrix, invalid-permission rejection, duplicate
   name rejection (case-insensitive).
3. User update (display + username rename) + role change.
4. Deactivate followed by reactivate toggles `is_active`.
5. Self-deactivate is blocked.
6. Audit event filtering by date range + action + search.
7. Permission denial for anonymous principal (list_users / create_role).

## Quality gates (Phase 13)
- `pytest tests/` → **138 passed in 77s** (7 new, zero regressions).
- `ruff check dentiva tests` → clean.
- `mypy dentiva` → 13 pre-existing `union-attr` errors in older UI files
  (down from 14 before this phase); zero new errors introduced. The new files
  carry the standard `# mypy: disable-error-code="…"` header consistent with
  prior PySide6 views.

## RBAC
| Action | Permission |
|---|---|
| View users list | `USERS_VIEW` |
| Create user | `USERS_CREATE` |
| Edit user (name, role, activate/deactivate) | `USERS_EDIT` |
| Reset password | `USERS_RESET_PASSWORD` |
| View roles / users read | `USERS_VIEW` or `ROLES_MANAGE` |
| Create / edit roles | `ROLES_MANAGE` |
| Manage dentists | `DENTISTS_MANAGE` |
| View audit log | `AUDIT_LOG_VIEW` |

## Integrity notes
- **System roles cannot be edited**: Doctor, Dentist, Assistant, Receptionist,
  Accountant, Administrator carry `is_system=True`; the role dialog disables
  all checkboxes and the Save button for them. Users who want customization
  clone them via "New role".
- **Password reset** forces `must_change_password = True` on next login (already
  wired in the auth flow from earlier phases), clears failed attempts and
  unlocks locked accounts.
- **Activation** also clears `failed_login_attempts` and `locked_until` so a
  reactivated user can sign in immediately.
- **Audit log is append-only**: the UI does not expose any edit or delete
  functionality, and `AuditEvent` has no service-layer mutators beyond
  `audit_service.record()`.

## Known follow-ups
1. Clone-role button in the role editor (currently you'd create a new role and
   tick the same boxes; a one-click clone is polish).
2. Staff employee records (HR info like salary/joining date/NID) are still a
   stub; this phase covers users/roles/providers — a future HR phase could add
   those without breaking current screens.
3. Audit-log CSV/export (the list is printable via standard print-to-PDF from
   the table today).
4. Session/kick-active-user on role change: when you deactivate a user or
   change their role, existing sessions continue to work until the next login
   or auto-lock (this is acceptable for a clinic app where staff are trusted;
   immediate revocation is a future polish).

## Next phase
Phase 14 — **Notifications & Reminders** (appointment reminders, follow-up
recalls, low-stock alerts, in-app notification center, optional SMS/email
hooks stubbed but defaulting to off for offline-first guarantee).
