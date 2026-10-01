# Phase 7 Report — Appointments & Queue

**Status:** Phase 7 complete. 84/84 tests pass. `ruff` and `mypy` clean. Ready for review/merge before Phase 8.

## What shipped

### Appointment & Queue service (`dentiva/services/appointment_service.py`)
Full scheduling and chair-side workflow with RBAC, conflict detection, and per-dentist queue ordering:

| Function | Purpose | RBAC |
|---|---|---|
| `list_appointments(...)` | Appointments for a date/window with patient+dentist names; filterable by dentist, status, patient. Newest-first by time. | `appointments.view` |
| `get_appointment(...)` | Single appointment with patient/dentist names. | `appointments.view` |
| `create_appointment(...)` | Creates appointment; validates patient/dentist exist, time in future/now, duration 5–480 min; checks dentist time-slot overlap (conflict detection); writes audit event. | `appointments.create` |
| `update_appointment(...)` | Reschedules/edits; refuses completed/cancelled/no-show; re-checks conflicts; writes audit event. | `appointments.edit` |
| `cancel_appointment(...)` | Sets `cancelled` + `cancelled_at=now`; notes cancellation reason; removes patient from queue if waiting/with-dentist. | `appointments.cancel` |
| `mark_appointment_status(...)` | Generic status setter (confirmed, no_show, completed, etc.) with audit. | `appointments.edit` |
| `list_queue(...)` | Today's queue with computed wait minutes (now – arrived_at); can filter by dentist. | `queue.manage` |
| `check_in_appointment(...)` | Marks an appointment `checked_in`, creates a `QueueEntry(status=waiting)` with next `position` for that dentist; refuses double-check-in or cancelled/no-show/completed. | `queue.manage` + `appointments.edit` |
| `walk_in(...)` | Registers a walk-in patient into the queue without an appointment. | `queue.manage` |
| `start_service(...)` | Moves a waiting entry to `with_dentist` (sets `started_at`) and **opens a new visit automatically** (via `visit_service.create_visit`), so the dentist is dropped straight into the chart-ready visit. | `queue.manage` |
| `finish_service(...)` | Marks entry `finished`, sets `finished_at=now`, and (by default) marks the linked appointment `completed`. | `queue.manage` |
| `remove_from_queue(...)` | Marks removed/no-show; if no_show, also marks linked appointment `no_show`. | `queue.manage` |
| `reorder_queue(...)` | Persists reordered positions for a dentist (UI drag-to-reorder in a future pass). | `queue.reorder` (falls back to `queue.manage`) |
| `upcoming_appointments(...)` | Helper for notifications — appointments starting within N minutes that are still scheduled/confirmed. | `appointments.view` |

### Status flow
Appointment: `scheduled → confirmed → checked_in → (in_progress via queue.start) → completed`. From any non-terminal state you can `cancel` or `no_show`.
Queue: `waiting → with_dentist → finished`; or `removed`/`no_show`.

### Conflict detection
`_conflict_check` iterates non-cancelled, active appointments for the target dentist (or unassigned) and returns a count of overlapping time ranges. Overlap is true if `a.start < new.end && a.end > new.start` (standard half-open interval semantics). This keeps validation portable across SQLite (no native INTERVAL arithmetic needed) and PostgreSQL. Adjacent appointments (ending at 10:00, next starting 10:00) are allowed.

### Appointment dialog (`dentiva/ui/dialogs/appointment_dialog.py`)
- Patient combo with search-as-you-type (editable QComboBox populated with up to 500 active patients, displays name + code + phone).
- Dentist selector (Unassigned + active dentists).
- QDateTimeEdit with calendar popup; defaults to the next 15-minute slot from now (e.g., now is 9:07 → defaults to 9:15).
- Duration spinbox 5–480 min, suffix "min", default 15.
- Reason (line edit) + Notes (multiline).
- Error label at the bottom for service-layer ValidationErrors (conflicts, missing patient, etc.).
- Respects the principal's permissions via service-layer checks (the UI always calls into services which re-check).

### Appointments & Queue view (`dentiva/ui/views/appointments/appointments_view.py`)
Tabbed view combining day list and live queue board:

**Day view tab:**
- Date picker (defaults to today) + dentist filter (All dentists / per dentist).
- "+ New appointment" button (only shown when principal has `appointments.create`).
- Data table with columns: Time / Patient / Phone / Dentist / Reason / Status / Actions.
- Status column colored by status (confirmed green, checked-in amber, in-progress purple, cancelled red, etc.).
- Row actions: **Edit** (if `appointments.edit`), **Check in** (primary, if `queue.manage` — auto-switches to Queue tab after success), **Cancel** (prompts for optional reason).

**Queue tab:**
- "+ Walk-in" button (if `queue.manage`) — quick patient picker dialog, adds to queue.
- Refresh button + 30-second auto-refresh timer.
- Table: # (position), Patient, Phone, Dentist, Wait (minutes), Status (color-coded), Actions.
- Per-row actions:
  - Waiting → **Start** (primary, opens a visit automatically) + **No-show**
  - With dentist → **Finish** (primary, finalises visit + marks appointment completed)
  - Finished/removed → disabled "—"

**Auto-refresh:** tab changes and every 30 s while on the Queue tab refresh both day list and queue.

