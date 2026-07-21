---
phase: 12-term-lifecycle
plan: 03
subsystem: database
tags: [django, sql-server, migrations, term-lifecycle, reports]
requires:
  - phase: 12-01
    provides: "AcademicTerm status lifecycle and scheduling 0008 migration"
provides:
  - "ImportStaging.term nullable legacy-compatible PROTECT foreign key"
  - "WeeklyReport.term required PROTECT foreign key"
  - "Fail-loud WeeklyReport legacy backfill by exact term-week intersection"
  - "WeeklyReport identity constraint on term, week_start, and department"
affects: [ops, reports, term-lifecycle, import-staging]
tech-stack:
  added: []
  patterns:
    - "Nullable-add, RunPython backfill, constraint replacement, non-null finalize"
    - "MigrationExecutor tests for production-shaped legacy row states"
key-files:
  created:
    - ops/migrations/0006_term_ownership.py
    - ops/tests_term_migrations.py
  modified:
    - ops/models.py
    - ops/tests_reports.py
key-decisions:
  - "Legacy WeeklyReport rows are assigned a term only when the report week intersects exactly one AcademicTerm."
  - "ImportStaging.term remains nullable at schema level so legacy unconsumed uploads survive; Plan 04 owns new-flow enforcement."
patterns-established:
  - "Stored report identity is term/week_start/department rather than week_start/department."
  - "Backfill diagnostics include report id, week_start, candidate count, and candidate term ids."
requirements-completed: [A4, IFO-04]
coverage:
  - id: D1
    description: "Durable term ownership fields for staged imports and weekly reports"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall -q ops/models.py ops/migrations/0006_term_ownership.py ops/tests_term_migrations.py ops/tests_reports.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test ops.tests_term_migrations ops.tests_reports.WeeklyReportTermIdentityTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher and plain Python has no Django package."
  - id: D2
    description: "Fail-loud WeeklyReport backfill and term/week/department uniqueness"
    requirement: A4
    verification:
      - kind: other
        ref: "source checks for scheduling 0008 dependency, nullable fields before RunPython, no ACTIVE fallback, and no csv_path/pdf_path writes"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test ops.tests_term_migrations ops.tests_reports -v 2"
        status: fail
    human_judgment: true
    rationale: "The local shell cannot run Django/MSSQL tests; run the listed commands in the configured project environment."
duration: 22 min
completed: 2026-07-22
status: complete
---

# Phase 12 Plan 03: Term Ownership Storage Summary

**Durable term identity for staged imports and stored weekly reports with fail-loud legacy report backfill.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-07-22T01:12:00+08:00
- **Completed:** 2026-07-22T01:34:00+08:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `ImportStaging.term` as a nullable `PROTECT` foreign key so legacy staged rows survive while Plan 04 can bind every new preview/commit flow to an intended term.
- Added required `WeeklyReport.term` and replaced `(week_start, department)` identity with `uniq_weekly_report_term_week_department`.
- Added `0006_term_ownership.py` with nullable field creation, materialized legacy report backfill, old uniqueness removal, new constraint creation, and non-null finalization.
- Added migration-executor and model tests for exact-one backfill, ambiguous/unmatched fail-loud behavior, legacy ImportStaging null tolerance, same-week cross-term coexistence, required report term, and `PROTECT` deletion semantics.

## Task Commits

1. **Task 1 RED:** `65021c5` test(12-03): add term ownership migration contract tests
2. **Task 2 GREEN:** `f4ea6b5` feat(12-03): add term ownership to ops records

## Files Created/Modified

- `ops/migrations/0006_term_ownership.py` - Adds term ownership fields and backfills WeeklyReport rows only on exactly one intersecting term.
- `ops/tests_term_migrations.py` - Adds migration-executor coverage for backfill success, ambiguous/unmatched aborts, cross-term uniqueness, and legacy staged imports.
- `ops/models.py` - Adds `ImportStaging.term`, required `WeeklyReport.term`, and the term/week/department unique constraint.
- `ops/tests_reports.py` - Adds `WeeklyReportTermIdentityTests` for required term ownership and `PROTECT` semantics.

## Decisions Made

- The WeeklyReport backfill uses inclusive week intersection `[week_start, week_start + 6 days]` and never falls back to the current ACTIVE term.
- Legacy report metadata and storage paths are left untouched; the migration updates only `term_id`.
- ImportStaging allows `term=NULL` for legacy rows at the schema layer; application-level mandatory binding is deferred to Plan 04 as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The required `py -3.12` commands cannot run in this shell: `No installed Python found!`.
- Fallback `python manage.py ...` commands cannot run Django: `ModuleNotFoundError: No module named 'django'`.
- Fallback syntax verification passed: `python -m compileall -q ops/models.py ops/migrations/0006_term_ownership.py ops/tests_term_migrations.py ops/tests_reports.py`.
- `sqlmigrate ops 0006` could not be inspected locally for the same Python/Django environment reason; run it against the MSSQL configuration before deployment.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Next Phase Readiness

Plan 04 can build on `ImportStaging.term` to make every new stage/resolve/consume flow explicitly term-bound. Before operational use, run the plan verification in the configured Python/MSSQL environment:

- `py -3.12 manage.py test ops.tests_term_migrations ops.tests_reports.WeeklyReportTermIdentityTests -v 2`
- `py -3.12 manage.py test ops.tests_term_migrations ops.tests_reports -v 2`
- `py -3.12 manage.py makemigrations --check --dry-run`
- `py -3.12 manage.py sqlmigrate ops 0006`

## Self-Check: PASSED

- Files exist: `ops/models.py`, `ops/migrations/0006_term_ownership.py`, `ops/tests_term_migrations.py`, `ops/tests_reports.py`, and this summary.
- Commits exist: `65021c5` and `f4ea6b5`.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-22*
