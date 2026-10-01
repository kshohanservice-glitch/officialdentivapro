# Phase 3 Report — Setup Wizard, Authentication, RBAC & Staff/User Management

**Status:** Phase 3 complete. All 40 tests pass. Lint (ruff) and type-checks (mypy) are clean. Ready for review/merge before Phase 4.

## What shipped

### Core services (under `dentiva/services/`)
| File | Purpose |
|---|---|
| `setup_service.py` | First-run wizard transaction: creates clinic profile, dentist(s), admin user, RBAC assignments. Validates inputs **before** any writes so partial failures roll back cleanly. |
| `auth_service.py` | bcrypt password hashing/verification, username lookup, login attempt tracking with lockout (5 failures → 5 min lockout by default; config-driven). |
| `user_service.py` | User CRUD (`create_user`, `list_users`, `set_user_role`, `reset_password`, `deactivate_user`) — all gated by `Permission`-based RBAC at the service layer (never just UI). |
| `clinic_service.py` | Read clinic profile, save logo to disk. |
| `dentist_service.py` | Dentist CRUD, photo/signature file storage, designations. |
| `audit_service.py` | Audit log writer stub (used by Phase 4+); `write_event` persists `AuditLog` rows. |

### Seed data (`dentiva/db/seed.py`)
- **52 teeth:** full adult (11–48) and pediatric (51–85) FDI notation, with ADA (universal) equivalents, ordered for chart drawing (upper-right → upper-left, then lower-right → lower-left).
- **6 roles:** Administrator, Dentist, Receptionist, Accountant, Inventory Manager, Read-Only — each seeded with explicit permission sets.
- **8 payment methods:** Cash, bKash, Nagad, Rocket, Upay, Card, Bank, Other.
- **Clinical catalog defaults:** treatment categories, common procedures, visit types, tooth conditions, prescription frequencies/durations — all populated idempotently.

### Dialogs (`dentiva/ui/dialogs/`)
- **SetupWizard** – three pages (Clinic → Lead Dentist → Admin Account), validation inline, only commits a single UoW on Finish so failure leaves DB untouched.
- **LoginDialog** – username/password form with configurable attempt cap and lockout, exposes logged-in `Principal` after success.
- **LockDialog** – password-only re-entry used by both manual lock (File → Lock) and auto-lock; cancelling logs out.
- **ActivationDialog** – already in Phase 2; wired through app lifecycle.

### Staff & Users view (`dentiva/ui/views/staff/staff_view.py`)
- Users tab: table of users (username, display name, role, status, last login), create-user dialog (role dropdown), reset password, deactivate/reactivate, role assignment. Buttons are enabled/disabled by the current principal's permissions — and the underlying service calls double-check permissions, so a restricted principal cannot bypass via the Python API.
- "Staff" tab is an intentional PlaceholderView (full employee records with payroll/attendance land in Phase 11 per the scope phasing).

### Application controller (`dentiva/app.py`)
Boot sequence now complete:
1. `bootstrap()` → engine, migrations, seed, activation + setup flags.
2. Seed defaults applied.
3. Activation dialog (skipped if already activated).
4. First-run setup wizard (skipped if `is_setup_complete`).
5. Login dialog with last-user prefill.
6. Main window created and shown; real `StaffUsersView` replaces the placeholder because staff/users are the production-ready view in Phase 3.
7. Global QEvent activity filter (`_ActivityFilter`) installed via `MainWindow.on_user_activity_callbacks(...)` so every mouse/key event resets the idle timer.
8. Auto-lock timer runs every 15 s and pops the lock dialog when `Session.should_lock()` returns true (configurable 5/10/15/30 minutes).
9. Unlock validates password; failure keeps dialog open; cancel/logout returns to login.
10. Module-level `run(argv)` entry point supports both `python -m dentiva` and the `dentiva-pro` console script.

### Auth session (`dentiva/auth/session.py`)
- `login(principal, lock_minutes)` captures principal + expiry.
- `touch()` resets the idle deadline on any user activity.
- `should_lock()` returns True once the deadline passes.
- `logout()` clears the principal.

### Unit of Work (`dentiva/core/unit_of_work.py`)
- Switched default to `autocommit=False` so service calls control transaction boundaries explicitly (`uow.commit()` on success, automatic rollback via context manager on exception).

### Tests (40 passing)
- **Unit:** `test_dates`, `test_money`, `test_password`, `test_permissions`, `test_validators`.
- **Integration:** `test_db_init` (schema, FK, WAL, seed counts), `test_migrations` (real `alembic upgrade head` in an isolated data dir), `test_activation` (code normalization, machine-binding).
- **Services (`tests/services/test_auth_and_setup.py`):** setup atomicity, clinic-name validation, dentist-required validation, admin-username/password-length validation, auth success, auth failure, lockout after 5 attempts, RBAC denial (receptionist cannot list users), create_user + reset_password round trip, password length enforcement, is_setup_complete flag.

