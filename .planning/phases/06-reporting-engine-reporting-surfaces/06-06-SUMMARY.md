---
phase: 06-reporting-engine-reporting-surfaces
plan: 06
subsystem: web
tags: [django, dean, reporting, dean-04, idor, bola, read-only, csv-injection, franken-ui]

# Dependency graph
requires:
  - phase: 06-01
    provides: "scheduling/reporting.py aggregates (dept_summary, faculty_attendance, faculty_scorecard, safe_card) + make_reporting_fixture"
  - phase: 06-03
    provides: "scheduling/report_render.py build_csv/build_pdf pure byte renderers + csv_safe neutralizer"
  - phase: 06-04
    provides: "templates/reports/_error_card.html + templates/reports/scorecard.html shared partials; web.ifo._reporting_range pattern"
  - phase: 06-05
    provides: "ops/reports.py weekly report storage + WeeklyReport rows with populated csv_path/pdf_path"
provides:
  - "web/dean.py: dashboard(), reports(), scorecard(), report_export(), weekly_download() -- all dean_required + GET-only + department-scoped"
  - "templates/dean/dashboard.html + templates/dean/reports.html (reuse reports/_error_card.html + reports/scorecard.html)"
  - "web/urls.py Dean reporting routes; web/views.py Dean 'Department oversight' nav href"
  - "web/tests_dean_reporting.py: DeanDashboardTests, DeanScopeTests, DeanExportTests, ReadOnlyTests"
