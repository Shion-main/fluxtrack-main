---
phase: 06-reporting-engine-reporting-surfaces
plan: 04
subsystem: web
tags: [django, ifo, reporting, rpt-05, safe-card, drill-down, franken-ui, htmx-optional]

# Dependency graph
requires:
  - phase: 06-01
    provides: "scheduling/reporting.py aggregates (dept_summary, faculty_attendance, faculty_scorecard, safe_card) + make_reporting_fixture"
  - phase: 02-correctness-foundations
    provides: "Session.status truth (held/absent) the aggregates read"
provides:
  - "web/ifo.py: dashboard() + scorecard() views behind ifo_required (IFO-09, RPT-04)"
  - "templates/ifo/dashboard.html + templates/ifo/_cards.html: KPI card grid + per-faculty table + Pattern A filter"
  - "templates/reports/_error_card.html: shared RPT-05 generic per-card error partial (reused by 06-06)"
  - "templates/reports/scorecard.html: shared full-page faculty scorecard (reused by 06-06)"
  - "web/urls.py: ifo_dashboard + ifo_scorecard routes; web/views.py IFO Reports nav href"
affects: [06-06, dean-dashboard, ifo-dashboard, faculty-scorecard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "safe_card (value, error) pairs passed per-section into the template; each section includes the shared _error_card.html on error so one raising aggregate never blanks the page (RPT-05 end-to-end)"
    - "GET-filtered point-in-time dashboard (Pattern A From/To + Apply/Reset), NOT polled (A-POLL); invalid/reversed range degrades to the current reporting week with a friendly note (T-06-11)"
    - "as_of=today always clamps the denominator so a future not-yet-missed session never lowers attendance %"
    - "Drill-down as a full page (A-DRILL) carrying the active from/to; attendance pills via the existing --green/--amber/--red faculty.css tokens (A-COLOR >=90/75/<75)"
    - "Generic error copy only in the error card; raw exception text asserted absent from the response (T-06-04 info-disclosure)"

key-files:
  created:
    - "templates/reports/_error_card.html"
    - "templates/ifo/_cards.html"
    - "templates/ifo/dashboard.html"
    - "templates/reports/scorecard.html"
    - "web/tests_reporting.py"
  modified:
    - "web/ifo.py"
    - "web/urls.py"
    - "web/views.py"

key-decisions:
  - "The four KPI cards all derive from ONE safe_card(dept_summary) call; the per-faculty table is a SEPARATE safe_card(faculty_attendance) call, so patching dept_summary to raise proves per-card isolation end-to-end (KPI section errors, table section still renders)."
  - "Effective-modality breakdown keys (raw 'f2f'/'online'/'blended') are mapped to Modality.choices labels in the view, so the template renders human labels without a custom template filter."
  - "reporting_week_start policy ('monday') resolved via a weekday-index map; the default range is that weekday-of-this-week through today."

requirements-completed: [IFO-09, RPT-04, RPT-05]

coverage:
  - id: D1
    description: "IFO_ADMIN gets a 200 unscoped dashboard with the four KPI captions + faculty rows from both departments; a non-IFO user is refused 403"
    requirement: "IFO-09"
    verification:
      - kind: view-test
        ref: "web/tests_reporting.py::IfoDashboardTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Full-page faculty scorecard drill-down renders early-ends + effective-modality breakdown + itemized absences, carries the from/to range; non-IFO refused"
    requirement: "RPT-04"
    verification:
      - kind: view-test
        ref: "web/tests_reporting.py::ScorecardDrilldownTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "When one aggregate raises, the dashboard still returns 200, the failing section shows the generic error copy, the sibling section still renders, and the raw exception text is absent"
    requirement: "RPT-05"
    verification:
      - kind: view-test
        ref: "web/tests_reporting.py::CardIsolationViewTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "Invalid and reversed from/to ranges degrade to the default range with a friendly note, never a 500"
    requirement: "IFO-09"
    verification:
      - kind: view-test
        ref: "web/tests_reporting.py::FilterValidationTests"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 04: IFO-09 Reporting Dashboard + Scorecard Drill-down Summary

**An `ifo_required` unscoped reporting dashboard renders KPI summary cards + a per-faculty table over a selectable range through `safe_card` pairs, with a full-page faculty scorecard drill-down; a raising aggregate errors in its own card while the rest of the page renders (RPT-05), and invalid dates degrade to the current reporting week — 7 view-level tests green.**

## Performance
- **Duration:** ~20 min
- **Completed:** 2026-07-15
- **Tasks:** 3 (all `auto`)
- **Files:** 8 (5 created, 3 modified)

## Accomplishments
- `web/ifo.py`: `dashboard(request)` and `scorecard(request, faculty_id)` behind `ifo_required`, plus a shared `_reporting_range()` helper that parses `from`/`to`, defaults to the current reporting week (via the `reporting_week_start` policy), and returns a friendly note on invalid/reversed input instead of raising.
- Both views consume the REAL 06-01 aggregate signatures (`dept_summary`, `faculty_attendance`, `faculty_scorecard`) through `safe_card`, passing per-section `(value, error)` pairs into the templates; `as_of=today` always clamps the denominator.
- `templates/reports/_error_card.html`: the shared RPT-05 error partial (UI-SPEC Pattern E) — generic copy only, never the raw exception.
- `templates/ifo/dashboard.html` + `templates/ifo/_cards.html`: the Pattern A GET filter bar (From/To + Apply/Reset), the four KPI cards (Faculty, Sessions held/scheduled, Absences, Attendance %) in the `grid gap-4 sm:grid-cols-2 lg:grid-cols-3` idiom, and the per-faculty `uk-table` with Pattern D drill-down links.
- `templates/reports/scorecard.html`: the shared full-page scorecard (back button carrying the range, KPI cards, effective-modality breakdown, itemized absences) reused by the Dean surface in 06-06.
- Attendance pills use the existing `--green/--amber/--red` `faculty.css` tokens at the A-COLOR thresholds (>=90 / 75-89 / <75).
- `web/urls.py`: `ifo_dashboard` and `ifo_scorecard` routes; `web/views.py`: IFO "Reports" nav href moved off `#` to `/ifo/dashboard`.
- `web/tests_reporting.py`: `IfoDashboardTests`, `ScorecardDrilldownTests`, `CardIsolationViewTests`, `FilterValidationTests` (7 tests) — all green.

## Task Commits
1. **Task 1: IFO-09 dashboard + KPI cards + Pattern A filter + Pattern E error card** — `88c9b71` (feat)
2. **Task 2: faculty scorecard drill-down (full page)** — `0817e48` (feat)
3. **Task 3: view-level tests (dashboard/drill-down/isolation/validation)** — `272faa1` (test)

## Threat Mitigations (from plan `<threat_model>`)
- **T-06-10 (Elevation of Privilege):** both views wrapped in `ifo_required`; non-IFO → 403, asserted in `IfoDashboardTests.test_non_ifo_refused` and `ScorecardDrilldownTests.test_non_ifo_refused`.
- **T-06-04 (Information Disclosure):** the error card renders fixed generic copy; `CardIsolationViewTests` patches an aggregate to raise with a secret marker and asserts the marker is ABSENT from the response.
- **T-06-11 (Input Validation):** `parse_date`-validated `from`/`to`; invalid and reversed ranges fall back to the current week with a note, asserted 200 (never 500) in `FilterValidationTests`.

## Decisions Made
- KPI cards all derive from a single `safe_card(dept_summary)`; the faculty table is a separate `safe_card(faculty_attendance)` — this is what makes the RPT-05 isolation test meaningful (patch `dept_summary`, the table still renders).
- Modality-breakdown raw keys are mapped to `Modality.choices` labels in the view (no custom template filter needed).
- The scorecard drill-down link was added to `_cards.html` in Task 2 (not Task 1) so the `ifo_scorecard` reverse existed before the link referenced it — avoids a `NoReverseMatch` in the Task-1 render path.

## Deviations from Plan
None — plan executed exactly as written. All planned artifacts, symbols, routes, nav change, and four test classes delivered; per-card isolation proven end-to-end.

## Issues Encountered
- The full `web` suite shows **3 pre-existing failures** (`DevLoginCoexistTests`, `DevLoginCuratedDemoTests.test_garay_dev_login...`, `HomeSurfaceNavTests.test_faculty_home_links_modality_request`) — all dev-login/home-redirect 302-vs-200 issues. **Verified pre-existing** at commit `ea3afb2` (before any 06-04 change) by checking out that commit and re-running: same 3 failures. Out of scope for this plan (logged, not fixed).
- The `RuntimeError: KABOOM_SECRET_TRACE_12345` traceback printed during the run is the intentional `safe_card` `logger.exception` output from `CardIsolationViewTests` — not a test failure.

## User Setup Required
None — no new dependencies, migrations, or external service configuration.

## Next Phase Readiness
- `templates/reports/_error_card.html` and `templates/reports/scorecard.html` are the shared partials 06-06 (Dean surface) reuses.
- The `safe_card` per-section rendering idiom and the `_reporting_range()` filter helper are established for the Dean/HR surfaces.
- No blockers.

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*

## Self-Check: PASSED
- Files: web/ifo.py, web/urls.py, web/views.py, templates/ifo/dashboard.html, templates/ifo/_cards.html, templates/reports/_error_card.html, templates/reports/scorecard.html, web/tests_reporting.py, 06-04-SUMMARY.md all present.
- Commits: 88c9b71, 0817e48, 272faa1 all in history.
- Tests: web.tests_reporting 7/7 OK. The 3 web-suite failures are pre-existing (verified at ea3afb2), unrelated to this plan.
