# Release Checklist — Dentiva Pro v1.0.0

Run through this checklist before cutting a release tag.

## Source QA (Linux or Windows dev box)

- [ ] `ruff check dentiva tests scripts` — all checks passed.
- [ ] `mypy dentiva` — 0 new errors (13 pre-existing Qt union-attr warnings acceptable).
- [ ] `pytest` — all 166 tests pass on a clean checkout.
- [ ] `python -m dentiva` launches, first-run setup wizard appears on a fresh
      data dir (set `DENTIVA_DATA_DIR` to a temp folder to verify).
- [ ] Activation with code `1516591935015165` succeeds; relaunch shows logged-out
      state, not the wizard.
- [ ] Global search (Ctrl+K) returns patients, appointments, invoices,
      prescriptions, inventory, treatments, attachments.
- [ ] Header bell generates notifications (schedule a 10-minute-out
      appointment, wait up to 60 s or restart, verify "Upcoming appointment"
      appears).
- [ ] Create backup, restore it in a temp data dir, verify patients come back.
- [ ] Attach a file to a patient, reopen patient profile, double-click to
      open the file, delete one, verify the disk file is removed.
- [ ] Create + post an invoice, record a payment, verify totals/due.
- [ ] Prescription editor: add 2 medicines, print preview PDF for A4 / A5 /
      thermal (where available).
- [ ] Auto-lock engages after the configured interval; password unlocks.
- [ ] Role editor: create a receptionist role without financial permissions,
      verify Invoices/Payments/Accounting nav items are disabled and service
      calls raise PermissionDenied.

## Clean-machine Windows install

- [ ] On a clean Windows 10/11 VM (no Python preinstalled):
  - [ ] Run `DentivaPro-Setup-v1.0.0.exe`.
  - [ ] Accept defaults (Program Files\DentivaPro), verify Start Menu
        "Dentiva Pro" shortcut + desktop shortcut are created.
  - [ ] Launch Dentiva Pro; first-run wizard appears.
  - [ ] Complete setup with a sample clinic and admin user.
  - [ ] Activate with `1516591935015165`.
  - [ ] Create a patient, an appointment, an invoice, an attachment.
  - [ ] Trigger a backup → save to `%USERPROFILE%\Documents\DentivaBackups`.
  - [ ] Close app; restart; verify data persists.
  - [ ] Change display scaling to 125% / 150%; relaunch, verify no clipping.
  - [ ] Uninstall from Add/Remove Programs; verify app folder is removed but
        `%APPDATA%\DentivaPro` (database, attachments, activation) is kept.

## DPI / UI audit

- [ ] 100% (96 DPI): all pages render without clipping; tables sized correctly.
- [ ] 125%: fonts/tables scale; no clipped buttons in dialogs.
- [ ] 150%: no overflow on Settings/Backup/Attachments forms.
- [ ] Bangla input: typing Bangla into patient address/allergies renders
      correctly and is persisted.
- [ ] Thermal print preview (80 mm): fits page width without wrapping.

## Build pipeline

- [ ] Push tag `v1.0.0` → GitHub Actions release workflow runs:
  - Ruff/mypy/pytest pass on both `ubuntu-latest` and `windows-latest`.
  - Icon build step completes.
  - PyInstaller onedir build completes without errors.
  - NSIS compiles; `DentivaPro-Setup-v1.0.0.exe` is uploaded to the Release.
- [ ] If GitHub Release upload fails for any reason, copy the installer
      from the workflow artifact into `dist/DentivaPro-Setup-v1.0.0.exe`
      in the repo and push it (the `dist/` folder is the documented
      fallback).

## Post-release

- [ ] Tag `v1.0.0` is annotated with release notes from CHANGELOG.md.
- [ ] Release page on GitHub links to this checklist and README.
- [ ] README and CHANGELOG committed to `main` (after PR merge).