Fixtures (`tests/conftest.py`) provide:
- `tmp_data_dir` — rewires `DENTIVA_DATA_DIR`, reloads `dentiva.paths`, monkeypatches every module that cached the paths singleton (`verifier`, `alembic_support`, `db.engine`, `bootstrap`), resets config cache.
- `session_factory` — engine + migrations + seed + sessionmaker per test.
- `session` — rollback-isolated so tests never leak data.
- `admin_principal` — idempotent admin principal (runs setup if not yet complete).

### Quality gates
```
$ ruff check dentiva tests
All checks passed!

$ mypy dentiva
Success: no issues found in 94 source files

$ pytest tests/
============================== 40 passed in 9.28s ==============================
```

## RBAC matrix (seeded)
| Permission | Administrator | Dentist | Receptionist | Accountant | Inventory Mgr | Read-Only |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| MANAGE_USERS / ROLES | ✅ | — | — | — | — | — |
| VIEW_PATIENTS / MANAGE_PATIENTS | ✅ | ✅ | ✅ | — | — | ✅ |
| MANAGE_APPOINTMENTS / CHECK_IN | ✅ | ✅ | ✅ | — | — | — |
| CHART_VIEW / CHART_EDIT | ✅ | ✅ | — | — | — | ✅(view) |
| PRESCRIPTIONS_CREATE / VIEW | ✅ | ✅ | ✅(view) | — | — | ✅(view) |
| INVOICES_CREATE / EDIT / VOID / VIEW | ✅ | ✅ | ✅(create/view) | ✅ | — | ✅(view) |
| PAYMENTS_RECORD / VIEW / REFUND | ✅ | — | ✅(record/view) | ✅ | — | ✅(view) |
| INVENTORY_VIEW / MANAGE / ADJUST | ✅ | — | — | ✅(view) | ✅ | ✅(view) |
| ACCOUNTING_REPORTS / DAY_CLOSE | ✅ | — | — | ✅ | — | — |
| BACKUP / RESTORE / SETTINGS_EDIT | ✅ | — | — | — | — | — |
| AUDIT_LOG_VIEW | ✅ | — | — | — | — | — |

## Verified flows (manual smoke)
- Bootstrap → migrate → seed → setup wizard → login works against an isolated temp DB.
- Admin auth with valid password returns a Principal containing the full permission set.
- Bad password raises `AuthenticationError`; 5 failures trigger `AccountLockedError`.
- Receptionist principal calling `list_users()` raises `PermissionDeniedError`.
- `create_user` + `reset_password` round-trip hashes the password with bcrypt.

## Notable design decisions this phase
1. **Validation before writes.** `setup_service.run_setup()` validates clinic name, dentist list, username length, password length **before** opening any write transaction; partial failures cannot leak rows.
2. **RBAC at the service layer.** Every mutating service method takes a `principal` and checks permissions; UI only hides buttons for convenience. A buggy or compromised UI cannot escalate.
3. **Auto-lock via event filter** rather than polling input devices. The `_ActivityFilter` QObject is installed on the QApplication and emits on mouse/key events, feeding `Session.touch()`.
4. **Lock dialog cancel = logout.** If a user walks away and dismisses the lock screen, the session re-opens at login rather than leaving an unlocked window.
5. **Seeds are idempotent.** `seed_defaults()` checks for existing rows before inserting, so re-running on upgrades does not duplicate reference data.

## Known intentional deferrals (scoped to later phases)
- Full role CRUD UI (Phase 3 ships role assignment; creating new role templates is deferred to Phase 12 Admin Console since seeded roles cover v1).
- Dirty-form save prompt before auto-lock (comes with data-entry forms in Phase 4–8).
- Full Staff tab (employee records, payroll, attendance — Phase 11).

## Files changed in this PR
`dentiva/db/seed.py`, `dentiva/services/{setup,auth,user,clinic,dentist,audit}_service.py`, `dentiva/ui/dialogs/{setup_wizard,lock_dialog}.py`, `dentiva/ui/views/staff/staff_view.py`, `dentiva/ui/widgets/forms.py`, plus edits to `dentiva/app.py`, `dentiva/auth/session.py`, `dentiva/core/unit_of_work.py`, `dentiva/ui/dialogs/{__init__,activation,login}.py`, `dentiva/ui/main_window.py`, `pyproject.toml`, and the test suite (`tests/conftest.py`, `tests/integration/*`, `tests/services/`).

## Next (Phase 4) — Dashboard & Global Search
Pending your explicit "Continue". Planned: real dashboard widgets (today's appointments, revenue tile, pending invoices, low stock alerts), global command palette / search (Ctrl+K) across patients/appointments/invoices, and the notification center badge.
