# Dentiva Pro — Phase 1: Architecture & Engineering Plan

**Product:** Dentiva Pro — Offline Dental Clinic Management for Bangladesh
**Lead Architect Plan — Phase 1 (Planning Only, No Production Code)**
**Date:** 2026-10-01

---

## 1. Repository & Environment Inspection

| Item | Status |
|------|--------|
| Repository | `/home/user/officialdentivapro`, branch `arena/01a0f68e-officialdentivapro`, branched from `main` commit `196ac40` (initial commit) |
| Existing code | Empty repository except for `README.md` ("# officialdentivapro") |
| Build host | Debian 12 (bookworm), Python 3.11.2, gcc/g++ 12.2, git 2.39, gh CLI 2.23, Node 22.22, npm 10.9 |
| SQLite | 3.40.1 (bundled with Python) — sufficient for production offline use |
| System memory / disk | 3.8 GB RAM, 20 GB free |
| Tkinter | Not available (not relevant; not chosen) |
| Packaging target | Windows 10/11 x64; all production binaries built by GitHub Actions on `windows-latest` |

---

## 2. Product Scope Recap (Key Mandates)

- Fully offline Windows desktop application, BDT/৳ currency, English UI with full Bangla/Unicode input support everywhere.
- First-run setup wizard (clinic info, logo, dentists, admin credentials).
- Secure auth with hashed passwords, session management, auto-lock (5/10/15/30 min).
- Granular RBAC enforced in the service layer, not just UI.
- Full patient lifecycle (search/list/profile/history/visits/appointments/payments/invoices/prescriptions/treatments/attachments).
- Premium dental chart (adult + pediatric tooth numbering, per-encounter historical findings).
- Appointment scheduling, queue management, treatment catalog, prescription editor with structured clinical sections, invoice & payments, inventory, accounting, staff/users, backup/restore, settings, notifications, global search, audit log, attachments.
- Flagship print templates (prescriptions & invoices) with A4/A5/thermal paper support, Bangla rendering, PDF export.
- Activation code `1516591935015165` one-time offline activation with obfuscation.
- Genuine Windows installer (Start Menu, shortcut, icon, uninstall preserving data, data removal opt-in).
- GitHub Actions CI → Windows release artifact (GitHub Releases primary, `dist/` fallback).
- Complete automated tests, stress tests, UI audit, clean-machine installation test, license audit.
- Single final production version; no "we'll add it later" gaps.

---

## 3. Technology Stack Selection

### 3.1 Python Version
- **Python 3.11.x** — excellent performance, stable, well-supported by PySide6, PyInstaller/Nuitka, and GitHub Actions `windows-latest`.

### 3.2 Desktop UI Framework
- **PySide6 (Qt for Python 6)** — License: **LGPLv3** (permits proprietary/commercial redistribution without disclosing application source, provided the Qt library itself is dynamically linkable/relinkable; we will ship LGPL notices and allow library upgrade, which PyInstaller onedir + NSIS naturally supports).
- Rationale over alternatives:
  - PyQt6 is GPLv3 — incompatible with closed-source commercial distribution without expensive Riverbank license.
  - Tkinter looks dated, lacks rich widgets, poor printing, poor HiDPI, poor theming — unsuitable for premium clinical product.
  - wxPython has weaker widget quality, weaker styling, and weaker printing/Unicode toolchain.
  - Electron/Tauri would mandate shipping Chromium (≥150 MB), plus Node runtime, contradicts "no unnecessary bloat," and complicates offline distribution; also the team skill set here is Python, not JS/TS.
  - .NET/WPF would force a C# rewrite and lose the existing Python ecosystem (SQLAlchemy, Alembic, bcrypt) for no real gain.
- Qt 6 gives us: native Windows look, HiDPI/scaling, mature printing (QPrinter, QPrintPreviewDialog, QPainter → native Windows print dialog → Save as PDF), rich widgets (QTableView, QCalendarWidget, QFileSystemModel), CSS-like QSS theming, QSS animations, QSettings, QtSql for integration points, SQLite driver, strong Unicode/Bangla shaping via HarfBuzz, mature signals/slots, QThread for background work, model/view architecture for large tables, system tray/notifications integration.