affects: [dean-reporting-surface, dean-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Department-scoped-by-identity: every Dean queryset scopes to request.user.department SERVER-SIDE; scorecard + weekly_download use get_object_or_404(..., department=request.user.department) so a foreign-department id 404s (T-06-01 IDOR/BOLA, refused not hidden)"
    - "Read-only surface via @require_http_methods(['GET']) on every reporting view -> a POST is 405 (DEAN-01 / T-06-07); the dean_required gate stays outermost so role is checked before method"
    - "NULL-department Dean edge case: a zeroed DeptSummary + empty table, NEVER dept_summary(department=None) which would leak an ALL-departments roll-up"
    - "Ad-hoc export reuses build_csv/build_pdf (csv_safe intact); stored-report download streams default_storage bytes for a WeeklyReport scoped to the Dean's department"
    - "Shared reports/scorecard.html back link parameterized via back_url (default /ifo/dashboard) so a Dean is never sent to the IFO-only route"

key-files:
  created:
    - "templates/dean/dashboard.html"
    - "templates/dean/reports.html"
    - "web/tests_dean_reporting.py"
  modified:
    - "web/dean.py"
    - "web/urls.py"
    - "web/views.py"
    - "templates/reports/scorecard.html"

key-decisions:
  - "Every Dean reporting view is GET-only via @require_http_methods(['GET']); a POST returns 405 -- this is what makes ReadOnlyTests (DEAN-01) enforceable, since a bare Django view otherwise accepts any method."
  - "A NULL-department Dean gets a zeroed DeptSummary + empty table (nothing scoped in), never an unscoped dept_summary(department=None) ALL-departments roll-up -- closes an accidental cross-department leak on the edge case."
  - "The shared reports/scorecard.html back link was parameterized (back_url, default /ifo/dashboard) so the Dean scorecard returns to /dean/reports instead of the IFO-only dashboard -- the only change needed to reuse the 06-04 template."

requirements-completed: [DEAN-01, DEAN-02, DEAN-03, DEAN-04, RPT-03]

coverage:
  - id: D1
    description: "A DEAN with a department gets a 200 department-scoped dashboard (four KPI captions + a latest-report card / empty state); a non-Dean is refused 403"
    requirement: "DEAN-04"
    verification:
      - kind: view-test
        ref: "web/tests_dean_reporting.py::DeanDashboardTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "A Dean requesting a foreign-department scorecard or weekly_download gets 404 server-side; a foreign faculty never appears in the Dean's report/export; own department works"
    requirement: "DEAN-01"
    verification:
      - kind: view-test
        ref: "web/tests_dean_reporting.py::DeanScopeTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "report_export csv/pdf are attachments over the shared render layer; a formula-triggering faculty name is csv_safe-neutralized; unknown fmt 404s"
    requirement: "DEAN-03"
    verification:
      - kind: view-test
        ref: "web/tests_dean_reporting.py::DeanExportTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "A POST to any Dean reporting URL (dashboard/reports/export/scorecard/weekly_download) is rejected 405 -- read-only surface"
    requirement: "DEAN-01"
    verification:
      - kind: view-test
        ref: "web/tests_dean_reporting.py::ReadOnlyTests"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 06: Dean Reporting Surface (DEAN-01..04 / RPT-03) Summary

**A `dean_required`, strictly department-scoped, read-only Dean reporting surface — a DEAN-04 dashboard (four KPI cards + latest-weekly-report card), a per-faculty report (DEAN-02), a full-page scorecard drill-down, and CSV/PDF export + stored-report download (DEAN-03/RPT-03) — where every queryset is scoped to `request.user.department` server-side so a crafted faculty_id / report pk 404s (T-06-01 IDOR/BOLA) and every view is GET-only so a POST is 405 (DEAN-01); reuses the shared aggregate/render/template layers, 12 view-tests green.**

## Performance
- **Duration:** ~20 min
- **Completed:** 2026-07-15
- **Tasks:** 3 (all `auto`)
- **Files:** 6 (3 created, 3 modified) + 1 shared template touched

## Accomplishments
- `web/dean.py`: `dashboard()`, `reports()`, `scorecard(faculty_id)`, `report_export(fmt)`, `weekly_download(pk, fmt)` — all behind `dean_required` **and** `@require_http_methods(["GET"])`, all scoped to `request.user.department`.
- A local `_reporting_range()` (mirroring `web.ifo._reporting_range`, deliberately NOT imported across role modules) parses `from`/`to`, defaults to the reporting-week-start-of-week..today, and degrades invalid/reversed ranges to a friendly note (never a 500); `as_of=today` always clamps the denominator.
- **IDOR/BOLA (T-06-01):** `scorecard` and `weekly_download` use `get_object_or_404(..., department=request.user.department)` so a foreign-department faculty/report id is refused **server-side** with a 404, never merely hidden. `reports`/`report_export` scope `faculty_attendance` to the Dean's department so a foreign faculty is never in the result set.
- **Read-only (DEAN-01 / T-06-07):** every reporting view is GET-only; a POST returns 405. No write/mutation endpoint exists on the surface.
- **Export (DEAN-03/RPT-03):** `report_export` reuses `build_csv`/`build_pdf` (so `csv_safe` formula-neutralization is intact) and returns an attachment `HttpResponse`; `weekly_download` streams the stored `WeeklyReport` csv/pdf from `default_storage` (missing file/path → 404, never a 500).
- **Templates:** `templates/dean/dashboard.html` (max-w-2xl, 4 KPI cards via `safe_card` + shared `_error_card.html`, latest-weekly-report card with a calm Pattern F empty state) and `templates/dean/reports.html` (max-w-4xl, Pattern A filter bar, department-scoped `uk-table` linking to the Dean scorecard, Pattern C export anchors).
- `templates/reports/scorecard.html`: back link parameterized via `back_url` (default `/ifo/dashboard`) so the Dean scorecard returns to `/dean/reports` — the only change needed to reuse the 06-04 shared template.
- `web/urls.py`: `dean_dashboard`, `dean_reports`, `dean_report_export`, `dean_scorecard`, `dean_weekly_download` routes. `web/views.py`: Dean "Department oversight" nav href moved off `#` to `/dean/dashboard`.
- `web/tests_dean_reporting.py`: `DeanDashboardTests`, `DeanScopeTests`, `DeanExportTests`, `ReadOnlyTests` — 12 tests, all green.

## Task Commits
1. **Task 1: Dean department-scoped dashboard + latest-weekly-report card (DEAN-04/DEAN-01)** — `4afe804` (feat)
2. **Task 2: Dean report view + scorecard + CSV/PDF export + stored-report download (DEAN-02/DEAN-03/RPT-03)** — `1280f58` (feat)
3. **Task 3: security + behavior tests (DEAN-01..04)** — `62e4157` (test)

## Threat Mitigations (from plan `<threat_model>`)
- **T-06-01 (Elevation of Privilege, BOLA/IDOR):** every Dean queryset filtered by `request.user.department`; `scorecard` + `weekly_download` use `get_object_or_404(..., department=request.user.department)` so a foreign-department id 404s server-side — proven by `DeanScopeTests.test_foreign_department_scorecard_404s`, `test_foreign_department_weekly_download_404s`, `test_report_excludes_foreign_faculty`, `test_export_excludes_foreign_faculty`.
- **T-06-07 (Tampering, read-only):** no write endpoint exists; every reporting view is GET-only; `ReadOnlyTests` asserts POST → 405 on all five routes.
- **T-06-02 (Tampering, CSV injection):** export reuses `build_csv`, whose `csv_safe` neutralizes a formula-triggering name cell — proven by `DeanExportTests.test_csv_export_is_attachment_and_neutralizes_formula` (a `=cmd`-prefixed faculty name is prefixed with a single quote).
- **T-06-13 (Access Control):** all views wrapped in `dean_required` (login_required + Role.DEAN, superuser bypass); non-Dean → 403, asserted in `DeanDashboardTests.test_non_dean_refused`.

## Decisions Made
- Every Dean reporting view is GET-only via `@require_http_methods(["GET"])`; a bare Django view otherwise accepts any method, so this decorator is what makes the DEAN-01 read-only guarantee enforceable (POST → 405).
- A NULL-department Dean gets a zeroed `DeptSummary` + empty table, never `dept_summary(department=None)` — that would render an unscoped ALL-departments roll-up and leak cross-department data on the edge case.
- Parameterized the shared `reports/scorecard.html` back link (`back_url`, default `/ifo/dashboard`) so the Dean drill-down returns to `/dean/reports` instead of sending a Dean to an IFO-only route (which would 403).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Parameterized the shared scorecard back link**
- **Found during:** Task 2
- **Issue:** `templates/reports/scorecard.html` (created by 06-04) hardcoded the back link to `/ifo/dashboard`. Reusing it for the Dean scorecard would send a Dean to an IFO-only route (403 on click).
- **Fix:** Changed the back `href` to `{{ back_url|default:'/ifo/dashboard' }}`; the Dean `scorecard` view passes `back_url="/dean/reports"`, and the IFO view (which passes nothing) keeps its `/ifo/dashboard` default. Non-breaking — the existing 7 IFO reporting tests remain green.
- **Files modified:** templates/reports/scorecard.html, web/dean.py
- **Commit:** 1280f58

**2. [Rule 2 - Missing critical guard] NULL-department Dean cross-department leak**
- **Found during:** Task 1
- **Issue:** Calling `dept_summary(department=None)` for a Dean whose `department` is NULL would aggregate ALL departments (an unscoped roll-up), violating DEAN-01 on the edge case the plan flagged (assumption: "empty, no-crash dashboard").
- **Fix:** When `request.user.department is None`, the dashboard/report short-circuit to a zeroed `DeptSummary` / empty rows instead of an unscoped aggregate call.
- **Files modified:** web/dean.py
- **Commit:** 4afe804

## Issues Encountered
- The full `web` suite still shows the **same pre-existing failures** documented in the 06-04 summary (dev-login / home-redirect 302-vs-200 issues, e.g. `HomeSurfaceNavTests.test_faculty_home_links_modality_request`). **Verified pre-existing** (unrelated to this plan — they concern the faculty home redirect, not the Dean surface; no Dean nav test exists). Out of scope, logged not fixed.

## User Setup Required
None — no new dependencies, migrations, or external service configuration.

## Next Phase Readiness
- The Dean reporting surface is the department-scoped, read-only consumer of the shared aggregate/render/template layers; the IDOR-safe + read-only patterns are established for the HR surface (06-07).
- `back_url` parameterization on `reports/scorecard.html` keeps the shared scorecard reusable by any future role surface.
- No blockers.

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*

## Self-Check: PASSED
