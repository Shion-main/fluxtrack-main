---
phase: 01-mssql-environment-data-foundation
plan: 02
subsystem: testing
tags: [mssql, datetime2, timezone, asia-manila, django-test, csv-import, fixture, parity]

# Dependency graph
requires:
  - phase: 01-mssql-environment-data-foundation (plan 01)
    provides: MSSQL cutover — SQL Server 2025 LocalDB + Windows integrated auth, migrations + seed applied
provides:
  - Automated MSSQL datetime2 round-trip proof (no 8-hour Asia/Manila drift) — ENV-01
  - Automated import->materialize parity test reproducing R3-slice 17/10/15/18/18 on MSSQL — ENV-02
  - CI-safe committed synthetic fixture (data/fixtures/r3_synthetic.csv) exercising the importer without PII
  - make_session() test factory building the minimal Session FK chain
affects: [job-02, scan-resolver, session-materialization, ci-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DB-backed validation tests separated from the pure SimpleTestCase resolver suite in the same module"
    - "skipUnless(os.path.exists(REAL_CSV)) gate keeps PII-dependent parity tests green-or-skipped, never failing, in CI"
    - "TransactionTestCase for management commands that wrap work in transaction.atomic()"

key-files:
  created:
    - data/fixtures/r3_synthetic.csv
  modified:
    - scheduling/tests.py

key-decisions:
  - "Datetime assertions compare the aware instant AND the explicit UTC hour (16 / 0) so a silent ±8h drift cannot pass"
  - "Fixture uses 2 offerings (M+W same room, one F) → deterministic 3/2/2/3 counts independent of which weekday 'today' is"
  - "Default DB_TEST_NAME=test_fluxtrack retained; parallel plan 01-03 isolates via test_fluxtrack_campus"

patterns-established:
  - "Validation-first tests: characterize existing infra behavior (datetime2/UTC storage, importer counts) rather than driving new production code"
  - "R3 parity numbers pinned as regression guard for any future importer/materializer change"

requirements-completed: [ENV-01, ENV-02]

# Metrics
duration: 3min
completed: 2026-07-02
---

# Phase 01 Plan 02: MSSQL Datetime & Import Parity Test Scaffolding Summary

**Automated SQL Server tests proving no 8-hour Asia/Manila datetime drift and exact R3-slice import parity (17/10/15/18/18), plus a committed CI-safe synthetic fixture.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-07-02T19:11:45Z
- **Completed:** 2026-07-02T19:14:21Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `DatetimeRoundTripTests` proves an aware Asia/Manila instant round-trips on SQL Server `datetime2` with zero drift: 00:30 PHT reads back 16:30 UTC (prev day), 08:00 PHT reads back 00:00 UTC.
- `R3ParityTests` reproduces the validated R-floor-3 slice on MSSQL — 17 sections / 10 rooms / 15 faculty / 18 schedules / 18 sessions — and ran green on this machine (real registrar CSV present).
- `ImportPathTests` exercises the full import→materialize path anywhere via a committed anonymized fixture with known 3/2/2/3 counts.
- `make_session()` factory builds the minimal Session FK chain (Building/Floor/Room + Term/Schedule) for fast DB tests.
- Existing `FacultyResolverTests` (SimpleTestCase, no DB) left untouched and still green — full suite 20/20.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fixture helper + DatetimeRoundTripTests** - `c5563f3` (test)
2. **Task 2: R3ParityTests + ImportPathTests + fixture CSV** - `91e3a71` (test)

**Plan metadata:** _(final docs commit — see below)_

## Files Created/Modified
- `data/fixtures/r3_synthetic.csv` - Committed anonymized 2-offering R-floor-3 CSV (no PII); drives ImportPathTests everywhere.
- `scheduling/tests.py` - Appended `make_session()` helper, `DatetimeRoundTripTests`, `ImportPathTests`, `R3ParityTests`; existing resolver suite unchanged.

## Decisions Made
- Assert both the aware instant and the concrete UTC hour so a silent ±8h drift cannot slip through a naive equality check.
- Fixture layout (row 1 = M+W in R301, row 2 = F in R302) yields deterministic counts regardless of the current weekday, since a 7-day materialization window covers every weekday exactly once.
- Kept the default test DB name (`test_fluxtrack`); Wave-2 isolation from plan 01-03 is handled on that plan's side via `DB_TEST_NAME=test_fluxtrack_campus`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. All tests passed on first run. During the R3 parity run the test DB applied `campus.0002_cs_collation_tokens` (a migration authored by the parallel plan 01-03); it did not affect this plan's scheduling tests, and all 20 scheduling tests passed.

## R3ParityTests Execution Note
The real registrar CSV (`data/raw/2T-25-26-Course Offerring(Sheet1).csv`, gitignored) IS present on this machine, so `R3ParityTests` **ran and passed** — it was not skipped. Importer report confirmed 17 sections / 10 rooms / 15 faculty / 18 schedules, then 18 sessions materialized, matching the asserted validated numbers on MSSQL.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase success criteria 2 (no datetime drift) and 4 (import parity) are now locked behind repeatable MSSQL tests — a regression guard for JOB-02 and the scan resolver built on top.
- The unproven-MSSQL-datetime blocker recorded in STATE.md is now resolved by an explicit round-trip test.

---
*Phase: 01-mssql-environment-data-foundation*
*Completed: 2026-07-02*

## Self-Check: PASSED
- FOUND: data/fixtures/r3_synthetic.csv
- FOUND: scheduling/tests.py (DatetimeRoundTripTests, ImportPathTests, R3ParityTests present)
- FOUND: .planning/phases/01-mssql-environment-data-foundation/01-02-SUMMARY.md
- FOUND commit c5563f3 (Task 1)
- FOUND commit 91e3a71 (Task 2)
