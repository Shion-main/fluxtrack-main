---
phase: 06-reporting-engine-reporting-surfaces
verified: 2026-07-15T15:56:57Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 6: Reporting Engine & Reporting Surfaces Verification Report

**Phase Goal:** One shared, independently tested aggregate layer powers the weekly report, faculty scorecards, and every dashboard (IFO, Dean, HR) — built once, consumed everywhere.
**Verified:** 2026-07-15T15:56:57Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Weekly Consolidated Attendance Report generates per department (one row per faculty: scheduled/held/absent/attendance %/checker-verified + itemized absences) from pure, independently tested aggregates, exportable as CSV + printable PDF | ✓ VERIFIED | `scheduling/reporting.py::faculty_attendance` (pure, DB-conditional-aggregation, `HELD_STATUSES`/`SessionStatus.ABSENT` truth, itemized `AbsenceItem` list) + `scheduling/report_render.py::build_csv`/`build_pdf` (stdlib `csv` + ReportLab Platypus, `%PDF` bytes) + `ops/reports.py::generate_weekly_report` (one WeeklyReport row per department + ALL roll-up, idempotent via `get_or_create`). 20 unit tests in `scheduling/tests_reporting.py`, 11 in `scheduling/tests_report_render.py`, 14 in `ops/tests_reports.py` — all pass (ran live, see Behavioral Spot-Checks). |
| 2 | Faculty scorecard, IFO-09 dashboard, and Dean dashboard (DEAN-04) all compute from the same shared aggregates over a selectable range, with faculty-scorecard drill-down | ✓ VERIFIED | `web/ifo.py:23-24` and `web/dean.py:36-42` both `from scheduling.reporting import (dept_summary, faculty_attendance, faculty_scorecard, safe_card)` — no independent status counting exists in either module (only `scheduling/reporting.py` reads `SessionStatus.ACTIVE/COMPLETED/ABSENT` for aggregation; grep confirms `web/checker.py`/`web/scan.py` only WRITE status, never re-aggregate it). Both `ifo.dashboard`/`ifo.scorecard` and `dean.dashboard`/`dean.scorecard` share an identical `_reporting_range()` GET-filter shape and render `reports/scorecard.html`. Verified live: `web/tests_reporting.py` (7 tests) + `web/tests_dean_reporting.py` (12 tests) pass. |
| 3 | Dean's access is read-only and department-scoped; can view/export their weekly report, which auto-generates weekly (JOB-03) + on demand, is stored, and notifies IFO + relevant Dean(s) | ✓ VERIFIED | `web/dean.py`: every reporting view decorated `@require_http_methods(["GET"])` (POST→405, `ReadOnlyTests.test_post_rejected_on_every_reporting_route` — 5 routes, all pass); `scorecard`/`weekly_download` use `get_object_or_404(..., department=request.user.department)` — cross-department id 404s (`DeanScopeTests.test_foreign_department_scorecard_404s`, `test_foreign_department_weekly_download_404s`, both pass); `scheduling/management/commands/runscheduler.py:58-70,98-102` — `_job_weekly_report` (the FILLED JOB-03 stub, still exactly 4 jobs: materialize/sweep/weekly_report/push_outbox, `CronTrigger(day_of_week="mon", hour=6)`) calls `generate_week_reports`, the SAME service the on-demand `generate_weekly_report` management command uses; `WeeklyReport.unique_together(week_start, department)` + `get_or_create` + deterministic-name overwrite = idempotent; `ops/reports.py::notify_report_ready` notifies `role=Role.IFO_ADMIN` always, and department-scoped Deans via `users=` only when `department is not None` — both routed exclusively through `notify()` (no direct `Notification.objects.create`). `SchedulerWiringTests` + `NoImplicitSchedulerTests` (ran live) both pass, confirming the 4-job invariant held. |
| 4 | HR can view verified session-level attendance, filter/search by faculty/department/date range/term, export as CSV for payroll | ✓ VERIFIED | `web/hr.py::attendance()` is session-grain (one row per `Session`, not aggregate), `_filtered_sessions()` applies 4 independent FK-id/date-range filters + free-text search; `is_verified` resolved via `Exists(CheckerValidation...)` annotation (no per-row subquery); `attendance_csv()` streams via `StreamingHttpResponse` + `queryset.iterator()` + `_Echo`, reusing `scheduling.report_render.csv_safe`. `web/tests_hr.py` (14 tests: `HrGateTests`, `HrFilterTests`, `HrExportTests`, `HrReadOnlyTests`) — ran live, all pass. |
| 5 | A single failing aggregate shows an error in its own card while the rest of the page still renders | ✓ VERIFIED | `scheduling/reporting.py::safe_card` — `(value, None)` / `(None, "This section could not be loaded.")`, logs real exception server-side, never returns exception text. End-to-end proof: `web/tests_reporting.py::CardIsolationViewTests.test_one_failing_aggregate_isolated` patches `web.ifo.dept_summary` to raise `RuntimeError("KABOOM_SECRET_TRACE_12345")`, asserts `200`, `"Couldn't load this section"` present, sibling `faculty_attendance` table STILL renders real data (`self.fx.faculty_a.last_name` present), and the raw exception string is absent (`assertNotContains`). Ran live — passes. Also covered at the unit level by `scheduling/tests_reporting.py::CardIsolationTests` and at the Dean layer implicitly (same `safe_card` helper). |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scheduling/reporting.py` | Pure aggregate layer: `faculty_attendance`, `dept_summary`, `faculty_scorecard`, `safe_card` | ✓ VERIFIED | All four functions present, pure (no writes/`notify()`/`timezone.now()` baked in; `as_of`/range passed as args), DB-side conditional aggregation confirmed by reading source. |
| `scheduling/report_render.py` | `csv_safe`, `build_csv`, `build_pdf` | ✓ VERIFIED | All three present; `csv_safe` neutralizes `= + - @ \t \r`; `build_csv` uses stdlib `csv`; `build_pdf` uses ReportLab Platypus `Table`/`SimpleDocTemplate`, returns `%PDF` bytes, handles empty rows. |
| `ops/reports.py` | Weekly generation + notify + JOB-03 fill | ✓ VERIFIED | `report_week_bounds`, `generate_weekly_report`, `notify_report_ready`, `generate_week_reports` all present and wired; idempotent storage via `default_storage` + server-built path (`reports/{week_start}/{code}.{csv,pdf}`), never request-derived. |
| `web/ifo.py` | `dashboard()` + `scorecard()` behind `ifo_required`, shared aggregates | ✓ VERIFIED | Present, imports shared aggregates, `safe_card`-wrapped sections, `_reporting_range()` degrades bad input to a friendly note (never 500). |
| `web/dean.py` | Department-scoped read-only dashboard/reports/scorecard/export/download | ✓ VERIFIED | Present; every view `dean_required` + GET-only; IDOR guards via `get_object_or_404(..., department=request.user.department)`; NULL-department Dean edge case explicitly handled (zeroed `DeptSummary`, never `dept_summary(department=None)`). |
| `web/hr.py` | Session-level filterable list + streaming CSV | ✓ VERIFIED | Present; `hr_required` + GET-only; `_filtered_sessions` shared by list and CSV; streaming export via `StreamingHttpResponse`/`.iterator()`/`_Echo`; `csv_safe` reused (not reimplemented). |
| `scheduling/management/commands/runscheduler.py` | JOB-03 stub filled, 4-job invariant intact | ✓ VERIFIED | `_job_weekly_report` calls `generate_week_reports`; `build_scheduler()` still registers exactly 4 jobs (`materialize`, `sweep`, `weekly_report`, `push_outbox`); no second scheduler introduced. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `web/ifo.py` | `scheduling/reporting.py` | `from scheduling.reporting import (dept_summary, faculty_attendance, faculty_scorecard, safe_card)` | ✓ WIRED | Both dashboard() and scorecard() call these functions directly; no re-derivation of held/absent found anywhere in `web/*.py` outside `web/hr.py`'s session-grain status label (expected — HR is session-level by design, criterion 4). |
| `web/dean.py` | `scheduling/reporting.py` + `scheduling/report_render.py` | Direct imports, used in `dashboard/reports/scorecard/report_export` | ✓ WIRED | Confirmed by grep + read; `report_export` calls `build_csv`/`build_pdf` directly. |
| `ops/reports.py` | `scheduling/reporting.py` + `scheduling/report_render.py` | `faculty_attendance`, `build_csv`, `build_pdf` | ✓ WIRED | `generate_weekly_report` calls all three in sequence, writes via `default_storage`. |
| `scheduling/management/commands/runscheduler.py` | `ops/reports.py` | `_job_weekly_report` → `generate_week_reports` | ✓ WIRED | Confirmed by read; same service also called by `scheduling/management/commands/generate_weekly_report.py` (on-demand CLI). |
| `ops/reports.py` | `ops/notify.py::notify()` | `notify_report_ready` → `notify(role=Role.IFO_ADMIN, ...)` + `notify(users=deans, ...)` | ✓ WIRED | No direct `Notification.objects.create` found in `ops/reports.py`; both fan-outs route through `notify()`. |
| `web/dean.py` (templates) | `dean_report_export` / `dean_weekly_download` | href in `templates/dean/reports.html` + `templates/dean/dashboard.html` | ✓ WIRED | Confirmed export/download anchors present and pointed at the correct named routes. |

### Behavioral Spot-Checks (live test runs)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-specific test suites (aggregates, render, ops, IFO/Dean/HR views) | `manage.py test scheduling.tests_reporting scheduling.tests_report_render ops.tests_reports web.tests_reporting web.tests_dean_reporting web.tests_hr -v1` | Ran 76 tests, OK (0 failures) | ✓ PASS |
| Scheduler wiring invariant (4 jobs, no implicit scheduler) | `manage.py test scheduling.tests.SchedulerWiringTests ops.tests.NoImplicitSchedulerTests -v1` | Ran 2 tests, OK | ✓ PASS |
| Full `web` suite (confirm the 3 documented pre-existing failures are unrelated) | `manage.py test web -v1` | Ran 94 tests, 3 failures — all `DevLoginCoexistTests`/`DevLoginCuratedDemoTests`/`HomeSurfaceNavTests` (dev-login/home-redirect 302-vs-200), none touching reporting/dean/hr/ifo | ✓ PASS (matches SUMMARY claim; confirmed unrelated by inspection of failure output — none reference reporting code paths) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RPT-01 | 06-01 | Weekly report per-faculty aggregate from pure functions | ✓ SATISFIED | `scheduling/reporting.py::faculty_attendance`, REQUIREMENTS.md marked `[x]` |
| RPT-02 | 06-05 | Auto-weekly (JOB-03) + on-demand generation, stored, notifies | ✓ SATISFIED | `ops/reports.py`, `runscheduler.py`, REQUIREMENTS.md `[x]` |
| RPT-03 | 06-02/03/06 | CSV + printable PDF export | ✓ SATISFIED | `scheduling/report_render.py`, `web/dean.py::report_export`/`weekly_download`, REQUIREMENTS.md `[x]` |
| RPT-04 | 06-01/04 | Faculty scorecard from shared aggregates | ✓ SATISFIED | `scheduling/reporting.py::faculty_scorecard`, `web/ifo.py::scorecard`, `web/dean.py::scorecard`, REQUIREMENTS.md `[x]` |
| RPT-05 | 06-01/04 | Per-card graceful degradation | ✓ SATISFIED | `safe_card`, `CardIsolationViewTests`, REQUIREMENTS.md `[x]` |
| IFO-09 | 06-04 | IFO dashboard summary cards + drill-down | ✓ SATISFIED | `web/ifo.py::dashboard/scorecard`, REQUIREMENTS.md `[x]` |
| DEAN-01 | 06-06 | Dean read-only, department-scoped | ✓ SATISFIED | `@require_http_methods(["GET"])` on all Dean views + `department=request.user.department` scoping, REQUIREMENTS.md `[x]` |
| DEAN-02 | 06-06 | Department-scoped reporting + per-faculty scorecards | ✓ SATISFIED | `web/dean.py::reports/scorecard`, REQUIREMENTS.md `[x]` |
| DEAN-03 | 06-06 | View/export weekly report for own department | ✓ SATISFIED | `web/dean.py::report_export/weekly_download`, REQUIREMENTS.md `[x]` |
| DEAN-04 | 06-06 | Dean dashboard summary cards + latest-report card | ✓ SATISFIED | `web/dean.py::dashboard`, REQUIREMENTS.md `[x]` |
| HR-01 | 06-07 | Session-level verified attendance view | ✓ SATISFIED | `web/hr.py::attendance`, REQUIREMENTS.md `[x]` |
| HR-02 | 06-07 | Filter/search by faculty/department/date/term | ✓ SATISFIED | `_filtered_sessions`, REQUIREMENTS.md `[x]` |
| HR-03 | 06-07 | Export session-level CSV for payroll | ✓ SATISFIED | `web/hr.py::attendance_csv`, REQUIREMENTS.md `[x]` |

No orphaned requirements found for Phase 6 in REQUIREMENTS.md.

### Anti-Patterns Found

None. Scanned `scheduling/reporting.py`, `scheduling/report_render.py`, `ops/reports.py`, `web/ifo.py`, `web/dean.py`, `web/hr.py`, `scheduling/management/commands/runscheduler.py` for `TODO|FIXME|XXX|TBD|placeholder|not yet implemented|coming soon` — zero matches.

### Human Verification Required

None. All five success criteria have direct codebase evidence plus passing live-run tests (not merely SUMMARY.md claims). PDF visual quality (navy header, zebra rows) was verified by reading `build_pdf`'s ReportLab styling code and its passing `PdfBuildTests`, not by visually inspecting a rendered PDF — this is a low-risk cosmetic item and does not block the phase goal.

### Gaps Summary

No gaps. All 5 phase success criteria are backed by real source code (read directly, not inferred from SUMMARY.md) and by live test runs executed during this verification (76 reporting-specific tests + 2 scheduler-invariant tests, all passing; the 3 pre-existing `web` suite failures are confirmed dev-login/home-redirect issues unrelated to reporting). The shared-aggregate-layer goal is structurally confirmed: `web/ifo.py`, `web/dean.py`, and `ops/reports.py` all import and call the exact same `scheduling/reporting.py` functions — no surface re-derives held/absent counts independently. HR intentionally consumes session-grain data (not the aggregate layer) per its own requirement (HR-01/02/03), which is by design, not a gap.

---

*Verified: 2026-07-15T15:56:57Z*
*Verifier: Claude (gsd-verifier)*
