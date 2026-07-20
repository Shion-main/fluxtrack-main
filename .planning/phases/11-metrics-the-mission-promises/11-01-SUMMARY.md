---
phase: 11-metrics-the-mission-promises
plan: 01
subsystem: api
tags: [reporting, aggregates, lateness, django, decimal, mssql-django]

# Dependency graph
requires:
  - phase: 06-reporting
    provides: scheduling/reporting.py aggregate layer (FacultyRow, Scorecard, _verified_map, _session_contribution)
  - phase: 09
    provides: SessionStatus.CANCELLED (excluded from lateness)
provides:
  - session_minutes_late(scheduled_start, actual_start) — the single grace-independent lateness formula (seconds)
  - _lateness_map(qs) — per-faculty Python fold {faculty_id: (total_late_seconds, late_count, held_with_start)}
  - _avg_minutes(total_seconds, held_with_start) — Decimal ROUND_HALF_UP average helper
  - FacultyRow.minutes_late_avg / late_sessions / chronic_late
  - Scorecard.minutes_late_avg / late_sessions / chronic_late
  - make_reporting_fixture _mk/add_session accept actual_start/actual_end
affects: [11-02 (HR per-session CSV imports session_minutes_late), 11 weekly-report/scorecard render surfaces]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-definition pure helper (session_minutes_late) reused by aggregate fold + HR CSV so the two cannot drift"
    - "Separate-query Python fold for lateness (mirrors _verified_map) — never Count(filter=Q), never ORM DurationField subtraction"
    - ">=1-whole-minute (secs>=60) chronic-frequency floor: sub-minute noise adds magnitude but never flags chronic"

key-files:
  created:
    - scheduling/tests_reporting_lateness.py
  modified:
    - scheduling/reporting.py
    - scheduling/test_support.py
    - scheduling/tests_reporting.py

key-decisions:
  - "Lateness is a single pure helper session_minutes_late returning SECONDS; callers render minutes (mirrors _session_contribution single-definition contract)"
  - "chronic-frequency count increments only at secs>=60 (>=1 whole minute); the average is over ALL held-with-start sessions regardless"
  - "chronic_late = held_with_start >= 5 and late_count/held_with_start >= 0.30 (D-02), computed in both faculty_attendance and faculty_scorecard from the shared _lateness_map"

patterns-established:
  - "Pattern: lateness fold does NOT copy _session_contribution's in-flight exclusion — an ACTIVE session with actual_start but NULL actual_end DOES contribute (lateness needs only the start)"
  - "Pattern: new defaulted dataclass fields appended after existing default fields so construction stays safe for all existing callers"

requirements-completed: [A3]

coverage:
  - id: D1
    description: "session_minutes_late pure formula — max(0, actual-scheduled) seconds, 0 for None start, floored at 0 for early arrival, grace-independent"
    requirement: A3
    verification:
      - kind: unit
        ref: "scheduling/tests_reporting_lateness.py#SessionMinutesLateFormulaTests (test_formula_max_zero / test_none_start_zero / test_early_arrival_not_negative)"
        status: pass
    human_judgment: false
  - id: D2
    description: "_lateness_map fold + FacultyRow/Scorecard fields: within-grace-late counts, sub-minute excluded from frequency, ABSENT/CANCELLED contribute nothing, in-flight ACTIVE contributes, chronic >=30% frequency with >=5-held floor"
    requirement: A3
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_lateness.py#LatenessAggregateTests (8 named edge tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "FacultyRow and Scorecard expose identical lateness fields for one faculty/range (single _lateness_map, no drift)"
    requirement: A3
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting.py#LatenessParityTests.test_facultyrow_and_scorecard_lateness_agree"
        status: pass
    human_judgment: false
  - id: D4
    description: "make_reporting_fixture _mk/add_session accept actual_start/actual_end without changing documented totals"
    requirement: A3
    verification:
      - kind: integration
        ref: "manage.py test scheduling.tests_reporting web.tests_hr (37 tests green, documented totals unchanged)"
        status: pass
    human_judgment: false

# Metrics
duration: 11min
completed: 2026-07-20
status: complete
---

# Phase 11 Plan 01: Lateness in the Aggregate Layer Summary

**One shared grace-independent `session_minutes_late` formula plus a per-faculty `_lateness_map` fold add avg-minutes-late, late-session count, and a chronic-late flag (>=30% of held, >=5-held floor) to both `FacultyRow` and `Scorecard` — redeeming the PROJECT.md promise that lateness is captured at the room level.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-20T08:32Z
- **Completed:** 2026-07-20T08:43Z
- **Tasks:** 3
- **Files modified:** 4 (1 created)