### 3.3 Database
- **SQLite 3.x** (via Python stdlib `sqlite3`, accessed through SQLAlchemy).
- Rationale: zero-install file-based RDBMS, proven in production desktop apps, ACID, supports WAL mode, foreign keys, triggers, indexes; well-suited to single-clinic single-machine offline use. Avoids the operational overhead of shipping Postgres/MySQL for an offline clinic.
- PRAGMAs at startup: `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `recursive_triggers=ON`, `mmap_size` appropriately sized, `temp_store=MEMORY`.
- Money stored as **INTEGER minor units (paisa)** to eliminate floating-point errors. Display layer converts to BDT/৳ with Decimal formatting.

### 3.4 ORM & Data Access
- **SQLAlchemy 2.x** (declarative 2.0 style, typed Mapped[]). Mature, well-tested, excellent SQLite support.
- Sessions scoped to units of work; explicit transactions for multi-record operations (visits+treatments+invoice, payment+invoice update, etc.).
- Repository/Service layer pattern so permission checks live in service methods, not UI code.

### 3.5 Migrations
- **Alembic** — canonical partner to SQLAlchemy. Migrations committed to `dentiva/migrations/versions/`.
- Use batch_alter_table for SQLite ALTER TABLE limitations.
- On application startup, Alembic runs `upgrade head` after creating a pre-migration safety backup on first launch of a new version.

### 3.6 Password Hashing
- **bcrypt** (via `bcrypt` PyPI package). Slow KDF with per-password salt, well-audited, parameterized work factor (default 12, configurable), no known practical breaks in 2026. Chosen over argon2-cffi because bcrypt has extremely stable wheels on Windows, fewer native-build pitfalls for PyInstaller/Nuitka, and meets "modern, salted, configurable" requirement. Work factor stored per-hash so future upgrades are possible.
- PBKDF2/MD5/SHA1/SHA-256 alone explicitly rejected (too fast, vulnerable to GPU cracking).

### 3.7 PDF / Printing
- **Qt Print Subsystem (QPrinter, QPrintDialog, QPrintPreviewDialog, QPainter, QTextDocument)**.
- Rationale: renders identically to screen preview, physical printer, and Microsoft Print to PDF. Natively supports Windows printer selection, paper sizes (A4, A5, custom/thermal), margins, page ranges, and Unicode. No external PDF libraries required. Avoids reportlab's weaker Bangla font shaping and additional dependency; avoids weasyprint's heavyweight native stack. We can always render to PDF using the built-in "Microsoft Print to PDF" and via QPrinter's PDF output mode on non-Windows for testing.
- Custom paper profiles (including thermal 80mm) supported via QPageSize/QPageLayout.

### 3.8 Image Handling
- **Pillow (PIL)** — used for logo/photo/attachment thumbnails, icon generation pipeline, image validation/downscaling. Mature MIT-licensed.
- App icon generated from SVG source and rendered to all required sizes (16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512) and compiled into an `.ico` via Pillow + Microsoft-style pack.

### 3.9 Validation & Configuration
- **Pydantic 2.x** — for strict typed settings validation (clinic profile validation at setup, settings schema validation, import/export validation where needed).
- **QSettings** (Qt) for user preferences and window state; structured JSON for application data that must be backed up and migrated.

### 3.10 Date/Time & Locale
- `datetime` (UTC internally), `zoneinfo` for Asia/Dhaka display. `Babel` or Qt's QLocale for locale-aware number/date formatting (with manual BDT symbol rules to avoid ৳ placement issues).

### 3.11 Logging
- Python `logging` module with `RotatingFileHandler` (5 MB × 5 backups) into `%APPDATA%/DentivaPro/logs/`. Structured log format; sensitive fields (passwords, PHI payloads) filtered out via a logging filter. Never logs to network. Never logs passwords, hashes, or full patient clinical notes (only event type + IDs).

### 3.12 Testing
- **pytest** + **pytest-qt** for unit + integration + UI tests.
- **pytest-cov** for coverage reporting.
- In-memory SQLite for most tests; file-based SQLite for migration/backup tests.
- Factory pattern via **factory_boy** for test data generation.
- Hypothesis-style randomized stress data generation via custom scripts for large-dataset performance tests.

### 3.13 Code Quality
- **Ruff** (lint + format, replaces flake8/isort/black with one fast tool).
- **mypy** for static typing on the business/service layer.

### 3.14 Packaging
- **PyInstaller 6.x** (onedir mode, not onefile) as the primary packaging tool. Rationale:
  - PyInstaller is extremely reliable for PySide6 on Windows, with official Qt support and well-known hook recipes.
  - onedir mode yields faster startup (no self-extraction), fewer Windows Defender false positives than onefile, easier to inspect/debug, easier to pair with NSIS.
  - Build time ~1-2 minutes on CI, well within Actions limits.
- **Nuitka** is kept as an optional secondary build target if final VirusTotal/signing/performance needs demand it, but the primary release will be PyInstaller onedir.

### 3.15 Installer
- **NSIS 3.x** (Nullsoft Scriptable Install System).
- Rationale: zlib/libpng/BZip2/LZMA licensed — fully free and open source, no commercial license required (unlike Inno Setup which now requests commercial licensing), produces small professional installers, supports custom pages, shortcuts, uninstall with data preservation flag, silent install, and is trivially scriptable on CI. Used by many production Windows applications. Supports custom branding images for the wizard UI.
- Installer features:
  - Install to `%ProgramFiles%\DentivaPro` by default (per-machine) or `%LocalAppData%\DentivaPro` (per-user).
  - Creates Start Menu folder "Dentiva Pro" with application shortcut and uninstaller.
  - Optional desktop shortcut.
  - Associates no file types by default (prescription PDFs are user-saved).
  - Embeds application icon for the EXE, the uninstaller, and the installer itself.
  - Uninstaller: by default preserves `%APPDATA%\DentivaPro\data` (database/backups/attachments); offers a checked "Remove all clinic data" option with typed confirmation.

### 3.16 CI/CD
- **GitHub Actions** on `windows-latest` for:
  - Lint (ruff), typecheck (mypy), tests (pytest with coverage).
  - Build PyInstaller onedir artifact.
  - Compile NSIS installer.
  - Upload build artifacts.
  - Publish GitHub Release on tag (manual workflow_dispatch for final release).
- PR workflow runs lint + tests on every push/PR; protected branches require PR review.
- Build is reproducible via pinned dependency versions in `requirements.lock` (pip-compile).

### 3.17 Activation
- Offline fixed-code system. Activation code `1516591935015165` is **never** stored as a literal in source. Instead:
  - A salted **HMAC-SHA256** digest of the code (with an embedded application-specific salt) is stored in the binary in an obfuscated form (split across multiple modules, XOR'd, recombined at runtime).
  - At activation, the user-entered code is normalized (whitespace stripped) and its HMAC is compared against the embedded digest using `hmac.compare_digest` (constant-time).
  - On success, an **activation record** (hardware-bound via `uuid.getnode()` + Windows MachineGuid SID where available, HMAC'd with a per-machine salt) is written to `%APPDATA%/DentivaPro/config/activation.dat`. Subsequent launches verify this record without asking the user again.
  - Tamper-resistance: activation file includes an HMAC; modification invalidates it and triggers re-prompt.
  - Honest security note (documented in `docs/SECURITY.md`): no offline fixed-code scheme can be made mathematically unbreakable; this provides reasonable commercial-grade resistance against casual piracy while keeping the app fully offline.

### 3.18 Icons & Asset Pipeline
- Product icon designed specifically for Dentiva Pro: a stylized tooth silhouette with a subtle "D/P" monogram in a modern shield/circle, in a premium clinical blue/teal palette.
- Source SVG stored in `assets/icon/dentiva-pro.svg`.
- Rendered via a Python build script using Pillow + resampling to all required Windows sizes (16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512) and packed into `assets/icon/dentiva-pro.ico` with proper alpha transparency, no accidental background box, optical centering, and safe padding.
- `.ico` is referenced in PyInstaller spec (`icon='assets/icon/dentiva-pro.ico'`) and in NSIS script (`Icon`/`UninstallIcon`).
- A small set of custom toolbar/navigation icons (tooth, calendar, queue, prescription, invoice, payment, inventory, accounting, users, backup, settings, about) will be designed/generated in a consistent stroke style and shipped as Qt resources (`.qrc` compiled to `_rc.py`).

### 3.19 Localization / Unicode
- All UI strings in English by default.
- Bangla input supported everywhere via standard Windows IME — Qt 6 HarfBuzz handles Bengali shaping (including conjuncts) when a suitable Bengali font is present (Windows ships with Vrinda, Kalpurush, SolaimanLipi via user install; we will bundle the permissively licensed **Kalpurush** or **Noto Sans Bengali** as a fallback font — SIL Open Font License 1.1, which permits commercial redistribution with accompanying license).
- Database is SQLite (UTF-8 native). All patient names, notes, prescriptions, Bangla medicine names stored as Unicode.
- Date/time, number, and currency formatting: Qt QLocale default English (BD) with ৳ symbol, but formatters go through `core/money.py` and `core/dates.py` so Bangla numerals are not forced (Western numerals are the clinical norm in Bangladesh; users may type Bangla in free-text fields).

### 3.20 Key Dependencies & Licensing Pre-Audit

| Package | License | Commercial redistribution | Notes |
|---------|---------|---------------------------|-------|
| PySide6 (Qt for Python) | LGPLv3 | Yes (dynamic link, provide LGPL notice, allow library relink) | Will ship `LICENSES/LGPL-3.0.txt` and Qt notices; onedir packaging satisfies dynamic-link/replacement criterion |
| SQLAlchemy | MIT | Yes | |
| Alembic | MIT | Yes | |
| bcrypt | Apache-2.0 | Yes | |
| Pillow (PIL) | HPND (MIT-like) | Yes | |
| Pydantic 2 | MIT | Yes | |
| PyInstaller | GPL-with-exception (its bootloader has linking exception) | Yes — permits bundling with proprietary apps | License: GPL with special exception for bootloader; widely used for commercial apps |
| pytest, pytest-qt, pytest-cov | MIT | Yes (dev only) | |
| factory_boy | MIT | Yes (dev only) | |
| Ruff | MIT | Yes (dev only) | |
| mypy | MIT | Yes (dev only) | |
| Noto Sans Bengali / Kalpurush | OFL-1.1 | Yes (bundling permitted with license) | Bundled as fallback font |
| NSIS | zlib/libpng (BSD-style) | Yes | |
| Reportlab, Weasyprint, Playwright, Tkinter, Electron, PyQt6 | — | Rejected / not used | See rationale above |

No paid runtime dependency, no telemetry, no cloud API, no online authentication.

---

## 4. Application Architecture

### 4.1 Layered Architecture

```
+-------------------------------------------------------------+
|                       Presentation (UI)                     |
|  PySide6 widgets, dialogs, views, view-models, print views  |
+-------------------------------------------------------------+
|         Qt signals/slots  →  Application controllers        |
+-------------------------------------------------------------+
|                         Services / Use-Cases                |
|  AuthService, PatientService, VisitService, InvoiceService, |
|  PaymentService, InventoryService, AccountingService,       |
|  PrescriptionService, AppointmentService, QueueService,     |
|  BackupService, SettingsService, AuditService, SearchSvc... |
|  (Permission checks enforced HERE — every method)           |
+-------------------------------------------------------------+
|                Repositories / Data-Access                   |
|     SQLAlchemy 2.0 sessions, typed queries, transactions    |
+-------------------------------------------------------------+
|                  SQLite Database File                       |
|           %APPDATA%/DentivaPro/data/dentiva.db              |
+-------------------------------------------------------------+
```

Cross-cutting:
- Logging service
- Config/Settings service (QSettings + JSON config)
- Permission policy engine
- Audit event bus (services emit; service persists)
- Unit-of-work transaction manager
- Print/PDF rendering subsystem
- Backup/Restore orchestrator

### 4.2 Module / Package Layout

```
officialdentivapro/
├── pyproject.toml                # project metadata, ruff/mypy/pytest config
├── requirements.in / requirements.txt  # pinned runtime deps
├── requirements-dev.in / requirements-dev.txt
├── README.md
├── LICENSE.txt                   # proprietary EULA notice (user text)
├── LICENSES/                     # third-party license texts (LGPL, MIT, OFL)
├── THIRD_PARTY_NOTICES.md
├── .github/
│   └── workflows/
│       ├── ci.yml                # lint + test
│       └── release.yml           # build installer + publish release
├── assets/
│   ├── icon/                     # SVG source + rendered .ico at all sizes
│   ├── fonts/                    # Noto Sans Bengali (OFL)
│   ├── images/                   # logo placeholder, wizard splash, empty-state
│   ├── themes/                   # QSS stylesheet(s)
│   └── resources.qrc             # Qt resource file
├── installer/
│   └── dentivapro.nsi            # NSIS installer script
├── scripts/
│   ├── build_icon.py             # SVG → multi-size .ico pipeline
│   ├── build_resources.py        # pyrcc6 (or rcc) invoker
│   ├── dist_pyinstaller.spec     # PyInstaller spec
│   ├── run_tests.py
│   └── seed_demo_data.py         # optional test data (dev only)
├── docs/
│   ├── PHASE1_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── SECURITY.md
│   ├── RBAC_MATRIX.md
│   ├── PRINT_TEMPLATES.md
│   ├── BACKUP_RESTORE.md
│   ├── ACTIVATION.md
│   └── USER_MANUAL.md (later)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   ├── ui/
│   ├── performance/
│   └── data/                     # fixtures
└── dentiva/
    ├── __init__.py
    ├── __main__.py               # entry point
    ├── app.py                    # QApplication bootstrap
    ├── bootstrap.py              # startup: paths, logging, config, migrations, auth
    ├── config.py                 # paths, constants
    ├── paths.py                  # Windows AppData path resolution
    ├── activation/
    │   ├── __init__.py
    │   ├── verifier.py           # obfuscated HMAC verification
    │   └── machine.py            # hardware-bound activation record
    ├── core/
    │   ├── logging_setup.py
    │   ├── money.py              # Decimal + paisa integer helpers, BDT formatting
    │   ├── dates.py
    │   ├── permissions.py        # Permission enum + Policy engine
    │   ├── errors.py             # typed exceptions + user-facing error mapping
    │   ├── unit_of_work.py
    │   ├── pagination.py
    │   └── validators.py
    ├── db/
    │   ├── engine.py             # SQLAlchemy engine/session factory
    │   ├── base.py               # DeclarativeBase
    │   ├── types.py              # MoneyType, UTCDateTime, etc.
    │   └── migrations/           # Alembic directory (env.py, script.py.mako, versions/)
    ├── models/                   # SQLAlchemy ORM models (~30 entities)
    │   ├── __init__.py
    │   ├── clinic.py
    │   ├── security.py           # User, Role, Permission, AuditEvent
    │   ├── staff.py
    │   ├── dentist.py
    │   ├── patient.py
    │   ├── visit.py
    │   ├── tooth.py              # tooth reference + dental chart
    │   ├── appointment.py
    │   ├── queue.py
    │   ├── treatment.py
    │   ├── prescription.py
    │   ├── invoice.py
    │   ├── payment.py
    │   ├── inventory.py
    │   ├── accounting.py
    │   ├── attachment.py
    │   ├── notification.py
    │   ├── backup.py
    │   └── settings.py
    ├── services/                 # business logic / RBAC boundary
    │   ├── auth_service.py
    │   ├── user_service.py
    │   ├── clinic_service.py
    │   ├── dentist_service.py
    │   ├── patient_service.py
    │   ├── visit_service.py
    │   ├── dental_chart_service.py
    │   ├── appointment_service.py
    │   ├── queue_service.py
    │   ├── treatment_service.py
    │   ├── prescription_service.py
    │   ├── invoice_service.py
    │   ├── payment_service.py
    │   ├── inventory_service.py
    │   ├── accounting_service.py
    │   ├── staff_service.py
    │   ├── attachment_service.py
    │   ├── backup_service.py
    │   ├── restore_service.py
    │   ├── settings_service.py
    │   ├── notification_service.py
    │   ├── audit_service.py
    │   └── search_service.py
    ├── repositories/             # thin data-access layer (optional but clean)
    ├── auth/
    │   ├── password.py           # bcrypt hash/verify, strength policy
    │   ├── session.py            # current-user context, lock timer
    │   └── lock.py               # auto-lock manager
    ├── printing/
    │   ├── profiles.py           # paper/printer profile model
    │   ├── prescription_renderer.py
    │   ├── invoice_renderer.py
    │   └── render_utils.py
    ├── backup/
    │   ├── backup.py
    │   └── restore.py
    ├── ui/
    │   ├── theme.py              # QSS loader, color palette, typography
    │   ├── design_tokens.py      # spacing, radius, elevation, font sizes
    │   ├── widgets/              # reusable premium widgets (cards, buttons, inputs, tables, dialogs, empty-state, toasts)
    │   ├── resources_rc.py       # compiled Qt resources
    │   ├── main_window.py        # shell (header + collapsible sidebar + stacked content area)
    │   ├── navigation.py         # sidebar nav tree
    │   ├── dialogs/
    │   │   ├── login_dialog.py
    │   │   ├── activation_dialog.py
    │   │   ├── setup_wizard.py   # first-run wizard
    │   │   ├── lock_dialog.py
    │   │   └── confirm_dialogs.py
    │   ├── views/
    │   │   ├── dashboard/
    │   │   ├── patients/
    │   │   ├── appointments/
    │   │   ├── queue/
    │   │   ├── treatments/
    │   │   ├── prescriptions/
    │   │   ├── invoices/
    │   │   ├── payments/
    │   │   ├── inventory/
    │   │   ├── accounting/
    │   │   ├── staff/
    │   │   ├── backup_restore/
    │   │   ├── settings/
    │   │   └── about/
    │   └── patient_profile/       # tabbed patient profile view
    └── utils/
