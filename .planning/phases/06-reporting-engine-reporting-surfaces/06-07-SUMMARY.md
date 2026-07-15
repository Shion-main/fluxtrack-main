---
phase: 06-reporting-engine-reporting-surfaces
plan: 07
subsystem: web
tags: [django, hr, reporting, hr-01, hr-02, hr-03, csv-injection, streaming, read-only, franken-ui]

# Dependency graph
requires:
  - phase: 06-01
    provides: "scheduling/models.py Session (status, actual_start, checkin_method, verified_by_checker) + make_reporting_fixture (two departments, multi-status sessions, active term)"
  - phase: 06-03
    provides: "scheduling/report_render.py csv_safe -- the single shared CSV-injection neutralizer reused by the HR payroll CSV"
  - phase: 06-06
    provides: "web/dean.py role-gate + GET-only read-only + department-scoping patterns; web/urls.py + web/views.py current state (Dean routes preserved)"
provides:
  - "web/hr.py: hr_required gate + attendance() session-level list view + attendance_csv() streaming export; _filtered_sessions() shared filter parser"
  - "templates/hr/attendance.html (Pattern-A filter bar + dense uk-table) + templates/hr/_rows.html"
  - "web/urls.py hr_attendance + hr_attendance_csv routes; web/views.py HR 'Attendance' nav href off '#'"
  - "web/tests_hr.py: HrGateTests, HrFilterTests, HrExportTests, HrReadOnlyTests"
