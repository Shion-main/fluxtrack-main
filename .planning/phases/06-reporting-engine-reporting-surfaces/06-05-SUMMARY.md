---
phase: 06-reporting-engine-reporting-surfaces
plan: 05
subsystem: reporting
tags: [django, apscheduler, default_storage, reportlab, notifications, mssql]

# Dependency graph
requires:
  - phase: 06-01
    provides: faculty_attendance aggregate (FacultyRow list) + make_reporting_fixture
  - phase: 06-03
    provides: build_csv / build_pdf pure byte renderers + csv_safe
  - phase: 05-03
    provides: WEEKLY_REPORT_READY push contract + notify() single write path
provides:
  - "ops/reports.py: report_week_bounds(), generate_weekly_report(), notify_report_ready(), generate_week_reports()"
  - "Filled JOB-03 (_job_weekly_report) generating the prior week's per-department + ALL roll-up reports"
  - "On-demand generate_weekly_report management command reusing the same service"
  - "WeeklyReport rows stored idempotently via default_storage under server-built paths"
affects: [06-06, 06-07, dean-reporting-surface, ifo-dashboard, hr-views]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Orchestration layer (ops/reports.py) over the pure aggregate + render layers; one shared service behind auto-weekly job and on-demand CLI"
    - "Idempotent artifact generation via get_or_create on unique_together + deterministic overwrite of default_storage names"
    - "Timezone-correct weekly bounds on local Session.date (report_week_bounds pure fn), never UTC scheduled_start"

key-files:
  created:
    - ops/reports.py
    - ops/tests_reports.py
    - scheduling/management/commands/generate_weekly_report.py
  modified:
    - scheduling/management/commands/runscheduler.py

key-decisions:
  - "Added generate_week_reports() orchestrator in ops/reports.py so JOB-03 and the on-demand command share one generation path (no duplicated logic)"
  - "report_week_bounds returns the week CONTAINING its argument; callers pass localdate()-7 days to target the prior completed week"
  - "Deterministic-name overwrite (_save_overwrite deletes before save) keeps csv_path/pdf_path canonical across regenerations"

patterns-established:
  - "Pattern 1: server-built storage names (reports/{week_start}/{code}.{ext}) derived only from department.code + week_start (T-06-05 path-traversal control)"
  - "Pattern 2: department fan-out from a Session.date filter (values_list distinct), never a large PK IN list (MSSQL 2100-param safety)"
  - "Pattern 3: report-ready notification exclusively through notify(); IFO via role, Deans via department-filtered users= (T-06-06 scoping)"

requirements-completed: [RPT-02]

coverage:
  - id: D1
    description: "generate_weekly_report() idempotently writes CSV+PDF via default_storage and upserts one WeeklyReport row per (week_start, department)"
    requirement: "RPT-02"
    verification:
      - kind: unit
        ref: "ops/tests_reports.py#IdempotencyTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "notify_report_ready() notifies IFO + only the report's department Dean(s) through notify() (NOTIF-00 / T-06-06)"
    requirement: "RPT-02"
    verification:
      - kind: unit
        ref: "ops/tests_reports.py#NotifyTargetingTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "report_week_bounds() returns Monday..Sunday local dates; Sunday included, next Monday excluded (Pitfall 1)"
    requirement: "RPT-02"
    verification:
      - kind: unit
        ref: "ops/tests_reports.py#WeekBoundaryTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "Filled JOB-03 + on-demand command generate the prior week's per-dept + ALL reports with a positive count, idempotently, preserving the 4-job scheduler invariant (ENV-04)"
    requirement: "RPT-02"
    verification:
      - kind: unit
        ref: "ops/tests_reports.py#JobFillTests"
        status: pass
      - kind: unit
        ref: "scheduling/tests.py#SchedulerWiringTests"
        status: pass
      - kind: unit
        ref: "ops/tests.py#NoImplicitSchedulerTests"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 5: Weekly Report Generation, Storage & Notification Summary

**RPT-02 weekly consolidated report: idempotent per-department + ALL roll-up generation stored via default_storage, notifying IFO + scoped Deans through notify(), driven by the filled JOB-03 slot and a matching on-demand command — with the 4-job single-scheduler invariant intact.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-15
- **Completed:** 2026-07-15
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- `ops/reports.py` service: `report_week_bounds()` (pure local Mon–Sun), `generate_weekly_report()` (idempotent `get_or_create` + `default_storage` server-built path), `notify_report_ready()` (IFO role + department-scoped Deans via `notify()`), and a `generate_week_reports()` orchestrator shared by both entry points.
- Filled the reserved JOB-03 `_job_weekly_report()` stub to generate the prior completed week's reports and return a meaningful count for `JobRun.rows_affected` — **no second scheduler and no new job**.
- Added the on-demand `manage.py generate_weekly_report` command (optional `--week`), reusing the exact same service so auto-weekly and on-demand can never diverge; ASCII-only summary output.
- 14 tests green across the report service, scheduler-wiring invariant, and implicit-scheduler guard.

## Task Commits

Each task was committed atomically:

1. **Task 1: Weekly report generation service + report-ready notify** - `d112fa4` (feat)
2. **Task 2: Fill JOB-03 stub + on-demand command, preserving the 4-job invariant** - `40b651d` (feat)

## Files Created/Modified
- `ops/reports.py` - Generation/storage/notification orchestration over the pure aggregate + render layers (RPT-02).
- `ops/tests_reports.py` - IdempotencyTests, NotifyTargetingTests, WeekBoundaryTests, JobFillTests.
- `scheduling/management/commands/runscheduler.py` - `_job_weekly_report` body filled; job set unchanged (still materialize/sweep/weekly_report/push_outbox).
- `scheduling/management/commands/generate_weekly_report.py` - On-demand CLI reusing `generate_week_reports`.

## Decisions Made
- **Shared orchestrator (`generate_week_reports`)** placed in `ops/reports.py` rather than inlined in the job body, so the auto-weekly job and the on-demand command call one code path — satisfies the plan's "do not duplicate generation logic" directive.
- **`report_week_bounds` returns the week containing its argument**; the prior-week selection lives in the callers (`localdate() - 7 days`). Keeps the boundary function pure and reusable for any target week (`--week`).
- **Deterministic overwrite** (`_save_overwrite` deletes any existing file before `default_storage.save`) so regeneration reuses the stable `reports/{week_start}/{code}.{ext}` name instead of minting a suffixed orphan — keeps `csv_path`/`pdf_path` canonical.
- **ALL roll-up (department=None) always generates**, counted in the returned tally (fixture → 2 departments + 1 ALL = 3).

## Deviations from Plan

None - plan executed exactly as written. (The `generate_week_reports` orchestrator is an implementation of Task 2's "reuse the shared service — do not duplicate generation logic" directive, not a scope change; the three named service symbols from the plan's artifacts are all present.)

## Issues Encountered
None. The docstring reference to the forbidden `Notification.objects.create` pattern initially tripped the acceptance grep; reworded to prose so the grep confirms no direct model create remains — the code always routes through `notify()`.

## User Setup Required
None - no external service configuration required. (S3 storage swap remains a Phase 8 config-only change per assumption A4; today `default_storage` writes to `MEDIA_ROOT`.)

## Next Phase Readiness
- `WeeklyReport` rows now materialize with populated `csv_path`/`pdf_path`, ready for the Dean/IFO report-download surfaces (06-06/06-07) to serve.
- `generate_weekly_report` command available for manual backfill of any week.
- No blockers.

## Self-Check: PASSED

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*
