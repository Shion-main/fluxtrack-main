---
phase: 04-modality-shift-approval-srs-v1-2
plan: 06
subsystem: scheduling
tags: [django, materialize, modality-shift, mssql, job-01, materialize_sessions]

# Dependency graph
requires:
  - phase: 04-05
    provides: "apply_approval writes ModalityShiftItem.assigned_room reservation (D-18) and APPROVED request state the hook reads"
  - phase: 04-03
    provides: "request-aware availability keeps the reserved room free until its future session exists"
  - phase: 02
    provides: "release_room() single-source-of-truth room release; notify() single write path"
provides:
  - "JOB-01 materialize_sessions honors approved modality-shift requests: future in-window sessions are born released (->Online) or born in the reserved room (->F2F/Blended), incl. time-moves"
  - "_apply_approved_shift(session, schedule, date) born-released/born-assigned hook"
  - "Defensive no-room guard: keep schedule.room + notify IFO, never crash the unattended job"
affects: [04-07, 04-08, phase-5-read-surface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "was_created-only hook: approval-consequence applied at session birth, idempotent by construction"
    - "APPLY the reservation, do not re-resolve (D-18): materialize reads item.assigned_room rather than re-running availability"
    - "list()-materialize approved candidate items before the write (pyodbc HY010 guard)"

key-files:
  created: []
  modified:
    - "scheduling/management/commands/materialize_sessions.py"
    - "scheduling/tests.py"

key-decisions:
  - "Materialize APPLIES item.assigned_room (never re-resolves) per D-18; the no-room path is a defensive guard only"
  - "Latest decision wins on the rare overlap: candidate approved items ordered by -request__decided_at"
  - "Defensive guard still stamps declared_modality/modality_changed_* for the target while keeping the original room"

patterns-established:
  - "Born-released/born-assigned: the JOB-01 hook fires only on get_or_create was_created, so re-running materialize is idempotent with no re-processing"

requirements-completed: [MOD-03, MOD-04]

coverage:
  - id: D1
    description: "Future in-window session materialized after an approved ->Online shift is born released (declared_modality=Online + room_released_at stamped, room FK never nulled); out-of-window future dates untouched; re-run idempotent"
    requirement: "MOD-03"
    verification:
      - kind: integration
        ref: "scheduling/tests.py::BornReleasedTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Future in-window ->F2F/Blended session is born in item.assigned_room (reservation applied, not re-resolved), incl. bundled time-move at the new slot"
    requirement: "MOD-04"
    verification:
      - kind: integration
        ref: "scheduling/tests.py::BornAssignedTests::test_future_in_window_session_born_in_reserved_room, ::test_time_move_born_at_new_slot"
        status: pass
    human_judgment: false
  - id: D3
    description: "Defensive no-room guard: an approved ->F2F item with no reserved room keeps schedule.room + notifies IFO informationally and never raises inside the unattended job (Pitfall 2/A1)"
    requirement: "MOD-04"
    verification:
      - kind: integration
        ref: "scheduling/tests.py::BornAssignedTests::test_no_assigned_room_falls_back_to_schedule_room_and_notifies_ifo"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-03
status: complete
---

# Phase 4 Plan 06: Materialize born-released/born-assigned hook Summary

**JOB-01 `materialize_sessions` now honors approved modality-shift requests — future in-window sessions are born released (->Online via `release_room`) or born in the reserved room (->F2F/Blended with any time-move), closing the out-of-horizon future-session gap (Pitfall 1) with a defensive no-room guard that never crashes the unattended job.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-03T16:21:04Z
- **Completed:** 2026-07-03T16:24:57Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_apply_approved_shift(session, schedule, date)` hook added to `materialize_sessions.py`, called only on `get_or_create` `was_created` — idempotent by construction.
- ->Online born-released path: sets `declared_modality=Online` + `modality_changed_at`/`_by` from the decision, then `release_room()` stamps `room_released_at` (room FK never nulled). Closes Pitfall 1 for MOD-03/D-04.
- ->F2F/Blended born-assigned path: applies the item's already-reserved `assigned_room` (D-18 — never re-resolves), rewrites `scheduled_start`/`_end` for a bundled time-move.
- Defensive guard (Pitfall 2/A1): a missing `assigned_room` keeps the session in its `schedule.room` and notifies IFO informationally via `notify()` — the job never raises.
- Candidate approved items `list()`-materialized before the write (MSSQL HY010 guard); full `scheduling` suite green (86 tests).

## Task Commits

Each task was committed atomically:

1. **Task 1: Born-released hook (->Online)** — `fc353fb` (test, RED) → `d30a7d5` (feat, GREEN)
2. **Task 2: Born-assigned hook (->F2F, defensive guard)** — `033ed83` (test)

_Note: the ->F2F/Blended born-assigned branch was implemented cohesively inside `_apply_approved_shift` during Task 1's GREEN step (single helper), so Task 2's `BornAssignedTests` passed on first run against the already-present branch — see TDD Gate Compliance below._

## Files Created/Modified
- `scheduling/management/commands/materialize_sessions.py` — added `_apply_approved_shift()` hook + wired it into the `get_or_create` loop (fires on `was_created`).
- `scheduling/tests.py` — added `BornReleasedTests` (3) and `BornAssignedTests` (3) plus `_approved_request`/`_materialize_future` helpers.

## Decisions Made
- Materialize APPLIES the reservation (`item.assigned_room`) rather than re-resolving availability (D-18); the no-room path is a defensive guard only, unreachable in Phase 4 scope by design.
- Latest decision wins on the rare schedule/window overlap: candidate items ordered by `-request__decided_at`.
- The defensive guard still stamps `declared_modality`/`modality_changed_*` for the target modality while keeping the original `schedule.room`, so the born session reflects the shift intent even when no room was reserved.

## Deviations from Plan

None — plan executed as written. One structural note (not a deviation in behavior): Task 2's implementation was folded into the single `_apply_approved_shift` helper written in Task 1 rather than added as a separate `feat` commit, because the ->Online and ->F2F branches share one lookup/dispatch. Behavior and tests match the plan exactly.

## Issues Encountered
- Initial draft passed `when=` to `release_room()`; corrected to the actual keyword `now=` before the first test run (caught during implementation, no failing commit).

## TDD Gate Compliance
- Task 1 followed a clean RED → GREEN cycle: `fc353fb` (failing `BornReleasedTests`) → `d30a7d5` (implementation, tests green).
- Task 2's `BornAssignedTests` (`033ed83`) were GREEN on first run because the ->F2F/Blended branch already lived in the shared `_apply_approved_shift` helper from Task 1. No separate `feat` commit exists for Task 2's source. This is a cohesive-helper trade-off, not a skipped implementation — all three born-assigned behaviors (reserved room, time-move, defensive guard) are covered by passing tests.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- JOB-01 now fully honors approved shifts for both current and future (out-of-horizon) sessions; MOD-03/MOD-04 born-state closed.
- Ready for 04-07/04-08 (web surfaces / SRS regeneration). No blockers.

## Self-Check: PASSED

- FOUND: scheduling/management/commands/materialize_sessions.py (`_apply_approved_shift`)
- FOUND: scheduling/tests.py (BornReleasedTests, BornAssignedTests)
- FOUND commit: fc353fb (test RED)
- FOUND commit: d30a7d5 (feat GREEN)
- FOUND commit: 033ed83 (test)

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-03*