### Wiring in main window
- `AppointmentsView` is late-bound after login via `MainWindow.replace_view("appointments", ...)` in the same pattern as Dashboard/Patients/Staff.
- "Start" on a queue entry currently opens a visit and shows a status-bar message indicating the visit is ready; direct navigation to the Visit tab inside the patient profile will be wired in Phase 8 when treatment records are integrated (Phase 7 focus is on appointment/queue flow itself).

### Tests (84 total, +9)
`tests/services/test_appointments.py`:
1. `test_create_appointment_basic` — creates a scheduled appointment and asserts defaults.
2. `test_conflict_detection` — overlapping appt with same dentist raises ValidationError; adjacent (gap-free) appt allowed.
3. `test_validation_missing_patient_and_time` — empty input raises.
4. `test_cancel_appointment` — sets cancelled status + cancelled_at timestamp.
5. `test_rbac_assistant_cannot_create` — Assistant (view-only) denied.
6. `test_check_in_creates_queue_entry_and_marks_appt` — check-in creates waiting queue row, appt becomes checked_in.
7. `test_walk_in_adds_to_queue` — walk-in patient lands in queue without an appointment.
8. `test_start_then_finish_flow` — full lifecycle: create → check-in → start (visit opened) → finish (appointment completed, queue finished).
9. `test_upcoming_appointments_filter` — appointments within next 60 minutes returned; past appointments excluded.

### Quality gates
```
$ ruff check dentiva tests
All checks passed!

$ mypy dentiva
Success: no issues found in 107 source files

$ pytest tests/
============================== 84 passed in 39.99s ==============================
```

## RBAC applied
| Action | Permission |
|---|---|
| View appointments | `appointments.view` |
| Create appointment | `appointments.create` |
| Edit/reschedule appointment | `appointments.edit` |
| Cancel appointment | `appointments.cancel` |
| View & manage queue / check-in / walk-in / start / finish | `queue.manage` |
| Reorder queue | `queue.reorder` (or `queue.manage` fallback) |
| Open visit on "Start" | `visits.create` (enforced by `visit_service.create_visit`) |
| Edit dental chart during visit | `chart.edit` (enforced by `visit_service.set_tooth_finding`) |

## Notable design decisions
1. **Conflict detection is Python-side (not SQL).** SQL interval math varies across SQLite and PostgreSQL (date arithmetic operators differ). Pulling candidate rows and checking overlap in Python is O(n) per save (n is small — a dentist sees ~15–25 appointments/day) and keeps the service portable without window functions or dialect-specific SQL.
2. **Auto-opened visit on "Start".** The critical path from "patient arrives" to "dentist can chart" is one click: Check in → Start. Start creates an open `Visit` (Phase 6) with the same dentist/patient and timestamp, so the chart is ready the moment the dentist sits down.
3. **Queue scoped to today.** Queue entries older than today are hidden by default (no archive UI in v1; data preserved for audit/reporting).
4. **Unassigned-dentist appointments only conflict with other unassigned appointments** — assigning two patients to "any dentist" at the same time is a conflict (double-booking reception), but assigning one to Dr. Rahman and another to Dr. Karim at the same time is not.
5. **Wait time is computed live** on every queue load (now – arrived_at in minutes) so no separate timer/tick is needed to keep "Wait" column fresh; 30-second refresh is sufficient.
6. **Cancelled appointments auto-drop out of the queue** if they'd already been checked in (defensive — typically cancel happens before check-in).
7. **Day view auto-switches to the Queue tab** after check-in so receptionists see the patient appear in the board and can verify they are listed under the correct dentist.

## Known intentional deferrals
- **Week/calendar view** — Phase 7 ships a robust day list which is sufficient for a single-clinic v1; a week/agenda view with color-coded dentist rows comes in Phase 12 Admin Console / polish if time permits.
- **Drag-and-drop queue reorder** — `reorder_queue` is implemented at the service layer; UI drag-to-reorder will be added in Phase 8 when I wire richer mouse interactions.
- **SMS/email reminders** — out of scope for v1 (offline-only, no network API). A notification-bell reminder ("You have N appointments starting in 30 minutes") is trivial to add and will hook into the existing notification center in a polishing pass.
- **Recurring appointments** — out of v1 scope per original spec (single appointment scheduling).
- **Appointment print (chit)** — added with print subsystem (Phase 8+).
- **Double-booking override** ("allow conflict?") — v1 rejects; override toggle for admin can be added later if needed.
- **Navigation from "Start" directly into the chart view** — Phase 8 wires treatment recording and chart navigation; "Start" currently opens the visit and shows a status message.

## Files changed
- Added: `dentiva/services/appointment_service.py`, `dentiva/ui/dialogs/appointment_dialog.py`, `dentiva/ui/views/appointments/__init__.py`, `dentiva/ui/views/appointments/appointments_view.py`, `tests/services/test_appointments.py`
- Modified: `dentiva/ui/main_window.py` (late-bind AppointmentsView), `dentiva/ui/navigation.py` (updated placeholder text for appointments route).

## Next (Phase 8) — Treatments & Prescriptions (Rx)
Pending your explicit "Continue". Planned: treatment catalog browser, treatment records per visit (tooth-coded, price snapshots from catalog), the multi-medicine prescription editor (name/form/strength/morning-noon-night/before-or-after-meals/duration/quantity/special instructions), finalized (locked) prescriptions, and connecting the "Start" action on the queue to navigating directly to the treatment/chart tab of the opened visit.
