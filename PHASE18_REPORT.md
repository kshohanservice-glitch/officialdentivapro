# Phase 18 Report — Release readiness, docs, dist fallback, clean-machine checklist

## Goal
Final release-readiness pass: changelog, release checklist, local build helper
script, and a documented `dist/` fallback so the installer is always available
even if the GitHub Release upload step cannot run.

## What shipped (Phase 18)

### `CHANGELOG.md` (new)
Full v1.0.0 changelog covering all the system headlines: offline posture,
activation code `1516591935015165`, first-run setup, auto-lock, dental chart,
prescriptions, immutable invoices + multi-method payments, inventory, RBAC,
audit log, notifications/reminders, backup/restore (with safety copies),
global search, attachments, NSIS packaging, and GitHub Actions CI/CD.

### `docs/RELEASE_CHECKLIST.md` (new)
Step-by-step release checklist organized into three sections:

* **Source QA** — ruff/mypy/pytest gates; first-run wizard verification;
  activation flow; Ctrl+K search across all 7 entity types; notification
  generation; backup/restore round-trip; attachment upload/open/delete;
  invoice + payment totals; prescription PDF across A4/A5/thermal; auto-lock;
  RBAC enforcement for a receptionist role.
* **Clean-machine Windows install** — fresh Win10/11 VM, no Python: run
  installer, verify shortcuts, run wizard, activate, create records, back
  up, restart, scale to 125%/150%, uninstall (data preserved).
* **DPI/UI audit** — 100/125/150% scaling, Bangla input, thermal preview.
* **Build pipeline** — tag triggers the workflow; artifact upload to
  Releases; if upload fails, drop the installer into `dist/`.

### `scripts/build_release.py` (new)
Local build helper that mirrors the GitHub Actions release workflow for
developers who need to produce an installer without pushing a tag:

1. Runs `ruff check dentiva tests scripts`.
2. Runs `pytest` (skippable via `--skip-tests`).
3. Builds the icon (`scripts/build_icon.py`).
4. Runs PyInstaller via `scripts/dist_pyinstaller.spec`.
5. Compiles the NSIS installer via `makensis` (skipped with
   `--skip-installer`; helpful Linux dev boxes).
6. Moves the result to `dist/DentivaPro-Setup-<version>.exe`.

Defaults to version `1.0.0`; accepts a version argument.

### `dist/.gitkeep` (new)
Tracks the `dist/` folder in git so release artifacts can be committed
there as a documented fallback channel when GitHub Releases is unavailable
in a restricted network environment.

### Miscellaneous fixes
- Replaced a Unicode multiplication sign (`×`) with `x` in an icon script
  comment to satisfy ruff's ambiguous-character lint.

## Quality gates
| Tool | Result |
|------|--------|
| `pytest tests/` | **166 passed** |
| `ruff check dentiva/ tests/ scripts/` | All checks passed |
| `py_compile` of new scripts | OK |

## Files changed / added
* Added: `CHANGELOG.md`
* Added: `docs/RELEASE_CHECKLIST.md`
* Added: `scripts/build_release.py`
* Added: `dist/.gitkeep`
* Modified: `scripts/build_icon.py` (comment lint)

## Release status
Dentiva Pro v1.0.0 is feature-complete for the stated requirements. The
PR is held open for human review/merge per phase-gate rules; no self-merge.
Tagging `v1.0.0` after merge will trigger the release workflow to produce
`dist/DentivaPro-Setup-v1.0.0.exe` and publish it to GitHub Releases (with
the `dist/` folder as the documented fallback).
