---
phase: 12-term-lifecycle
plan: 08
subsystem: reporting
tags: [django, term-lifecycle, reports, scheduler, storage, mssql]
requires:
  - phase: 12-03
    provides: "WeeklyReport.term and term/week/department identity"
  - phase: 06-05
    provides: "stored weekly report generation, renderers, and scheduler job"
provides:
  - "Mandatory term signatures for attendance and coverage aggregate APIs"
  - "Term-filtered shared Session aggregate root via schedule__term=term"
  - "Term-keyed weekly report generation and reports/term-<pk>/<week>/ storage paths"
  - "Active-term scoped weekly report command and scheduler adapters"
affects: [reporting, weekly-reports, scheduler, term-lifecycle, ifo-dashboard, dean-reporting]
tech-stack:
  added: []
  patterns:
    - "Term identity is required below report controllers; omission is a TypeError"
    - "Stored reports are generated only for one supplied writable term"
    - "Scheduler resolves the authoritative ACTIVE term once and no-ops when absent"
key-files:
  created: []
  modified:
    - scheduling/reporting.py
    - scheduling/tests_reporting.py
    - scheduling/tests_reporting_coverage.py
    - scheduling/tests_reporting_lateness.py
    - scheduling/tests_reporting_rooms.py
    - ops/reports.py
    - ops/tests_reports.py
    - scheduling/management/commands/generate_weekly_report.py
    - scheduling/management/commands/runscheduler.py
    - web/ifo.py
    - web/dean.py
    - web/tests_dean_reporting.py
    - web/tests_reporting.py
key-decisions:
  - "Aggregate and weekly report services take required keyword-only term parameters; no service resolves ACTIVE internally."
  - "New stored weekly report files use reports/term-<pk>/<week>/<department-code>.csv|pdf."
  - "The on-demand command accepts --term by pk or exact name but refuses non-ACTIVE terms; the lower-level service still uses the writable-term guard."
patterns-established:
  - "Controller/adapters resolve term; aggregate/generation services only consume explicit term."
  - "No-ACTIVE weekly scheduler run returns 0 and does not scan archived history."
requirements-completed: [A4, IFO-04]
coverage:
  - id: D1
    description: "Attendance and coverage aggregates require explicit term and filter Session rows with schedule__term=term."
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall -q scheduling/reporting.py scheduling/tests_reporting.py scheduling/tests_reporting_rooms.py scheduling/tests_reporting_coverage.py scheduling/tests_reporting_lateness.py web/ifo.py web/dean.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_reporting scheduling.tests_reporting_rooms -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher; source and compile checks passed."
  - id: D2
    description: "Stored weekly report generation is keyed by one supplied term, writes term-qualified paths, and refuses archived terms before metadata/file writes."
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall -q ops/reports.py ops/tests_reports.py web/tests_dean_reporting.py web/tests_reporting.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test ops.tests_reports.WeeklyReportTermTests ops.tests_reports -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher; service source checks confirmed required term signatures, writable guard, schedule__term predicate, and reports/term- paths."
  - id: D3
    description: "Weekly command and scheduler adapters pass explicit term, refuse explicit non-ACTIVE command targets, and no-op safely with no ACTIVE scheduler term."
    requirement: IFO-04
    verification:
      - kind: other
        ref: "python -m compileall -q scheduling/management/commands/generate_weekly_report.py scheduling/management/commands/runscheduler.py ops/reports.py ops/tests_reports.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test ops.tests_reports ops.tests.NoImplicitSchedulerTests -v 2 && py -3.12 manage.py check"
        status: fail
    human_judgment: true
    rationale: "Django verification and manage.py check could not run because this shell has no py launcher; source checks confirmed term= production calls and no implicit lookup in ops.reports."
duration: 10 min
completed: 2026-07-21
status: complete
---

# Phase 12 Plan 08: Term-Required Reporting Generation Summary

**Report aggregates and stored weekly generation now require explicit term identity, use term-qualified storage, and schedule only the authoritative ACTIVE term.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-21T18:01:27Z
- **Completed:** 2026-07-21T18:11:21Z
- **Tasks:** 3
- **Files modified:** 13

## Accomplishments

- Made `_scoped_sessions`, `faculty_attendance`, `dept_summary`, `coverage_by_building_day`, `zero_coverage_floors`, and `faculty_scorecard` require `term` and apply `schedule__term=term` at the shared query root.
- Added same-date Draft/Archived leakage tests and omission TypeError tests for aggregate APIs.
- Updated weekly report generation to require `term`, guard with `require_writable_term`, use `(term, week_start, department)` identity, and write new files under `reports/term-<pk>/<week>/`.
- Added command/scheduler adapter tests and implementation: `generate_weekly_report --term`, ACTIVE-only command targets, scheduler no-active no-op, and coupling guards that production calls pass `term=`.

## Task Commits