affects: [hr-attendance-surface, payroll-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Streaming CSV via StreamingHttpResponse + queryset.iterator() + an echo-writer (_Echo whose write returns the value) so the payroll export bounds memory at full-term scale (T-06-03)"
    - "Checker-verified status ANNOTATED via Exists(OuterRef) so it is resolved in the main query -- no per-row subquery runs inside the streaming generator (MSSQL HY010/cursor-open trap avoided, T-06-15)"
    - "One shared _filtered_sessions parser feeds BOTH the list view and the CSV export so their scope can never disagree; filters key on FK id + date__range only (never pk__in -> the 2100-param trap, T-06-16)"
    - "Cross-department by design: department is a FILTER, not a scope boundary (unlike Dean); hr_required gates access, but no per-department server-side scoping"
    - "Read-only via @require_http_methods(['GET']) on every view so a POST is 405 (T-06-07); csv_safe reused (not reimplemented) for injection neutralization (T-06-02)"

key-files:
  created:
    - "web/hr.py"
    - "templates/hr/attendance.html"
    - "templates/hr/_rows.html"
    - "web/tests_hr.py"
  modified:
    - "web/urls.py"
    - "web/views.py"

key-decisions:
  - "The checker-verified status is an is_verified Exists() ANNOTATION rather than the Session.verified_by_checker property, because the property runs a per-object query -- fatal inside a streaming .iterator() generator on MSSQL. Annotating resolves it in the one main query so no subquery opens while the server-side cursor is streaming."
  - "A single _filtered_sessions(request) parser is shared by attendance() and attendance_csv() so the on-screen filters and the exported rows are always the same set; the export never diverges from what the user sees."
  - "An invalid date degrades to a friendly inline notice and drops just that bound (a 200 with a note), never a 500; filters are ignored rather than raising, and no filter uses a pk__in id list."
  - "The HR surface is GET-only (@require_http_methods(['GET'])) so a POST is 405 -- the enforceable read-only guarantee (a bare Django view otherwise accepts any method), mirroring the 06-06 Dean surface."

requirements-completed: [HR-01, HR-02, HR-03]

coverage:
  - id: D1
    description: "hr_required gates the list + CSV to Role.HR_ADMIN (superuser bypass); a non-HR user is refused 403"
    requirement: "HR-01"
    verification:
      - kind: view-test
        ref: "web/tests_hr.py::HrGateTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Four independent filters (faculty/department/date-range/term) each narrow the session list; an invalid date yields a 200 friendly notice not a 500; a no-match filter shows the no-results state"
    requirement: "HR-02"
    verification:
      - kind: view-test
        ref: "web/tests_hr.py::HrFilterTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "attendance_csv streams a text/csv attachment (header + a Present + an Absent row) that honors the active filters and neutralizes a faculty name beginning with '=' via reused csv_safe"
    requirement: "HR-03"
    verification:
      - kind: view-test
        ref: "web/tests_hr.py::HrExportTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "A POST to /hr/attendance or /hr/attendance.csv is rejected 405 -- the HR surface exposes no write endpoint"
    requirement: "HR-01"
    verification:
      - kind: view-test
        ref: "web/tests_hr.py::HrReadOnlyTests"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-07-15
status: complete
---

# Phase 06 Plan 07: HR Session-Level Attendance Surface (HR-01/02/03) Summary

**An `hr_required`, cross-department, read-only HR attendance surface at the SESSION grain -- a filterable/searchable list (faculty / department / date range / term) whose invalid input degrades to a friendly notice never a 500, plus a streaming, injection-safe payroll CSV export -- where the checker-verified status is an `Exists()` annotation (so no subquery runs inside the `.iterator()` generator on MSSQL), one shared filter parser keeps the list and the export in lock-step, and every view is GET-only so a POST is 405; 14 view-tests green.**

## Performance
- **Duration:** ~20 min
- **Completed:** 2026-07-15
- **Tasks:** 3 (all `auto`)
- **Files:** 6 (4 created, 2 modified)

## Accomplishments
- `web/hr.py`: `hr_required` (login + Role.HR_ADMIN, superuser bypass, T-06-14) + `attendance()` (the session-level list) + `attendance_csv()` (the streaming payroll export), both GET-only.
- **Session-grain list (HR-01):** each row shows faculty, course/section, date, scheduled vs actual start, a Present/Absent status pill, check-in method, and the honest checker-verified badge -- NOT the aggregate grain the Dean/IFO dashboards use.
- **Four independent filters + search (HR-02):** faculty (id), department (`faculty__department` id), term (`schedule__term` id), and `from`/`to` date range (`parse_date`-validated), plus a free-text search over faculty name / course code. All key on FK id + `date__range` -- never a `pk__in` id list (the 2100-param trap, T-06-16). Invalid dates leave a friendly inline notice and are ignored (a 200, never a 500).
- **Streaming injection-safe export (HR-03):** `attendance_csv` uses `StreamingHttpResponse` + `queryset.iterator()` + an `_Echo` echo-writer so the full-term payroll CSV bounds memory (T-06-03). Text cells run through the REUSED `scheduling.report_render.csv_safe` so a faculty name beginning with `= + - @` can never become an Excel formula (T-06-02). NO write is performed inside the generator (T-06-15).
- **`is_verified` annotation (the load-bearing decision):** checker-verification is `Exists(CheckerValidation ... action=VERIFIED)` annotated onto the queryset, so it resolves in the one main query -- no per-row subquery runs inside the streaming `.iterator()` generator (which would trip the MSSQL HY010/cursor-open trap the `Session.verified_by_checker` property would cause).
- **Shared parser:** one `_filtered_sessions(request)` feeds BOTH the list and the CSV export so the exported rows are always exactly the filtered set the user sees.
- **Read-only (T-06-07):** every HR view is `@require_http_methods(["GET"])`; a POST is 405. No write/mutation endpoint exists.
- **Cross-department by design:** `hr_required` gates access, but department is a FILTER, not a security boundary -- HR sees all departments (unlike the department-scoped Dean surface).
- `templates/hr/attendance.html` (max-w-5xl, Pattern-A filter bar with faculty/department/term selects + date range + search, Pattern-C Export CSV anchor, Pattern-F empty + no-results states) + `templates/hr/_rows.html` (dense `uk-table` rows with semantic status pills).
- `web/urls.py`: `hr_attendance` + `hr_attendance_csv` routes added ALONGSIDE the Dean/IFO wiring (never overwritten). `web/views.py`: HR "Attendance" nav href moved off `#` to `/hr/attendance`.
- `web/tests_hr.py`: `HrGateTests`, `HrFilterTests`, `HrExportTests`, `HrReadOnlyTests` -- 14 tests, all green.

## Task Commits
1. **Task 1: hr_required gate + session-level attendance list with filters (HR-01/HR-02)** -- `d25dcdf` (feat)
2. **Task 2: streaming, injection-safe payroll CSV export (HR-03)** -- `6536c84` (feat)
3. **Task 3: HR gate, filters, export, read-only tests (HR-01/02/03)** -- `3cad8cb` (test)

## Threat Mitigations (from plan `<threat_model>`)
- **T-06-14 (Elevation of Privilege):** both views wrapped in `hr_required` (login + Role.HR_ADMIN, superuser bypass); a non-HR user is 403 -- proven by `HrGateTests.test_non_hr_refused_on_list` / `test_non_hr_refused_on_csv`.
- **T-06-02 (Tampering, CSV injection):** the export reuses `csv_safe` (not a reimplementation) so a `=cmd`-prefixed faculty name is prefixed with a single quote -- proven by `HrExportTests.test_csv_neutralizes_formula_name`.
- **T-06-03 (Denial of Service):** `StreamingHttpResponse` + `queryset.iterator()` bounds memory; the on-screen list is capped at `HR_PAGE_SIZE=200` (the full set is for the CSV).
- **T-06-15 (Tampering, MSSQL cursor):** no DB write inside the streaming generator; the checker-verified status is a pre-resolved `Exists()` annotation, so no subquery runs while the cursor streams.
- **T-06-16 (Input Validation):** `parse_date`-validated date filters, invalid input yields a friendly notice (never a 500), and every filter uses FK id + `date__range` (no `pk__in` list) -- proven by `HrFilterTests.test_invalid_date_is_friendly_not_500`.

## Decisions Made
- Annotated `is_verified` via `Exists()` instead of reading the `Session.verified_by_checker` property, because the property runs a per-object query that is fatal inside a streaming `.iterator()` generator on MSSQL (an open server-side cursor plus a fresh subquery = HY010). The annotation resolves in the main query.
- One shared `_filtered_sessions(request)` parser feeds both the list view and the CSV export so the exported rows can never diverge from the on-screen filters.
- Invalid date input degrades to a friendly inline notice and drops just that bound (a 200 with a note), never a 500; filters are ignored rather than raising.
- Every HR view is `@require_http_methods(["GET"])` so a POST is 405 -- the enforceable read-only guarantee, mirroring the 06-06 Dean surface.

## Deviations from Plan

None -- plan executed exactly as written. All three tasks landed as separate atomic commits (feat/feat/test) in plan order; every acceptance criterion, behavior, artifact, and prohibition was satisfied without a rule-triggered auto-fix.

_Test-authoring note (not a plan deviation): the filter-narrowing assertions check per-session **course codes** (which appear only in table rows) rather than faculty names or department codes, because the Pattern-A filter dropdowns echo every choice -- so a filtered-out faculty's name is still present in the page's `<option>` list. This makes the "narrows" assertions test the table, not the dropdown._

## Issues Encountered
- The full `web` suite shows the **same 3 pre-existing failures** documented in the 06-04 / 06-06 summaries (`DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`, `DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`, `HomeSurfaceNavTests.test_faculty_home_links_modality_request`) -- all dev-login / faculty-home-redirect issues, **verified pre-existing** (they fail on the committed Task 1+2 code and touch login/home, not HR). Out of scope, logged not fixed. The HR suite (`web.tests_hr`) is 14/14 green.

## User Setup Required
None -- no new dependencies, migrations, or external service configuration.

## Next Phase Readiness
- HR-01/02/03 delivered: the final reporting surface of Phase 06 (7/7 plans) is the cross-department, read-only session-level attendance list + streaming, injection-safe payroll CSV export.
- The streaming-export + shared-filter-parser + Exists-annotation patterns are available for any future large-export surface.
- No blockers.

## Self-Check: PASSED

- FOUND: web/hr.py
- FOUND: templates/hr/attendance.html
- FOUND: templates/hr/_rows.html
- FOUND: web/tests_hr.py
- FOUND: web/urls.py (hr_attendance + hr_attendance_csv)
- FOUND: web/views.py (/hr/attendance nav href)
- FOUND commit: d25dcdf (Task 1 feat)
- FOUND commit: 6536c84 (Task 2 feat)
- FOUND commit: 3cad8cb (Task 3 test)

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*