```

### 4.3 Application State / Lifecycle
1. OS launches `DentivaPro.exe` → Qt app starts.
2. `bootstrap.py` resolves data paths under Windows `%APPDATA%\DentivaPro` (creates directories if missing).
3. Config/logging initialized.
4. DB engine created; if DB does not exist → empty DB created and Alembic stamped to head; otherwise migrations auto-applied (with pre-migration backup).
5. Activation file checked. If no valid activation → **Activation dialog** blocks entry.
6. After activation, if clinic profile not yet set up → **First-run Setup Wizard** (clinic info, logo, dentists, admin user).
7. After setup complete → **Login dialog**.
8. On successful login → **Main Window** opens, Dashboard loaded, inactivity auto-lock timer armed.
9. Lock screen triggers on idle; unsaved data protected via prompt before lock when possible (modal "save/discard/cancel" on dirty forms).
10. On app close → graceful session end audit event, DB checkpoint, flush logs, close engine.

### 4.4 Permission Enforcement Strategy
- `core/permissions.py` defines `Permission(Enum)` with all granular permissions (see §6).
- Every authenticated session holds an immutable `Principal` (user id, role ids, set of effective permissions).
- Every service method receives the current `Principal` (explicit argument, not global, to prevent accidental bypass) and calls `policy.require(principal, Permission.X)` at the top.
- UI can additionally hide/disable controls as a UX courtesy, but UI-hiding is **never** the authoritative check.
- Search results and dashboard widgets filter at query time based on principal permissions (e.g., no financial widgets if `VIEW_FINANCIAL` is absent).
- Audit log records authorization failures.

### 4.5 Data Integrity & Concurrency
- SQLite is opened with a connection timeout; all writes occur on the main thread's unit of work OR are serialized through a single writer queue (SQLite supports one writer; background tasks post write requests to the main DB thread via Qt signals).
- Multi-record operations use explicit transactions: `with session.begin(): ...` — failure rolls back atomically.
- Foreign keys always `ON`. Foreign-key behavior chosen per relation: `RESTRICT` for destructive financial/clinical deletes (prevent orphaning historical invoices), `CASCADE` only for owned dependent records (e.g., prescription medicines).
- Soft-delete (`deleted_at` column) used for patients, staff, dentists, suppliers, catalog items; hard delete only for draft/never-finalized records and only with audit + typed confirmation.

### 4.6 Financial Integrity
- All monetary amounts stored as **Integer paisa** (1 BDT = 100 paisa).
- All calculations use Python `decimal.Decimal` at the service boundary, converted to/from paisa integers at persistence.
- Invoices are **finalized (posted)** → thereafter immutable. Corrections are made via separate audited credit/adjustment records, never by editing historical line items.
- Payments always linked to an invoice and a payment method; payment creation updates invoice outstanding atomically.
- Deleting a payment is not a silent delete; it is an audited reversal that re-opens balance.

### 4.7 Backup & Restore Architecture
- Backups are atomic copies of the SQLite database (using `sqlite3` backup API for online-safe copies) plus:
  - `config/settings.json`
  - `config/activation.dat` (encrypted per-machine)
  - `attachments/` directory (patient files)
  - `logos/` (clinic/dentist assets)
  - Backup metadata JSON (product version, timestamp, schema version, checksum).
- All of the above is zipped into `dentiva-backup-YYYYMMDD-HHMMSS.zip` with an internal manifest + SHA-256 checksum file.
- Restore flow:
  1. User selects backup zip via Windows file dialog.
  2. Zip validated (checksum, schema version compatibility, product version floor).
  3. **Pre-restore safety backup** of current live DB is created automatically and confirmed.
  4. Restore runs in a transactional sequence: close connections → replace files → run migrations if backup schema older → reopen → verify integrity.
  5. Progress dialog; errors reported with non-technical messages + log details.
- Scheduled automatic backups (7/15/30 day interval via app-startup time check + next-backup timestamp persisted) never silently fail: failure shows a notification, logs the error, and is recorded as a notification visible in the notification center.

### 4.8 Print Architecture
- Paper-size profiles defined as data (A4 portrait, A5 portrait, Thermal 80mm width, custom).
- Each renderer (`prescription_renderer.py`, `invoice_renderer.py`) receives a record and a profile and produces a `QTextDocument` (for fluid text-heavy content) **or** uses `QPainter`-based drawing (for precise positioning: tooth chart, signature area, invoice totals box).
- Renderers produce identical output for `QPrintPreviewWidget`, `QPrinter` (physical printer), and `QPrinter` to PDF (QPrinter::PdfFormat).
- Bangla text uses a font cascade: preferred configured font → bundled Noto Sans Bengali → system default. Tested across paper sizes; page-break rules defined so multi-medicine prescriptions and multi-line invoices continue gracefully across pages.
- Signature area (prescription only) reserves a 4cm × 2.5cm blank block with "Signature" label placed outside the signing rectangle so handwriting is not interfered with.
- Invoice header matches clinic profile (logo, name, address, phone). Signature block omitted unless a jurisdiction-required configuration flag is set.

---

## 5. Data Model (Summary)

Defined in detail in `docs/DATA_MODEL.md` (will be finalized in Phase 2 with exact column types/constraints/indexes). High-level entity list:

1. **clinic_profile** — single row: name, logo_path, address, phone, email, tagline, footer_note, currency (BDT fixed), created_at.
2. **dentist** — id, name, designation(s) (multi-value via dentist_designation), qualifications, certifications, registration_no, signature_path, is_active, notes.
3. **designation** — reusable lookup (BDS, DDS, DMD, FCPS, MS, etc.), name.
4. **dentist_designation** — association (many-to-many).
5. **role** — id, name, is_system, permissions_json (or join with permission_set).
6. **permission_set** — role_id, permission (enum string) for granular RBAC.
7. **user** — id, username (unique), password_hash, password_set_at, failed_login_attempts, locked_until, staff_id (nullable), is_active, last_login_at, must_change_password, created_at.
8. **staff** — id, name, role_title, dob, gender, blood_group, address, phone, nid, photo_path, salary_paisa, joining_date, employment_status, notes, created_at, deleted_at.
9. **patient** — id, patient_code (unique indexed), name, dob, age_cache, gender, blood_group, address, phone, emergency_phone, email, chief_complaint, medical_history, allergies, notes, created_by, created_at, updated_at, deleted_at.
10. **visit** — id, patient_id, dentist_id, visit_date, reason, chief_complaint, on_examination, advice, notes, status (open/closed), created_by, created_at.
11. **tooth_reference** — static reference table: tooth_code (FDI 11-48, 51-85; ADA 1-32; and pediatric), name, quadrant, is_pediatric, position.
12. **dental_chart_finding** — id, visit_id, tooth_code, finding (enum: caries, restoration, missing, extracted, impacted, mobility_i/ii/iii, sensitivity, periodontal_pocket, gingivitis, pulpitis, attrition, erosion, dry_socket, other), notes, surface (optional), created_by, created_at — per-visit historical.
13. **appointment** — id, patient_id, dentist_id, scheduled_at, duration_minutes, reason, status (scheduled/confirmed/completed/missed/cancelled/rescheduled), notes, created_by, created_at, updated_at.
14. **queue_entry** — id, patient_id, dentist_id, appointment_id (nullable), status (waiting/in_progress/completed/cancelled), arrived_at, started_at, finished_at, position, created_by, created_at.
15. **treatment_catalog** — id, name, description, category, default_price_paisa, is_active, created_at.
16. **treatment_record** — id, visit_id, patient_id, dentist_id, catalog_id (nullable), name_at_service_time, description, tooth_codes (csv or association), price_paisa (snapshot), notes, created_by, created_at.
17. **prescription** — id, visit_id (nullable), patient_id, dentist_id, date, chief_complaint, on_examination, advice, notes, finalized, finalized_at, created_by, created_at, updated_at.
18. **prescription_medicine** — id, prescription_id, idx (for order), name, form, strength, frequency_morning/noon/night booleans, meal_relation (before/after/with), duration_days, quantity, instructions, created_at.
19. **clinical_template_option** — configurable list per section (CC, OE, Advice) for quick-select — id, section_key, display_text, sort_order, is_active.
20. **invoice** — id, invoice_number (unique sequential/year), patient_id, dentist_id, visit_id (nullable), date, subtotal_paisa, discount_paisa, tax_paisa, total_paisa, paid_paisa, due_paisa, status (unpaid/partial/paid/cancelled/refunded), notes, is_posted, posted_at, voided_at, created_by, created_at.
21. **invoice_line_item** — id, invoice_id, item_type (treatment/catalog/custom), reference_id (treatment_record_id or catalog_id or null), description, quantity, unit_price_paisa, discount_paisa, line_total_paisa.
22. **payment_method** — static + configurable: Cash, bKash, Nagad, Rocket, Upay, Card, Bank, Other.
23. **payment** — id, invoice_id, patient_id, method_id, amount_paisa, reference_no, notes, paid_at, created_by, created_at, reversed_at.
24. **supplier** — id, name, contact_person, phone, address, email, notes, is_active, created_at.
25. **inventory_category** — id, name, parent_id.
26. **inventory_item** — id, sku, name, category_id, unit, location, min_level_qty, current_qty, notes, created_at.
27. **inventory_movement** — id, item_id, movement_type (purchase/consume/return/adjust/expiry_writeoff), quantity_delta, unit_price_paisa (for purchase), supplier_id (nullable), batch_no, expiry_date (nullable), reference (e.g. invoice#), notes, created_by, created_at.
28. **accounting_category** — id, name, kind (income/expense), parent_id, is_active.
29. **accounting_entry** — id, date, category_id, kind (income/expense), amount_paisa, payment_method_id, reference, description, related_invoice_id (nullable), related_payment_id (nullable), created_by, created_at.
30. **attachment** — id, patient_id (polymorphic via attachable_type/id), original_filename, stored_filename, content_type, size_bytes, title, notes, uploaded_by, created_at.
31. **referral** — id, patient_id, referred_to, reason, date, notes, created_by, created_at.
32. **notification** — id, user_id (or global), kind (appointment_upcoming/appointment_missed/low_stock/expiring_stock/backup_failed/etc.), title, message, payload_json, is_read, read_at, created_at.
33. **audit_event** — id, timestamp, user_id (nullable if pre-auth), action (enum), entity_type, entity_id, summary, before_json (redacted), after_json (redacted), ip_or_machine.
34. **backup_record** — id, path, started_at, finished_at, status (success/failed), size_bytes, triggered_by (manual/scheduled/pre_restore), schema_version, checksum.
35. **app_setting** — key/value table with validated types (clinic defaults, auto-lock minutes, backup interval, printer profiles, paper defaults, etc.).
36. **printer_profile** — id, name, paper_size, margins_mm, orientation, is_default.
37. **schema_version** — Alembic-managed (`alembic_version` table).

### Key indexes
- `patient(patient_code) UNIQUE`, `patient(name)`, `patient(phone)`, `patient(created_at DESC)`.
- `visit(patient_id, visit_date DESC)`, `visit(dentist_id, visit_date)`.
- `appointment(scheduled_at, dentist_id, status)`.
- `queue_entry(status, dentist_id, position)`.
- `invoice(invoice_number UNIQUE)`, `invoice(patient_id, date)`, `invoice(status)`.
- `payment(invoice_id)`, `payment(paid_at)`, `payment(method_id)`.
- `inventory_movement(item_id, created_at DESC)`.
- `audit_event(entity_type, entity_id, timestamp DESC)`, `audit_event(user_id, timestamp DESC)`.
- `notification(user_id, is_read, created_at DESC)`.

---

## 6. RBAC Permission Matrix (Outline)

Defined in detail in `docs/RBAC_MATRIX.md`. High-level permission list:

**Patients**
- `PATIENTS_VIEW`, `PATIENTS_CREATE`, `PATIENTS_EDIT`, `PATIENTS_DELETE` (soft-delete, admin-only), `PATIENTS_EXPORT`

**Clinical**
- `VISITS_VIEW`, `VISITS_CREATE`, `VISITS_EDIT`, `DENTAL_CHART_VIEW`, `DENTAL_CHART_EDIT`, `PRESCRIPTIONS_VIEW`, `PRESCRIPTIONS_CREATE`, `PRESCRIPTIONS_EDIT`, `PRESCRIPTIONS_PRINT`, `TREATMENTS_VIEW`, `TREATMENTS_CREATE`, `TREATMENTS_EDIT`, `TREATMENTS_CATALOG_MANAGE`

**Appointments / Queue**
- `APPOINTMENTS_VIEW`, `APPOINTMENTS_CREATE`, `APPOINTMENTS_EDIT`, `APPOINTMENTS_CANCEL`, `QUEUE_MANAGE`, `QUEUE_REORDER`

**Financial (sensitive — restricted by default)**
- `INVOICES_VIEW`, `INVOICES_CREATE`, `INVOICES_EDIT`, `INVOICES_VOID`, `INVOICES_PRINT`, `PAYMENTS_VIEW`, `PAYMENTS_CREATE`, `PAYMENTS_REFUND`, `ACCOUNTING_VIEW`, `ACCOUNTING_MANAGE`, `FINANCIAL_REPORTS_VIEW`, `FINANCIAL_SETTINGS_MANAGE`

**Inventory**
- `INVENTORY_VIEW`, `INVENTORY_CREATE`, `INVENTORY_EDIT`, `INVENTORY_ADJUST`, `SUPPLIERS_MANAGE`

**Staff & Users**
- `STAFF_VIEW`, `STAFF_CREATE`, `STAFF_EDIT`, `USERS_VIEW`, `USERS_CREATE`, `USERS_EDIT`, `USERS_RESET_PASSWORD`, `ROLES_MANAGE`

**System**
- `SETTINGS_VIEW`, `SETTINGS_MANAGE`, `DENTISTS_MANAGE`, `CLINIC_PROFILE_MANAGE`, `BACKUP_CREATE`, `BACKUP_RESTORE`, `BACKUP_CONFIGURE`, `AUDIT_LOG_VIEW`, `ACTIVATION_MANAGE`, `DESTRUCTIVE_OPERATIONS`, `DATA_EXPORT`, `PRINTERS_MANAGE`, `VIEW_REPORTS`, `NOTIFICATIONS_MANAGE`, `SEARCH_GLOBAL`, `ATTACHMENTS_VIEW`, `ATTACHMENTS_MANAGE`

Default roles seeded at setup:
- **Owner/Administrator** — all permissions.
- **Dentist** — all clinical permissions, patients view/create/edit, appointments view/create/edit, own invoices create, own prescriptions print; NO financial reports, NO accounting view/manage, NO user management, NO destructive ops, NO audit log.
- **Receptionist** — patients view/create/edit, appointments, queue, invoices create, payments create (record payments), patients export; NO accounting, NO financial reports, NO staff/user management, NO backups, NO settings.
- **Assistant** — patients view, appointments view, queue assist, inventory view; no financial, no settings.
- **Accountant** (optional) — financial permissions, accounting, reports; no clinical edit (view only).

Custom roles fully configurable in Settings.

---

## 7. Design System (Foundation)

Detailed QSS + design tokens will be implemented in Phase 2. Summary:

**Palette (restrained clinical premium):**
- Primary: deep clinical blue `#1F5AA6` (trust)
- Primary hover: `#2A6BC0`, active: `#174683`
- Accent: teal `#2BA5A0` (dental/medical clarity)
- Neutral backgrounds: `#F5F7FA` (page), `#FFFFFF` (card/surface), `#EBEEF3` (divider)
- Text: `#101828` (primary), `#475467` (secondary), `#667085` (tertiary)
- Success: `#12B76A`, warning: `#F79009`, error: `#F04438`, info: `#2E90FA`
- Dark-mode not planned for v1 (Windows dental clinics overwhelmingly run light mode; will support high-contrast Windows themes via palette overrides if needed but primary theme is light).

