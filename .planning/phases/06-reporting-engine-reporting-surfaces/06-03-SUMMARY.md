---
phase: 06-reporting-engine-reporting-surfaces
plan: 03
subsystem: api
tags: [reportlab, pdf, csv, csv-injection, reporting, platypus, rpt-03]

# Dependency graph
requires:
  - phase: 06-reporting-engine-reporting-surfaces
    provides: "06-01 FacultyRow dataclass (name, scheduled, held, absent, verified, attendance_pct, early_ends, absences) from scheduling/reporting.py"
  - phase: 06-reporting-engine-reporting-surfaces
    provides: "06-02 reportlab>=4.2,<5 installed (4.5.1); reportlab.platypus importable under py -3.12"
provides:
  - "scheduling/report_render.py: csv_safe(value), build_csv(rows) -> bytes, build_pdf(rows, week_start, department) -> bytes"
  - "csv_safe() — the single shared CSV-injection neutralizer (= + - @ tab CR) imported by every CSV export in the phase"
  - "HEADER — the six-column Faculty/Scheduled/Held/Absent/Attendance %/Checker-verified contract shared by CSV and PDF"
affects: [06-05-weekly-report-surface, 06-06-dean-export, 06-07-hr-payroll-csv]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure render layer: dataclasses in, bytes out — no ORM, no default_storage, no HttpResponse (caller builds the download response)"
    - "Single shared CSV-injection neutralizer (csv_safe) so weekly-report CSV and payroll CSV can never disagree on the guard"
    - "stdlib csv.writer for quoting/escaping — never hand-rolled string joins"
    - "ReportLab Platypus Table with repeatRows=1 + brand-navy (#001c43) header fill for printable PDF"

key-files:
  created:
    - "scheduling/report_render.py — csv_safe(), build_csv(), build_pdf()"
    - "scheduling/tests_report_render.py — CsvBuildTests, CsvInjectionTests, PdfBuildTests"
  modified: []

key-decisions:
  - "csv_safe() lives in report_render.py as the phase-wide neutralizer (per 06-03 key_links) so 06-05 and 06-07 import one guard, not two divergent copies"
  - "build_csv formats attendance as an int-percent string (e.g. 75%); counts are emitted as plain ints and delegated to csv quoting"
  - "build_pdf handles empty rows by rendering the title + a 'No data for this range.' line rather than a zero-row Table (which ReportLab errors on)"

patterns-established:
  - "Pattern: pure bytes-in/bytes-out render functions over reporting dataclasses, unit-tested with SimpleTestCase (no DB)"
  - "Pattern: security control (CSV-injection guard) implemented once and reused, not re-derived per export"

requirements-completed: [RPT-03]

coverage:
  - id: D1
    description: "csv_safe() neutralizes leading = + - @ tab CR so a faculty name cannot become an Excel formula (CSV-injection control, T-06-02)"
    requirement: "RPT-03"
    verification:
      - kind: unit
        ref: "scheduling/tests_report_render.py#CsvInjectionTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_csv(rows) returns bytes with a correct header row and one row per FacultyRow, quoted/escaped by the stdlib csv module"
    requirement: "RPT-03"
    verification:
      - kind: unit
        ref: "scheduling/tests_report_render.py#CsvBuildTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "build_pdf(rows, week_start, department) returns non-empty %PDF bytes via ReportLab Platypus with a repeating navy header row; empty input still yields a valid PDF"
    requirement: "RPT-03"
    verification:
      - kind: unit
        ref: "scheduling/tests_report_render.py#PdfBuildTests"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-15
status: complete
---

# Phase 06 Plan 03: CSV/PDF Render Layer Summary

**Pure bytes-in/bytes-out render layer (scheduling/report_render.py) turning FacultyRow aggregates into a stdlib-csv download and a ReportLab-Platypus navy-header PDF, guarded by a single shared CSV-injection neutralizer.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-07-15
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- `csv_safe()` — the phase-wide CSV-injection neutralizer prefixing a single quote to any text cell starting with `=`, `+`, `-`, `@`, tab, or carriage-return (T-06-02); the one guard 06-05 and 06-07 both import.
- `build_csv(rows)` — header + one line per FacultyRow via the stdlib `csv` module into `StringIO`, faculty name run through `csv_safe`, returns UTF-8 bytes; empty list yields header only.
- `build_pdf(rows, week_start, department)` — landscape-A4 ReportLab Platypus table with `repeatRows=1`, brand-navy (`#001c43`) header fill, thin grid, zebra rows; returns `%PDF` bytes and handles empty input gracefully.
- 11/11 unit tests green (CsvBuildTests, CsvInjectionTests, PdfBuildTests) under the Django test runner.

## Task Commits

TDD cycle (RED test gate → GREEN implementation):

1. **RED — failing tests for render layer** - `3016e64` (test)
2. **Task 1 + Task 2 — csv_safe/build_csv/build_pdf** - `0277c14` (feat)

**Plan metadata:** committed with STATE/ROADMAP update (docs).

_Note: Tasks 1 and 2 landed in one GREEN feat commit — see Deviations._

## Files Created/Modified
- `scheduling/report_render.py` - Pure CSV/PDF byte builders + `csv_safe()` neutralizer; no ORM/storage/HttpResponse.
- `scheduling/tests_report_render.py` - CsvBuildTests, CsvInjectionTests, PdfBuildTests (SimpleTestCase, no DB).

## Decisions Made
- Placed `csv_safe()` in `report_render.py` as the single phase-wide neutralizer (per the plan's `key_links`) so downstream exports import one guard rather than maintaining divergent copies.
- CSV emits attendance as an int-percent string (`75%`) matching the PDF cell format; the header/column order (`HEADER`) is a module constant shared by both builders so they can never drift.
- `build_pdf` renders empty input as title + "No data for this range." to avoid a zero-row ReportLab Table error.

## Deviations from Plan

### Structural (not a rule-triggered auto-fix)

**1. Tasks 1 and 2 committed in a single GREEN feat commit**
- **Found during:** Task 1 GREEN phase
- **Issue:** The single shared test module `scheduling/tests_report_render.py` imports `build_csv`, `build_pdf`, and `csv_safe` at module top level. A Task-1-only implementation (no `build_pdf`) makes the whole test module fail to import, so the CSV test classes cannot even load in isolation.
- **Resolution:** Implemented both builders in one cohesive module and committed them together as `0277c14`, after the RED test gate `3016e64`. The RED→GREEN TDD sequence is preserved; only the per-task commit granularity changed.
- **Impact:** None on correctness or scope. Both builders live in one module (`report_render.py`) with one shared test module by design, so a combined commit is the natural unit.

---

**Total deviations:** 1 structural (commit granularity), 0 rule-triggered auto-fixes.
**Impact on plan:** All plan behaviors, artifacts, acceptance criteria, and prohibitions satisfied exactly. No scope creep.

## Issues Encountered
None — RED confirmed failing (module absent), GREEN confirmed all 11 tests pass on first implementation.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `build_csv` / `build_pdf` / `csv_safe` are ready for 06-05 (stored weekly report), 06-06 (Dean ad-hoc export), and 06-07 (HR payroll CSV reuses `csv_safe`).
- Prohibitions honored: no WeasyPrint / window.print, no hand-rolled CSV quoting, no file writes or `default_storage` access — render is pure bytes-in/bytes-out.

## Self-Check: PASSED

- FOUND: scheduling/report_render.py
- FOUND: scheduling/tests_report_render.py
- FOUND: 06-03-SUMMARY.md
- FOUND commit: 3016e64 (RED test gate)
- FOUND commit: 0277c14 (GREEN feat)

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*