## Accomplishments
- `session_minutes_late(scheduled_start, actual_start)` — THE single lateness definition (seconds, grace-independent, `max(0, actual-scheduled)`, explicit 0 for a NULL start), the lateness sibling of `_session_contribution`. Plan 02's HR CSV will import this one function so the faculty aggregate and payroll export cannot disagree.
- `_lateness_map(qs)` — a separate Python fold over `.values_list().iterator()` (never `Count(filter=Q)`, never ORM DurationField subtraction) returning `{faculty_id: (total_late_seconds, late_count, held_with_start)}`. In-flight ACTIVE sessions contribute (unlike room-hours); the chronic-frequency count increments only at `secs >= 60`.
- Three defaulted fields (`minutes_late_avg` Decimal, `late_sessions` int, `chronic_late` bool) added to both `FacultyRow` and `Scorecard`, wired through `faculty_attendance` and `faculty_scorecard` from the shared `_lateness_map`; `chronic_late = held>=5 and late/held>=0.30`.
- `make_reporting_fixture` `_mk`/`add_session` now accept `actual_start`/`actual_end` (default None) so lateness tests seed known deltas without altering any documented total.
- New `scheduling/tests_reporting_lateness.py` with every mutation-resistant edge as a dedicated named test, plus a FacultyRow/Scorecard parity test in `tests_reporting.py`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Lateness formula helper, per-faculty fold, and dataclass fields** - `379b88f` (feat)
2. **Task 2: Extend make_reporting_fixture for known lateness deltas** - `c3365c4` (test)
3. **Task 3: Mutation-resistant lateness tests + FacultyRow/Scorecard field assertions** - `032df92` (test)

**Plan metadata:** committed separately with STATE.md/ROADMAP.md updates (docs: complete plan).

_Note: Task 3 is a TDD task; the implementation it pins was built in Task 1, so the tests pass on first run (GREEN) — see TDD Gate Compliance below._

## Files Created/Modified
- `scheduling/reporting.py` - Added `session_minutes_late`, `_lateness_map`, `_avg_minutes`; three lateness fields on `FacultyRow`/`Scorecard`; wired both builders.
- `scheduling/test_support.py` - `_mk`/`add_session` accept optional `actual_start`/`actual_end`.
- `scheduling/tests_reporting_lateness.py` - NEW: DB-free formula tests + DB-backed edge/chronic/parity tests.
- `scheduling/tests_reporting.py` - Added `LatenessParityTests` (FacultyRow == Scorecard lateness fields).

## Decisions Made
- None beyond what the plan and D-01/D-02 specify. The `>=60s` chronic-frequency floor, the held-with-start denominator for the average, and the in-flight-ACTIVE inclusion were all pre-locked by the plan and honored exactly.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

Plan Task 3 carries `tdd="true"`, but the plan deliberately sequences the *implementation* into Task 1 (feat `379b88f`) and the *mutation-resistant test authoring* into Task 3 (test `032df92`) — the tests pin already-built behavior rather than driving it RED-first. This is the plan's intended structure (Task 1's own `<verify>` gates the implementation against the existing suite; Task 3 adds the dedicated edge tests). No RED gate commit precedes the feat commit because the feature and its pinning tests are separate plan tasks. All Task 3 tests pass; no gate trip.

## Issues Encountered
None. All targeted module runs were green on first execution; no auto-fixes required.

## Verification
- `manage.py test scheduling.tests_reporting_lateness scheduling.tests_reporting scheduling.tests_reporting_rooms` — 131 tests, all green.
- No `grace_minutes`, `past_grace`, or ORM DurationField subtraction in the new lateness code.
- Targeted module runs only (not a full suite), so `FluxTrack_SRS.docx` was not regenerated — confirmed untouched in git status.

## User Setup Required
None - no external service configuration required. No schema change, no migration.

## Next Phase Readiness
- Plan 02 (HR per-session lateness CSV) can now `from scheduling.reporting import session_minutes_late` — the single shared definition is in place.
- The weekly-report render layer (`scheduling/report_render.py`) and scorecard surface can read the three new `FacultyRow`/`Scorecard` fields directly.

## Self-Check: PASSED

All created/modified files exist on disk; all three task commits (`379b88f`, `c3365c4`, `032df92`) present in git history.

---
*Phase: 11-metrics-the-mission-promises*
*Completed: 2026-07-20*