**Typography:**
- Default UI font: **Segoe UI** (native Windows) at 9-10pt, with **Noto Sans Bengali** registered as fallback for Bangla ranges.
- Headings: weight 600 (Semibold), sizes 18/16/14.
- Body: regular 10pt; tables 9-10pt; numeric columns tabular figures.

**Spacing scale (px rem-equivalent, Qt px at 96dpi base):** 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
**Border radius:** 4 (compact controls), 8 (cards, buttons, inputs), 12 (large cards/dialogs), 20 (pills/chips).
**Elevation (shadows):** none on page; soft 0 1px 2px rgba(16,24,40,.06) for cards; 0 4px 12px rgba(16,24,40,.08) for dropdowns/dialogs; 0 8px 24px rgba(16,24,40,.12) for modals.
**Buttons:** filled primary, outline secondary, text tertiary, destructive. Minimum touch/click height 32px; padding 8px 16px.
**Form controls:** height 32px; border `#D0D5DD`; focus ring primary/2px; error border/ring; disabled state 50% opacity, not allowed cursor.
**Tables:** zebra striping optional; sticky header; sortable columns; numeric columns right-aligned; proper cell padding (8px 12px); selected row primary/5%; hover row `#F2F4F7`.
**Cards:** 8px radius, 1px border `#EAECF0`, white background, 16-20px padding.
**Modals:** 12px radius, 24px padding, overlay 50% black @ 40% opacity, centered with sensible max width (560/720/960).
**Notifications/toasts:** top-right, 5s auto-dismiss, four semantic colors; action buttons.
**Icons:** consistent 1.5px stroke, 16/20/24/32px sizes, same color as accompanying text by default, primary color for active navigation.
**Animations:** property-based QPropertyAnimation on opacity/geometry only (150-200ms, ease-out); collapsible sidebar slide; toast slide-in; modal fade. Users can disable in Settings.
**Keyboard:** full tab navigation, visible focus rings, Enter to confirm dialogs, Esc to cancel/close, standard shortcuts (Ctrl+S save, Ctrl+P print, Ctrl+F global search, F5 refresh, Ctrl+L lock, Ctrl+Shift+A new appointment, etc.).

