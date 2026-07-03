---
phase: 04-modality-shift-approval-srs-v1-2
plan: 01
subsystem: database
tags: [django, models, migration, orm, mssql, policy, test-fixtures]

# Dependency graph
requires:
  - phase: 03
    provides: "Session.declared_modality override field, get_policy/SystemSetting register, Role.DEAN + User.department routing, campus Room/Building/Floor, AcademicTerm/Schedule/Session"
provides:
  - "ModalityShiftStatus enum (pending/approved/rejected/withdrawn/denied)"
  - "ModalityShiftRequest model (atomic multi-schedule ticket over a date window)"
  - "ModalityShiftItem model (per-schedule preferred_room, assigned_room, time-move slot)"
  - "modality_shift_lead_days policy default (2) in FLUXTRACK_POLICY"
  - "scheduling/migrations/0003_modality_shift_request.py"
  - "make_shift_fixture() reusable test-support builder"
affects: [04-02, 04-03, 04-04, 04-05, 04-06, 04-07, 04-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modality-shift ticket = one ModalityShiftRequest + N ModalityShiftItem rows (D-19 atomic multi-schedule)"
    - "assigned_room is a server-written reservation, never a client field (T-04-05a mitigation, D-18)"
    - "Shared plain-helper test fixture (make_shift_fixture) imported across app test modules"

key-files:
  created:
    - "scheduling/migrations/0003_modality_shift_request.py"
    - "scheduling/test_support.py"
  modified:
    - "config/settings.py"
    - "scheduling/models.py"
    - "scheduling/tests.py"

key-decisions:
  - "Migration file renamed from Django auto-name to plan artifact name 0003_modality_shift_request.py via unapply/rename/re-apply"
  - "Competitor occupant modeled as a second F2F Session (distinct faculty) in room A, avoiding a D-17 self-double-book"

patterns-established:
  - "ModalityShiftStatus mirrors the SessionStatus TextChoices shape; DENIED is the terminal no-room outcome (D-07 REVISED), REJECTED is the Dean's explicit no"
  - "FK audit shape (PROTECT requester, SET_NULL routed/decided actors + decided_at) copied from Session.modality_changed_by/_at"

requirements-completed: [MOD-01]

coverage:
  - id: D1
    description: "modality_shift_lead_days policy default resolves to 2 and is SystemSetting-overridable (D-02/D-03)"
    requirement: "MOD-01"
    verification:
      - kind: unit
        ref: "python -c get_policy('modality_shift_lead_days')==2 (plan Task 1 inline assertion) -> 'lead_days ok'"
        status: pass
    human_judgment: false
  - id: D2
    description: "ModalityShiftRequest + ModalityShiftItem + ModalityShiftStatus models with a five-state lifecycle and clean additive migration"
    requirement: "MOD-01"
    verification:
      - kind: unit
        ref: "py -3.12 manage.py makemigrations scheduling --check --dry-run (no changes) + ModalityShiftStatus.values assertion -> 'models ok'"
        status: pass
      - kind: integration
        ref: "py -3.12 manage.py migrate (0003_modality_shift_request applies cleanly on MSSQL LocalDB)"
        status: pass
    human_judgment: false
  - id: D3
    description: "make_shift_fixture() seeds a valid routing-correct Phase-4 object graph reusable by ops/scheduling/web tests"
    requirement: "MOD-01"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#FixtureSmokeTests.test_fixture_wires_dean_and_same_department_faculty"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-07-03
status: complete
---

# Phase 4 Plan 01: Modality-Shift Data Foundation Summary

**ModalityShiftRequest + ModalityShiftItem models (five-state lifecycle), the modality_shift_lead_days=2 policy default, migration 0003, and a shared make_shift_fixture() test builder — the schema every later Phase-4 plan reads and writes.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-03
- **Tasks:** 3
- **Files modified:** 5 (3 created/modified source + migration + test)

## Accomplishments
- Added `modality_shift_lead_days: 2` to `FLUXTRACK_POLICY`, resolvable only through `get_policy()` and SystemSetting-overridable (D-02/D-03) — no literal lead-day constant elsewhere.
- Added `ModalityShiftStatus` (pending/approved/rejected/withdrawn/denied), `ModalityShiftRequest` (atomic multi-schedule ticket over a date window, D-19/D-01), and `ModalityShiftItem` (per-schedule preferred_room + server-written assigned_room + optional time-move slot, D-05/D-06/D-16/D-18) to `scheduling/models.py`; no `Session.modality` column added (declared_modality is the override).
- Generated and applied `scheduling/migrations/0003_modality_shift_request.py`; `makemigrations --check` clean.
- Created `scheduling/test_support.py` with `make_shift_fixture()` and a green `FixtureSmokeTests` smoke test; full suite (128 tests) still green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add modality_shift_lead_days policy default** - `e654431` (feat)
2. **Task 2: Add ModalityShiftRequest + ModalityShiftItem models + migration** - `55c8520` (feat)
3. **Task 3: Add shared make_shift_fixture test-support builder** - `7a99dfe` (test)

## Files Created/Modified
- `config/settings.py` - Added `modality_shift_lead_days: 2` to FLUXTRACK_POLICY.
- `scheduling/models.py` - Added ModalityShiftStatus, ModalityShiftRequest, ModalityShiftItem.
- `scheduling/migrations/0003_modality_shift_request.py` - Additive migration creating the two models.
- `scheduling/test_support.py` - `make_shift_fixture()` reusable object-graph builder.
- `scheduling/tests.py` - `FixtureSmokeTests` proving fixture routing wiring.

## Decisions Made
- **Migration filename honored the plan artifact name.** Django auto-named the migration `0003_modalityshiftrequest_modalityshiftitem.py`; unapplied it, renamed to the plan's `0003_modality_shift_request.py`, and re-applied so the recorded migration name matches the file. No downstream migration depended on it, so this was safe.
- **Competitor occupant is a second F2F Session (distinct faculty) in room A** at the same slot, rather than an ops.Booking — gives availability tests a real session occupant while avoiding a D-17 faculty self-double-book. An ops.Booking-based competitor remains an equally valid alternative for booking-specific conflict cases.

## Deviations from Plan

None - plan executed exactly as written. (The migration-file rename is the plan's stated artifact name, not a deviation.)

## Issues Encountered
None. The only extra step was the unapply/rename/re-apply cycle to match the plan's migration filename; the DB history is consistent under the renamed migration.

## Threat Model Notes
- **T-04-01a (Elevation):** `ModalityShiftRequest` carries `requester` + `department` so later plans (04-04/04-05/04-08) can enforce object-level ownership and department gates. Fields present as designed.
- **T-04-05a (Tampering):** `ModalityShiftItem.assigned_room` is a nullable server-written column (never derived from client input); request-aware availability (04-03) will read it (D-18). No new threat surface introduced.
- No new external packages installed (T-04-SC accept holds); migration is additive only.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Downstream plans can import `ModalityShiftRequest`, `ModalityShiftItem`, `ModalityShiftStatus`, the `modality_shift_lead_days` policy key, and `make_shift_fixture()` without further schema work.
- 04-02+ (lead-time gate, availability, services, web) build directly on this schema.

## Self-Check: PASSED

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-03*
