# Dentiva Pro

**Offline Dental Clinic Management for Bangladesh**

Dentiva Pro is a professional, fully-offline Windows desktop application designed
for dental clinics in Bangladesh. It supports patient records, dental charting,
visits, appointments, queue management, treatments, prescriptions, invoices,
payments (Cash / bKash / Nagad / Rocket / Upay / Card / Bank), inventory,
accounting, staff & user management with granular RBAC, backup & restore,
and flagship-quality prescription/invoice printing (A4 / A5 / thermal).

* Currency: **BDT (৳)** (all amounts stored as integer paisa)
* Language: English UI with full Bangla/Unicode input support everywhere
* Activation code (one-time offline): **1516591935015165**
* Author: Shohan Khan — <helloiamshohan@gmail.com>

## Status

This repository is being built in phased, gated milestones. See
[`docs/PHASE1_PLAN.md`](docs/PHASE1_PLAN.md) for the architecture and plan.

## Developing

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
python scripts/build_icon.py
python -m dentiva
```

### Testing

```bash
ruff check dentiva tests
mypy dentiva
pytest
```

### Project layout

```
dentiva/             Application source
  app.py             QApplication bootstrap
  bootstrap.py       Paths / logging / DB / migration bootstrap
  core/              Money, dates, permissions, errors, validators
  db/                SQLAlchemy engine, models, Alembic migrations
  auth/              Password hashing, session
  activation/        Offline HMAC-based activation
  ui/                PySide6 UI (theme, widgets, dialogs, views, main window)
  services/          Business logic & RBAC boundary (built in later phases)
assets/              Icon, fonts, themes, images
scripts/             Build utilities (icon build, PyInstaller spec, dist helpers)
installer/           NSIS installer script
tests/               Unit / integration / UI / performance tests
docs/                Architecture, security, RBAC, data model documentation
.github/workflows/   GitHub Actions CI
```

## License

Dentiva Pro is proprietary software (© Shohan Khan). All rights reserved.
Third-party open-source components used by Dentiva Pro are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