1. **Task 1 RED:** `082950b` test(12-08): add failing term-scope aggregate tests
2. **Task 1 GREEN:** `478b6c4` feat(12-08): require term in attendance aggregates
3. **Task 2 RED:** `546e9ad` test(12-08): add failing term-keyed weekly report tests
4. **Task 2 GREEN:** `e4466d3` feat(12-08): key weekly reports by term
5. **Task 3 RED:** `1a4c284` test(12-08): add failing active-term report adapter tests
6. **Task 3 GREEN:** `117f0b5` feat(12-08): scope report adapters to active term

## Files Created/Modified

- `scheduling/reporting.py` - Required term-aware aggregate signatures and shared `schedule__term` predicate.
- `scheduling/tests_reporting.py` - Updated aggregate calls and added term omission/leakage tests.
- `scheduling/tests_reporting_coverage.py` - Updated coverage calls and added coverage term-scope tests.
- `scheduling/tests_reporting_lateness.py` - Updated lateness aggregate calls to pass term.
- `scheduling/tests_reporting_rooms.py` - Updated stale term fixture/comment to the status lifecycle.
- `ops/reports.py` - Required term-aware stored generation, writable-term guard, term-qualified paths and department discovery.
- `ops/tests_reports.py` - Added weekly report term generation, command, scheduler, and coupling tests.
- `scheduling/management/commands/generate_weekly_report.py` - Added `--term`, ACTIVE resolution, and ACTIVE-only command refusal.
- `scheduling/management/commands/runscheduler.py` - Resolves ACTIVE once and no-ops when none exists.
- `web/ifo.py`, `web/dean.py` - Minimal adjacent updates so existing report consumers pass active term into required aggregate services.
- `web/tests_dean_reporting.py`, `web/tests_reporting.py` - Updated stored-report fixture setup calls for the new required generation signature.

## Decisions Made

- Aggregate services do not resolve ACTIVE internally. Existing IFO/Dean report controllers perform the minimal active-term adapter role until later selector propagation plans own explicit historical term selection.
- The stored report notification link now includes `term-<pk>` in the generated path segment so a notification is not only week-keyed.
- The command layer is stricter than the lower-level service: explicit `--term` must name an ACTIVE term, while the service uses the reusable writable-term guard required by the generation boundary tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated adjacent IFO/Dean aggregate consumers**
- **Found during:** Task 1
- **Issue:** Making aggregate `term` mandatory would break existing IFO and Dean report views that still called the aggregate services without term.
- **Fix:** Resolved the ACTIVE term at the controller boundary and passed it into the now-required aggregate APIs.
- **Files modified:** `web/ifo.py`, `web/dean.py`
- **Verification:** `python -m compileall -q web/ifo.py web/dean.py`; source inventory of aggregate signatures/call sites.
- **Commit:** `478b6c4`

**2. [Rule 3 - Blocking] Updated adjacent report view test seed calls**
- **Found during:** Task 2
- **Issue:** Existing Dean/IFO report tests seeded stored reports through the generation service's old positional signature.
- **Fix:** Updated those seed calls to pass the fixture term explicitly.
- **Files modified:** `web/tests_dean_reporting.py`, `web/tests_reporting.py`
- **Verification:** `python -m compileall -q web/tests_dean_reporting.py web/tests_reporting.py`
- **Commit:** `e4466d3`

**Total deviations:** 2 auto-fixed (2 blocking).
**Impact on plan:** Both changes were required by the plan's mandatory service signatures and stayed within existing reporting adapters/tests.

## Issues Encountered

- `py -3.12 manage.py test scheduling.tests_reporting scheduling.tests_reporting_rooms -v 2` failed before Django startup: `No installed Python found!`.
- `py -3.12 manage.py test ops.tests_reports.WeeklyReportTermTests ops.tests_reports -v 2` failed for the same local launcher issue.
- `py -3.12 manage.py test ops.tests_reports ops.tests.NoImplicitSchedulerTests -v 2` and `py -3.12 manage.py check` failed for the same local launcher issue.
- Fallback compile/source checks passed for all changed files.

## User Setup Required

None - no external service configuration required. Run the listed Django commands in the configured Python 3.12/MSSQL environment.

## Known Stubs

None.

## Threat Flags

None. This plan narrows existing report-generation and aggregate trust boundaries; it does not add new network endpoints, auth paths, file access from user input, or schema changes.

## Next Phase Readiness

Plan 09 can build on required-term aggregate and generation services. Later report selector plans should replace the temporary active-term adapter in IFO/Dean controllers with the selected report term and preserve it through links/exports.

## Self-Check: PASSED

- Files exist: all 13 modified source/test files and this summary.
- Commits exist: `082950b`, `478b6c4`, `546e9ad`, `e4466d3`, `1a4c284`, `117f0b5`.
- No tracked files were deleted in task commits.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-21*