**Application shell dimensions:**
- Header bar: 56px, brand logo + clinic name left, date/center widget, notifications + user menu right.
- Sidebar expanded: 240px.
- Sidebar collapsed: 64px (icon + tooltip).
- Sidebar toggle button in header; state persisted via QSettings.
- Content area: scrollable main area with 24px outer padding.

---

## 8. Phased Implementation Plan

Below is the gated phase plan. Each phase ends with validation and a report. I will **not** proceed to the next phase until you respond "Continue."

| Phase | Name | Scope | Exit Criteria |
|-------|------|-------|---------------|
| **1** | **Architecture & Planning** | This document. Inspect repo, evaluate technologies, define architecture, data model, design system, RBAC, CI/CD, packaging, activation, test strategy, risks. | Plan accepted. |
| 2 | Project Foundation & App Shell | Repo structure, pyproject, deps, virtualenv, logging, config, paths, DB engine, SQLAlchemy Base, Alembic setup (first migration = schema skeleton), activation module, Qt theme/design tokens, QSS, resource pipeline, icon build script, main window shell (header + collapsible sidebar + stacked views), navigation wiring to placeholder views, login dialog (non-functional until phase 3), error handling, run-tests script, CI (ruff/mypy/pytest) on PR. | App launches, shows shell, sidebar collapses/expands, navigates between placeholder views, theme applied, CI passes, migrations run cleanly. |
| 3 | Setup Wizard, Auth & RBAC | Activation dialog (real verification), first-run setup wizard (clinic info, logo, dentists, admin user, validation), login, bcrypt password hashing, failed-attempt lockout, auto-lock (idle timer), User/Role/Permission models & seed defaults, policy engine, Staff & Users screen (user CRUD, role assignment, password change), lock dialog, session state. | Can activate, run setup, log in/out, auto-lock works, create users/roles, permission checks enforced at service layer. |
| 4 | Dashboard & Shared Widgets | Real dashboard with RBAC-aware widgets (today's patients, upcoming appts, queue, revenue [if authorized], low stock [later], quick actions), shared widget library (cards, stat tiles, tables with pagination, search bars, empty states, toasts, confirmation dialogs, date range picker). | Dashboard renders from real (seed/test) data; respects permissions; widgets click through to relevant modules. |
| 5 | Patient Management | Patient model, listing (filters today/7/30/90/1y/all; search by code/name/phone/age/gender/blood group/dentist), create/edit form with validation, duplicate detection, patient profile (header, tabs: Overview/Visits/Appointments/Treatments/Prescriptions/Invoices/Payments/Attachments/Notes/Timeline — empty initially). | Unlimited patients, search fast at 10k+ records, profile opens, all tabs render, audit recorded, RBAC enforced. |
| 6 | Visits, Dental Chart & Clinical Timeline | Visit creation from patient profile, dental chart (SVG-based interactive adult/pediatric, FDI numbering), per-encounter findings persistence, clinical timeline consolidation (visits/treatments/prescriptions/invoices), CC/OE/Advice quick-select, tooth interactions (select/click to mark findings, multi-select). | Chart renders, findings stored per visit, historical chart states preserved, timeline merges all events with filters. |
| 7 | Appointments & Queue | Appointment CRUD, calendar+list view, double-booking prevention with override, status transitions (scheduled/confirmed/completed/missed/cancelled/rescheduled), reminders/notifications, Queue module with arrival/start/finish/reorder, queue status reflected on dashboard and patient profile. | Real scheduling workflow; queue updates state atomically; dashboard reflects live counts. |
| 8 | Treatments & Prescriptions | Treatment catalog CRUD, patient treatment records (price snapshot, tooth linkage, invoice linkage), Prescription editor (multi-medicine add/reorder/remove/validate, structured CC/OE/Advice select, save draft → finalize), finalization immutability, print preview of prescription (all paper sizes A4/A5/Thermal), signature area, Bangla rendering, PDF output via QPrinter. | Can create multi-medicine prescription, print/preview/PDF work, finalize is immutable, catalog price change does not affect historical records. |
| 9 | Invoices, Payments & Financials | Invoice creation (from visit/patient/profile), line items (treatment/custom/qty/discount), subtotal/total/due, partial/full/unpaid status, immutability after posting, payment recording (Cash/bKash/Nagad/Rocket/Upay/Card/Bank/Other), daily totals, payment history filters, payments module (all transactions with filters), financial permission enforcement deep in services, invoice printing (A4/A5/thermal). | Full invoice→payment lifecycle works, due amounts update atomically, unauthorized users cannot access any financial data via any code path, prints render on all paper sizes. |
| 10 | Inventory & Accounting | Suppliers, categories, inventory items, SKU, stock movements (purchase/consume/return/adjust/expiry), low-stock and expiring-stock alerts, accounting categories, income/expense entries (linked to payments/invoices where appropriate), period reports (daily income/expense, net position, payment-method summary, treatment revenue, expense category, outstanding receivables). | Stock levels update consistently, movements auditable, reports reconcile with invoice/payment data, low-stock notifications fire. |
| 11 | Staff, Settings, Notifications & Global Search | Full Staff records module, Settings screens (clinic info/logo, dentists/designations, users/roles, appointment defaults, queue, prescription templates/clinical options, invoice/print settings/printer profiles/paper, currency/date formats, backup config, security/auto-lock, notification prefs, data management / destructive reset with typed confirmation), Notification center (real aggregated notifications, permission-aware, mark read, actionable), Global search (Ctrl+F) across patients/codes/phones/appointments/prescriptions/invoices/payments/inventory/staff filtered by permissions. | All settings persist and affect behavior; notifications reflect real events; search is fast and permission-filtered; destructive actions require typed confirmation + safety backup. |
| 12 | Attachments & Audit Log | Attachment upload (copy-into-app-data-store), mime/size validation, image preview, safe open, metadata, deletion rules, inclusion in backups; Audit log viewer (admin-only) with filters by entity/user/action/time, export; ensure audit captures all security/business-critical events. | Attachments survive source file moves; audit entries for all required events; audit log not editable; backups include attachments. |
| 13 | Backup & Restore | Manual backup (folder dialog, timestamped zip, checksum), scheduled auto-backup (7/15/30 days, failure notifications), restore flow (validation, pre-restore safety backup, progress dialog, integrity check, error handling), backup history view, restore safety. | Backups created and validated; restore works with safety net; incompatible backups rejected with clear messages. |
| 14 | Printing Hardening, Unicode, PDF Finalization | All print templates final (prescription flagship, invoice flagship, optional reports), Bangla font cascade testing, multi-page content, long names/addresses/medicine lists/invoice lines, paper-size-aware layouts, Save as PDF, physical printer selection, printer profiles saved, margins configurable, print settings persist. | Test prints at A4/A5/80mm thermal render correctly; multi-page content breaks properly; Bangla text shaped correctly in preview+PDF+paper. |
| 15 | Activation Hardening, Security & Audit | Activation obfuscation refinement, tamper detection, machine binding, security review (password policy, session fixation, audit capture completeness, SQL-injection testing via ORM verification, file-path safety for attachments/backups, permission bypass attempts via unit tests), auto-lock during unsaved data protection, error message user-friendliness review. | Penetration-style unit tests: unauthorized user cannot access financials via service methods; activation tampering detected; no stack traces shown. |
| 16 | Performance, Stress & Reliability | Pagination/virtualization for all large tables; query optimization; indexes added based on EXPLAIN; large-dataset seeding script (50k patients, 200k visits, 500k invoices/payments/audit events); test search/filter/list load times <500ms p95; double-submit protection on all forms; transactions verified on all multi-record operations; graceful shutdown; DB integrity check on startup. | Stress tests pass; large-dataset UI remains responsive; double-clicks do not create duplicate records; crash recovery does not corrupt DB. |
| 17 | Automated Test Suite | Comprehensive pytest + pytest-qt suite covering all mandated areas; unit tests for services, repositories, money/date helpers, permission policy, password hashing, activation; integration tests for migrations, full CRUD flows, financial calculations, backup/restore, RBAC enforcement, attachments; UI tests for major workflows; coverage target ≥80% for services/models, smoke coverage for UI. | All tests pass in CI; coverage reports uploaded; regression suite catches prior bugs. |
| 18 | UI/UX Systematic Audit | Systematic screen-by-screen inspection at multiple window sizes (1024×768, 1366×768, 1920×1080, 2560×1440) and DPI (100%, 125%, 150%, 175%); check for clipping/overlap/overflow/misalignment; check keyboard navigation; check all states (empty/loading/error/disabled/permission-denied); fix Bangla/long-text breakage; verify all buttons work; verify print previews. | Zero release-blocking UI defects; no TODO placeholders; no dead buttons; consistent design language across screens. |
| 19 | Packaging, Installer & Icon Finalization | Final icon (design/render ICO multi-size with optical centering + transparency + no background box), PyInstaller spec finalized & tested, NSIS installer script (Start Menu, desktop shortcut, uninstall, data preservation), version/company metadata on EXE, third-party license files bundled, GitHub Actions release workflow (build + sign if possible + upload artifact), smoke-test installer in clean Windows VM (GitHub Actions `windows-latest` environment). | Installer builds in CI, installs to clean Windows program files, launches, registers uninstall, icon correct in EXE/Start Menu/taskbar/shortcut. |
| 20 | License Audit & Dependency Review | Full license review of every dependency; THIRD_PARTY_NOTICES.md generated; LGPL compliance re-verified (dynamic linking, relinkability); no GPL-only depedencies accidentally pulled in; remove any forbidden deps. | All dependencies compatible with commercial closed-source distribution; notices shipped. |
| 21 | Final Release Validation & Production Build | Run full automated tests, clean build, install in fresh Windows environment (CI ephemeral runner), go through full first-run activation → setup → login → create patient → visit → dental chart → prescription (print/PDF) → invoice → payment → backup → restore → logout → lock → unlock → uninstall-without-data → reinstall → data present. Fix any defects found. | Release artifact (installer EXE) validated end-to-end; zero release-blocking defects. |
| 22 | Release Publication | Tag commit, push tag; GitHub Actions produces release; attempt to publish to GitHub Releases; if publishing fails, place validated artifacts in `dist/` with checksums; create PR for final release branch; report completion. | Release artifacts published or dist fallback populated; PR created for review. |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PySide6 LGPL compliance misstep | Low | Legal | Ship `LICENSES/` with LGPL + Qt notices; use onedir (no static linkage); document relink procedure in THIRD_PARTY_NOTICES. |
| PyInstaller false-positive antivirus | Medium | User trust | onedir mode (better than onefile), code-sign if certificate available later; provide SHA-256 checksums; document Windows Defender SmartScreen expectations. |
| Qt print layout breaking across paper sizes | Medium | Usability | Paper-aware renderer with tested profiles; page-break rules; automated visual regression of rendered PDFs in tests (QPrinter::PdfFormat + size assertions). |
| Bangla shaping glitches | Low-Medium | UX | Bundle Noto Sans Bengali; test with real Bangla text; QFont cascade tested; use Qt 6 HarfBuzz (known to support Bengali). |
| SQLite write contention | Low (single-user desktop) | Stability | WAL mode + single writer serialised through Qt thread; pragmas tuned; short transactions. |
| Backup zip corruption | Low | Data safety | SHA-256 manifest; validate before restore; never overwrite without pre-restore safety backup; atomic temp-file rename. |
| Activation bypass by determined attacker | Medium (offline fixed-code inherently limited) | Revenue | HMAC-SHA256 with split obfuscation + machine binding + integrity HMAC; document that no offline scheme is unbreakable; keep validation logic server-free per requirement. |
| Large-dataset UI slowdown | Medium (50k+ patients) | Performance | Indexed queries, pagination/LIMIT-OFFSET (or keyset pagination where appropriate), QTableView with QAbstractTableModel not QTableWidget with all rows, lazy loading of tabs, background loading for heavy widgets. |
| Migration failures on existing DB | Low-Medium | Data loss | Auto pre-migration backup; batch_alter_table for SQLite; migration tests in CI (upgrade/downgrade/upgrade cycle on test DB). |
| Installer missing a runtime DLL | Low | Install defect | CI builds on clean `windows-latest`, runs the built exe in a smoke step; dependency walker check via PyInstaller logs. |
| Unsaved data lost on auto-lock | Low | UX | Track form dirty state; present save/discard/cancel dialog before lock; periodic auto-save draft for prescriptions/notes where appropriate. |
| Double-click double-submits payments/invoices | Medium | Financial | All submit buttons disabled after first click (re-enabled only on failure); DB-level unique constraints where possible (invoice_number, payment uniqueness checks); transactional integrity. |

---

## 10. Requirements Traceability Matrix (Internal — Will Expand Each Phase)

This internal matrix will be expanded each phase. At Phase 1, I am recording a complete list of requirement groups from the master specification and mapping them to the phase that will deliver them.

| # | Requirement Group | Phase | Tests |
|---|-------------------|-------|-------|
| R1 | Product identity, name, icon, branding | 2, 19 | UI/visual, installer |
| R2 | English default, Bangla/Unicode entry | 2 (font cascade), 8, 14 | Unicode tests, Bangla rendering |
| R3 | BDT/৳ everywhere, Decimal/paisa | 2 (money module), 9 | Calculation tests |
| R4 | No paid runtime cloud/API/SDK | All | License audit 20 |
| R5 | Local relational DB (SQLite), normalized, migrations | 2 | Migration tests |
| R6 | First-run setup wizard | 3 | Setup flow tests |
| R7 | Secure auth (bcrypt), session, auto-lock | 3, 15 | Auth tests, lock tests |
| R8 | Granular RBAC at service layer | 3, 9, 15 | Permission bypass tests |
| R9 | Main shell (header, collapsible sidebar, nav sections) | 2 | UI tests |
| R10 | Design system (palette/typography/spacing/radius/shadows/icons/forms/tables/cards/modals/notifications/states) | 2, 4, 18 | UI audit |
| R11 | Multi-resolution, HiDPI responsiveness, DPI scaling | 2, 18 | Size/DPI audit |
| R12 | Dashboard real, RBAC-aware | 4 | Dashboard integration tests |
| R13 | Patients unlimited, filters, search | 5 | Pagination/search perf tests |
| R14 | Patient profile (all tabs, history) | 5, 6, 7, 8, 9 | Profile flow tests |
| R15 | Dental chart (adult/pediatric, historical per visit) | 6 | Chart state tests |
| R16 | Clinical timeline | 6 | Timeline aggregation tests |
| R17 | Appointments (status, double-book, reschedule) | 7 | Appointment logic tests |
| R18 | Queue (waiting/in-progress/completed, reorder) | 7 | Queue state-machine tests |
| R19 | Treatment catalog + patient records (price snapshot) | 8 | Catalog price immutability tests |
| R20 | Prescription editor (multi-medicine, structured sections) | 8 | Prescription tests |
| R21 | Flagship prescription print (header, signature, paper sizes, Bangla, PDF) | 8, 14 | Print render tests |
| R22 | Invoices (line items, totals, paid/partial/unpaid, immutable) | 9 | Invoice lifecycle tests |
| R23 | Invoice printing (A4/A5/thermal, PDF, Windows printers) | 9, 14 | Print tests |
| R24 | Payments (methods including bKash/Nagad/Rocket/Upay, history) | 9 | Payment tests |
| R25 | Financial permission deep enforcement | 3, 9, 15 | Negative-permission tests |
| R26 | Inventory (stock, movements, low/expiring alerts) | 10 | Inventory tests |
| R27 | Accounting (income/expense, categories, reports) | 10 | Accounting reconciliation tests |
| R28 | Staff & Users (employees vs logins) | 3, 11 | Staff/user tests |
| R29 | Backup & Restore (manual/scheduled, pre-restore backup, integrity) | 13 | Backup/restore tests |
| R30 | Settings comprehensive (all listed areas) | 11 | Settings persistence tests |
| R31 | Destructive actions (typed confirmation, safety backup) | 11, 15 | Destructive-action tests |
| R32 | Global search (permission-aware, fast) | 11 | Search tests |
| R33 | Notification center (actionable, permission-aware) | 11 | Notification tests |
| R34 | Attachments (safe copy, preview, backup) | 12 | Attachment tests |
| R35 | About (Shohan Khan, helloiamshohan@gmail.com) | 2 | Content test |
| R36 | Audit log (events listed, protected, non-editable) | 12, 15 | Audit tests |
| R37 | Keyboard shortcuts, tab nav, focus | 2, 18 | Keyboard audit |
| R38 | Print subsystem (profiles, preview, multi-page, Unicode) | 14 | Print render regression tests |
| R39 | Error/empty/loading/locked/permission/corruption states | 2, 4, 15 | UI state audit |
| R40 | Performance (indexing, pagination, large data) | 16 | Stress tests |
| R41 | Transactions, atomicity, duplicate-submit protection | 2, 16 | Transaction tests |
| R42 | Logging (rotating, redaction, no secrets) | 2 | Log inspection tests |
| R43 | Activation (offline, obfuscated, hardware-bound) | 3, 15 | Activation tests |
| R44 | Windows installer (genuine, Start Menu, icon, uninstall data preservation) | 19 | Clean-install tests |
| R45 | GitHub Actions CI + GitHub Releases / dist fallback | 2, 19, 22 | CI verification |
| R46 | Dependency & license audit | 20 | License report |
| R47 | Comprehensive automated tests | 17 | Coverage + pass |
| R48 | Stress / large dataset tests | 16 | Stress perf report |
| R49 | Systematic UI validation | 18 | UI audit checklist |
| R50 | Clean-machine install test | 19, 21 | Clean VM install script |
| R51 | Final independent re-audit | 21 | Audit checklist |
| R52 | Final release artifact (genuine, tested) | 21, 22 | Release validation |
| R53 | Strong relational integrity, soft-delete for important records | All | FK + soft-delete tests |
| R54 | No artificial limits (patients, history, etc.) | 5, 16 | Large-dataset tests |
| R55 | Safe error handling, no stack traces, recovery paths | 2, 15 | Error state tests |

---

## 11. Acceptance Criteria for Phase 1

- [x] Repository inspected.
- [x] Environment inspected and documented.
- [x] All major technology choices made and justified (Python 3.11, PySide6, SQLite, SQLAlchemy 2, Alembic, bcrypt, Qt printing, Pillow, Pydantic, PyInstaller, NSIS, pytest, Ruff, GitHub Actions).
- [x] No paid/cloud runtime dependencies; all third-party licenses compatible with commercial redistribution.
- [x] Layered architecture defined (UI → Services (RBAC) → Repositories → SQLite), service-layer permission enforcement strategy documented.
- [x] Data model entities defined (37 tables) with relationships and key indexes.
- [x] RBAC permissions and default roles outlined.
- [x] Design system foundations (palette, typography, spacing, radius, elevation, shell dimensions) documented.
- [x] Backup/restore architecture documented with safety backup and checksum validation.
- [x] Print architecture documented with paper profiles and renderers.
- [x] Activation approach documented (obfuscated HMAC-SHA256, machine binding, honest security note).
- [x] Phased implementation plan defined (22 phases) with exit criteria.
- [x] Risks identified with mitigations.
- [x] Requirements traceability matrix started.
- [x] Phase 1 report written to `docs/PHASE1_PLAN.md`.

**Phase 1 status: Complete. Awaiting user's "Continue" to begin Phase 2 (Project Foundation & App Shell).**
