---
phase: 06-reporting-engine-reporting-surfaces
plan: 01
subsystem: api
tags: [django-orm, mssql, conditional-aggregation, reporting, dataclasses, tdd]

# Dependency graph
requires:
  - phase: 02-correctness-foundations
    provides: "Session.status truth (ABSENT via sweep, ACTIVE/COMPLETED = held), is_no_show_past_grace"
  - phase: 03-checker-verification
    provides: "CheckerValidation (action=verified, related_name=validations)"
  - phase: 04.2-merged-sections
    provides: "MERGED checkin_method siblings get NO CheckerValidation (D-09 honest verified)"
provides:
  - "scheduling/reporting.py: HELD_STATUSES + dataclasses FacultyRow/DeptSummary/AbsenceItem/Scorecard"
  - "faculty_attendance() pure RPT-01 per-faculty aggregate (scheduled/held/absent/verified/early_ends/attendance_pct + itemized absences)"
  - "dept_summary() department-wide totals + distinct faculty_count"
  - "faculty_scorecard() RPT-04 slice with early-ends + effective-modality breakdown"
  - "safe_card() RPT-05 per-card isolation wrapper"
  - "scheduling/test_support.py::make_reporting_fixture two-department multi-status reporting fixture"
affects: [06-02, 06-03, 06-04, 06-05, 06-06, ifo-dashboard, dean-dashboard, hr-list, weekly-report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure aggregate layer mirroring resolver discipline: no writes, no notify(), no timezone.now() inside; range/as_of passed as args"
    - "DB-side conditional aggregation (Count(filter=Q(...)) in one GROUP BY); attendance_pct computed in Python to dodge MSSQL int-division"
    - "Separate grouped verified query so the validations reverse-join never inflates status counts"
    - "Effective-modality via Case/When(declared_modality='' -> schedule__modality, default declared_modality)"
    - "safe_card (value, None)/(None, generic) isolation, logs real exc, never leaks exception text"

key-files:
  created:
    - "scheduling/reporting.py"
    - "scheduling/tests_reporting.py"
  modified:
    - "scheduling/test_support.py"

key-decisions:
  - "faculty_scorecard/Scorecard co-located in the Task 1 GREEN reporting.py write (whole-module create) rather than a separate Task 2 GREEN commit; Task 2 landed its tests/verification separately."
  - "Verified count = distinct sessions with a ValidationAction.VERIFIED validation, via a SEPARATE grouped query merged by faculty_id in Python (status counts stay honest)."
  - "_scoped_sessions restricts to schedule__status=ACTIVE (archived-schedule sessions are not real obligations, RESEARCH A5); as_of clamps date__lte so future not-yet-missed sessions do not lower attendance %."
  - "Aggregates filter Session.date (local DateField), never scheduled_start (UTC), so weekly boundaries carry no Asia/Manila drift (Pitfall 1)."

patterns-established:
  - "Pattern: pure reporting aggregate returning dataclasses, unit-tested against a shared multi-status fixture under the Django runner"
  - "Pattern: verified/held decoupled — held from Session.status, verified from a separate validations query (MERGED siblings held-not-verified)"

requirements-completed: [RPT-01, RPT-04, RPT-05]

coverage:
  - id: D1
    description: "faculty_attendance() returns one FacultyRow per faculty with scheduled/held/absent/verified/early_ends/attendance_pct + itemized absences read from Session.status truth"
    requirement: "RPT-01"
    verification:
      - kind: unit
        ref: "scheduling/tests_reporting.py::AggregateTests"
        status: pass
      - kind: unit
        ref: "scheduling/tests_reporting.py::TruthReuseTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "MERGED sibling counts as held but not checker-verified (honest verified count)"
    requirement: "RPT-01"
    verification:
      - kind: unit
        ref: "scheduling/tests_reporting.py::MergedSiblingTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "faculty_scorecard() adds early-ends + effective-modality breakdown honoring declared_modality (declared-ONLINE-over-F2F counted ONLINE)"
    requirement: "RPT-04"
    verification:
      - kind: unit
        ref: "scheduling/tests_reporting.py::ScorecardTests"
        status: pass
      - kind: unit
        ref: "scheduling/tests_reporting.py::WeekBoundaryTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "safe_card() returns (value, None) on success and (None, generic message) on failure without leaking exception text"
    requirement: "RPT-05"
    verification:
      - kind: unit
        ref: "scheduling/tests_reporting.py::CardIsolationTests"
        status: pass
    human_judgment: false

# Metrics
duration: ~35min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 01: Reporting Aggregate Layer Summary

**Pure, side-effect-free Django-ORM aggregate layer (faculty_attendance / dept_summary / faculty_scorecard / safe_card) reading the Session.status truth via DB-side conditional aggregation, with a two-department multi-status reporting fixture and 20 unit tests.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-15
- **Tasks:** 2 (both TDD)
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- `scheduling/reporting.py`: `HELD_STATUSES`, dataclasses `FacultyRow`/`DeptSummary`/`AbsenceItem`/`Scorecard`, and pure functions `faculty_attendance()`, `dept_summary()`, `faculty_scorecard()`, `safe_card()`.
- Held/absent read straight from `Session.status` (never re-derived from timestamps); verified computed by a SEPARATE grouped query so the validations reverse-join cannot inflate status counts; MERGED siblings stay held-but-unverified.
- `faculty_scorecard()` adds early-ends and a DB-side effective-modality breakdown (`declared_modality` overrides `schedule.modality`, honoring approved shifts).
- `safe_card()` isolates a raising aggregate to its own card, logs the real exception server-side, and returns a generic message (no exception-text leak).
- `make_reporting_fixture()` in `scheduling/test_support.py`: two departments over one term, all sessions inside the known Mon–Sun `IN_WINDOW_DATE` week, spanning every Session status + a MERGED sibling + a verified validation + an `ended_early` session + a declared-ONLINE-over-F2F session.
- 20 unit tests (`scheduling/tests_reporting.py`) all green; full 179-test `scheduling` suite still OK (no regressions).

## Task Commits

1. **Task 1 (RED): fixture + failing aggregate/truth/merge/card tests** - `a3d8cf5` (test)
2. **Task 1 (GREEN): faculty_attendance/dept_summary/safe_card + scorecard** - `2b8a459` (feat)
3. **Task 2 (test): scorecard early-ends/effective-modality + week-boundary** - `3025118` (test)

_Task 2's implementation (`faculty_scorecard`/`Scorecard`) was co-located in the Task 1 GREEN whole-module write of `reporting.py`; Task 2 added its dedicated tests + verification._

## Files Created/Modified
- `scheduling/reporting.py` (created) - Pure RPT-01/04/05 aggregates + dataclasses + safe_card.
- `scheduling/tests_reporting.py` (created) - AggregateTests, TruthReuseTests, MergedSiblingTests, CardIsolationTests, ScorecardTests, WeekBoundaryTests (20 tests).
- `scheduling/test_support.py` (modified) - Added `make_reporting_fixture(prefix="rpt")` + CheckinMethod/CheckerValidation/ValidationAction imports.

## Decisions Made
- **Whole-module GREEN write:** `reporting.py` was written complete in the Task 1 GREEN commit (including `faculty_scorecard`/`Scorecard`) for module cohesion; Task 2 therefore landed as a test-only commit. Deviation from the strict per-task RED/GREEN split, documented below. Project TDD gate is off (`config.workflow` has no `tdd_mode`), so this is cosmetic to the gate.
- **Verified via separate query:** distinct-session count over `validations__action=VERIFIED`, merged by `faculty_id` in Python — keeps held/absent counts free of reverse-join row multiplication.
- **`schedule__status=ACTIVE` in the base filter:** archived-schedule sessions excluded (RESEARCH A5). `as_of` clamps `date__lte` so a future not-yet-missed session doesn't lower attendance %.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking/sequencing] Scorecard implementation co-located in Task 1 GREEN**
- **Found during:** Task 1 (GREEN write of reporting.py)
- **Issue:** The shared test module imports all public symbols at the top; writing `reporting.py` as one cohesive module meant `faculty_scorecard`/`Scorecard` were defined during Task 1's GREEN rather than deferred to Task 2's GREEN. A strict per-task split would have required a stub-then-fill dance for no functional gain.
- **Fix:** Kept the whole-module write in Task 1; Task 2 landed its ScorecardTests/WeekBoundaryTests as a test commit that verifies the already-present implementation. All acceptance greps for Task 2 (`def faculty_scorecard`, `ended_early`, `declared_modality`) pass.
- **Files modified:** scheduling/reporting.py (Task 1 commit `2b8a459`), scheduling/tests_reporting.py (Task 2 commit `3025118`)
- **Verification:** `manage.py test scheduling.tests_reporting -v1` → 20 tests OK.
- **Committed in:** `2b8a459` (impl), `3025118` (tests)

**2. [Rule 1 - Bug] Corrected an as_of test expectation**
- **Found during:** Task 1 (GREEN test run)
- **Issue:** `test_as_of_clamps_future_scheduled_session` initially set `as_of=week_start` (Monday) and expected `scheduled==7`, but `date__lte=Monday` also excludes the Tue/Wed sessions, yielding 5.
- **Fix:** Set `as_of=tue` so only the future Wednesday SCHEDULED session is clamped → `scheduled==7`. The test now correctly proves the as_of semantics (future not-yet-missed session excluded).
- **Files modified:** scheduling/tests_reporting.py
- **Verification:** test passes.
- **Committed in:** `2b8a459` (Task 1 GREEN)

---

**Total deviations:** 2 (1 sequencing, 1 test-expectation fix)
**Impact on plan:** No scope creep. All planned artifacts, symbols, and test classes delivered exactly. Behavior matches the plan's must-haves.

## Issues Encountered
None beyond the test-expectation fix above. The `RuntimeError` traceback printed during the run is the intentional `logger.exception` output from `CardIsolationTests` (the safe_card failure path) — not a test failure.

## User Setup Required
None - no external service configuration required. No new dependencies (ReportLab/CSV/PDF land in later plans).

## Next Phase Readiness
- The shared aggregate layer is ready for consumption by 06-02 (weekly report render/generation), 06-03/04/05/06 (IFO-09, Dean, HR surfaces).
- Symbols exported: `HELD_STATUSES`, `FacultyRow`, `DeptSummary`, `AbsenceItem`, `Scorecard`, `faculty_attendance`, `dept_summary`, `faculty_scorecard`, `safe_card`, plus `make_reporting_fixture` for downstream tests.
- No blockers.

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*
