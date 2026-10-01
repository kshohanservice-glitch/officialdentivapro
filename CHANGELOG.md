# Changelog

All notable changes to Dentiva Pro are documented here. Versions correspond to
git tags (`v1.0.0`, etc.).

## v1.0.0 — 2026-10-01

Initial production release of Dentiva Pro.

### Highlights

* **Fully offline** — no network, telemetry, paid API, or cloud service required
  at runtime after activation.
* **Activation**: one-time offline code `1516591935015165` (HMAC-obfuscated,
  machine-bound via hardware fingerprint).
* **First-run setup wizard** — clinic profile, admin user, and first dentist
  configured on first launch; the app never opens to an empty dashboard.
* **Auto-lock** after 5/10/15/30 minutes of idle time.

### Clinical

* Patient records with demographics, medical history, allergies, chief complaint.
* Flagship **dental chart** (adult & pediatric) with per-encounter history.
* Visits/encounters with diagnosis, treatment notes, procedure entries.
* Appointment calendar with status, reason, dentist assignment.
* Reception queue for walk-ins.
* Treatment catalog with procedure pricing.

### Prescribing & Printing

* Multi-medicine prescription editor (morning/noon/night dosing, meal
  relation, duration, quantity, instructions).
* Flagship prescription print templates for A4 / A5 / thermal 80 mm /
  thermal 58 mm with Bangla-friendly rendering, signature block, PDF via
  the Windows print workflow.

### Financials (all values BDT/৳ as integer paisa)

* Immutable invoices after posting (void-and-recreate to change).
* Payments with Cash / bKash / Nagad / Rocket / Upay / Card / Bank / Other.
* Inventory with stock levels, categories, suppliers, and movements.
* Accounting / income & expense tracking.

### Security, RBAC, Audit

* bcrypt password hashing (per-user salt).
* Granular role-based permissions enforced at the **service layer**, not
  just UI hiding.
* User/staff management with role editor.
* Audit log of all significant actions.

### Notifications & Reminders

* Upcoming appointment reminders (configurable lead window).
* Daily schedule summary (first open of the day).
* Low-stock inventory alerts.
* Overdue-invoice alerts.
* Header bell badge; dedicated Notifications page; Settings tab for toggles.

### Backup & Restore

* Zip-format backups with SHA-256 manifest (DB hot-copy via the SQLite
  backup API + attachments + logo).
* **Pre-restore safety backup** created automatically before any restore.
* Checksum and `PRAGMA integrity_check` verification before committing a restore.
* Path-traversal guards on attachment and backup file opens.
* Automatic backup interval (0–90 days) and startup due prompt.
* Configurable backup folder.

### Global Search & Attachments

* Ctrl+K / Ctrl+F popup searches patients, appointments, invoices,
  prescriptions, inventory, treatments, and attachments.
* File attachments stored as `<yyyymm>/<uuid><ext>` on disk (never
  user-supplied names), 50 MB per-file cap, full CRUD from the dedicated
  Attachments page and from inside each patient's profile.

### Packaging & Release

* Windows installer built via NSIS (Program Files, Start Menu, desktop
  shortcut, uninstall entry). Per-user data under `%APPDATA%\DentivaPro`
  is preserved on uninstall.
* GitHub Actions CI runs ruff/mypy/pytest on Ubuntu + Windows on every push.
* Release workflow builds a PyInstaller onedir bundle, compiles the NSIS
  installer, and publishes to GitHub Releases on `v*` tags (with a
  `dist/` fallback if the upload step is unavailable).

### Credits

Developed by Shohan Khan — <helloiamshohan@gmail.com>.
