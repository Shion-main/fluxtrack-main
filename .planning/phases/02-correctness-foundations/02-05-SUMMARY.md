---
phase: 02-correctness-foundations
plan: 05
subsystem: infra
tags: [apscheduler, scheduler, jobrun, django-management-command, cron, mssql]

# Dependency graph
requires:
  - phase: 02-02
    provides: "ops.notify.notify() single Notification write path (failure alerts route through it)"
  - phase: 02-03
    provides: "scheduling.jobs.sweep_no_shows + detect_room_conflicts (the sweep job body); ops migration 0002_roomconflictflag (0003 stacks on it)"
  - phase: 02-04
    provides: "ops/tests.py ReleaseRoomTests region (JobRun/NoImplicitScheduler classes appended after)"
provides:
  - "JobRun model + migration 0003 — one row per scheduled-job execution (status/rows/timestamps)"
  - "ops.jobrun.run_job(job_name, fn) observability wrapper — records JobRun, notifies System Admins on failure only, never re-raises"
  - "scheduling/management/commands/runscheduler.py — single dedicated BlockingScheduler process wiring exactly 3 jobs"
  - "FLUXTRACK_POLICY['sweep_interval_minutes']=5 (sweep cadence via get_policy, not hardcoded)"
  - "APScheduler pinned >=3.10,<4"
affects: [phase-06-reporting, phase-07-sys-04, deployment-systemd]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedicated BlockingScheduler process (manage.py runscheduler) — never AppConfig.ready(), so jobs never double-fire across web workers"
    - "run_job observability wrapper: JobRun row per run + failure-only SysAdmin alert; broad Exception caught so a bad run cannot crash the scheduler"
    - "build_scheduler() factored out (returns unstarted scheduler) for unit-testable get_jobs() introspection"

key-files:
  created:
    - ops/jobrun.py
    - ops/migrations/0003_jobrun.py
    - scheduling/management/commands/runscheduler.py
  modified:
    - ops/models.py
    - ops/tests.py
    - scheduling/tests.py
    - config/settings.py
    - requirements.txt

key-decisions:
  - "Dropped the research-optional close_old_connections() from run_job: it closes the connection Django's per-test transaction holds (every JobRunTest errored 'Attempt to use a closed connection'); short jobs never outlive a pyodbc connection so the hygiene call bought nothing"
  - "Materialize cadence is a code constant (6h) while sweep cadence is policy-driven — sweep gates the no-show grace experience so it reads get_policy('sweep_interval_minutes'); materialize is pure horizon backfill"
  - "weekly_report registered now as a stub returning 0 so the one dedicated process owns all 3 jobs from day one; the report body (per-dept CSV/PDF -> S3) is Phase 6"

patterns-established:
  - "One dedicated scheduler process, constructed only in build_scheduler(), guarded by NoImplicitSchedulerTests reading every project app's apps.py"
  - "Every scheduled job callable is wrapped lambda: run_job(name, fn) with max_instances=1, coalesce=True, replace_existing=True"

requirements-completed: [ENV-04]

coverage:
  - id: D1
    description: "JobRun model + run_job wrapper: records status/rows/timestamps per run; notifies System Admins on failure only; never re-raises"
    requirement: "ENV-04"
    verification:
      - kind: unit
        ref: "ops/tests.py::JobRunTests (4 tests: ok records rows+no notice, none->0 rows, failure records failed+notifies active sysadmin only, no re-raise)"
        status: pass
    human_judgment: false
  - id: D2
    description: "runscheduler registers exactly 3 jobs (materialize/sweep/weekly_report) on one unstarted BlockingScheduler"
    requirement: "ENV-04"
    verification:
      - kind: unit
        ref: "scheduling/tests.py::SchedulerWiringTests::test_build_scheduler_registers_exactly_three_jobs_unstarted"
        status: pass
    human_judgment: false
  - id: D3
    description: "No AppConfig.ready() constructs or starts a scheduler (no per-worker double-fire)"
    requirement: "ENV-04"
    verification:
      - kind: unit
        ref: "ops/tests.py::NoImplicitSchedulerTests::test_no_app_config_constructs_or_imports_a_scheduler"
        status: pass
    human_judgment: false
  - id: D4
    description: "Live run: manage.py runscheduler fires a sweep JobRun within ~5 min and a second web worker produces no duplicate JobRun rows"
    requirement: "ENV-04"
    verification: []
    human_judgment: true
    rationale: "02-VALIDATION.md manual-only item — requires running runscheduler alongside runserver + a second web worker and observing a live tick; structural wiring is fully unit-covered by D1-D3, but the real 5-min tick and no-double-fire behavior can only be observed at runtime"

# Metrics
duration: 6min
completed: 2026-07-02
status: complete
---

# Phase 2 Plan 05: Dedicated APScheduler Process (ENV-04) Summary

**One `manage.py runscheduler` BlockingScheduler process runs all 3 jobs (materialize/6h, sweep/policy-driven 5-min, weekly_report stub), each wrapped by a run_job observability wrapper that records a JobRun row per run and alerts System Admins on failure only — never inside a web worker, so nothing double-fires.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-02T21:55:18Z
- **Completed:** 2026-07-02T22:01:06Z
- **Tasks:** 3
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments
- `JobRun` model (job_name, status, started_at, finished_at, rows_affected, detail) with `-started_at` ordering + `(job_name, -started_at)` index, migration `0003_jobrun` stacked on `0002_roomconflictflag`. SYS-04 (Phase 7) reads the latest row per job_name.
- `ops.jobrun.run_job(job_name, fn)` — records exactly one JobRun per execution (running -> ok|failed), notifies `role=SYSTEM_ADMIN, type="job_failed"` on failure ONLY (success/heartbeat never notify), and catches broad `Exception` so one bad run cannot crash the long-lived BlockingScheduler process (T-02-13).
- `runscheduler` command with a factored `build_scheduler()` returning an unstarted `BlockingScheduler(timezone=Asia/Manila)` + `MemoryJobStore`, registering exactly 3 jobs: `materialize` (IntervalTrigger 6h via `call_command("materialize_sessions")`), `sweep` (IntervalTrigger `get_policy("sweep_interval_minutes")`=5 min running `sweep_no_shows` then `detect_room_conflicts`), `weekly_report` (CronTrigger Mon 06:00, stub returning 0). Each `max_instances=1, coalesce=True, replace_existing=True`.
- `sweep_interval_minutes=5` added to `FLUXTRACK_POLICY` (overridable via SystemSetting like every other policy key).
- APScheduler pin tightened to `>=3.10,<4` (blocks the 4.0 pre-release rewrite of the scheduler/jobstore API).

## Task Commits

Each task was committed atomically (TDD: test -> feat):

1. **Task 1: RED tests** - `6b65402` (test) — JobRunTests + NoImplicitSchedulerTests + SchedulerWiringTests
2. **Task 2: JobRun model + migration + run_job** - `1de7e24` (feat) — GREEN for JobRunTests
3. **Task 3: runscheduler + policy + pin** - `3da104a` (feat) — GREEN for SchedulerWiringTests + NoImplicitSchedulerTests

_RED at Task 1: 5 errors (JobRunTests x4 + SchedulerWiringTests import) with NoImplicitSchedulerTests correctly green as a structural guard._

## Files Created/Modified
- `ops/jobrun.py` - `run_job` observability wrapper (record JobRun, failure-only SysAdmin alert, never re-raise)
- `ops/migrations/0003_jobrun.py` - CreateModel JobRun, depends on `0002_roomconflictflag`
- `scheduling/management/commands/runscheduler.py` - dedicated BlockingScheduler process + `build_scheduler()`
- `ops/models.py` - added `JobRun` model
- `ops/tests.py` - appended `JobRunTests` + `NoImplicitSchedulerTests` (method-local imports so only ENV-04 classes went RED)
- `scheduling/tests.py` - appended `SchedulerWiringTests`
- `config/settings.py` - `FLUXTRACK_POLICY['sweep_interval_minutes'] = 5`
- `requirements.txt` - `APScheduler>=3.10,<4`

## Decisions Made
- **Removed the research-"optional" `close_old_connections()` from `run_job`.** Documented as a deviation below — it broke every JobRunTest under Django's per-test transaction.
- **Sweep cadence policy-driven, materialize cadence a code constant.** Sweep affects the no-show grace experience so it goes through `get_policy`; materialize is pure horizon backfill where 6h is an implementation detail.
- **weekly_report stub returns 0 now.** Registers the slot so the dedicated process owns all 3 jobs immediately; the Phase-6 report body is out of scope here.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed optional `close_old_connections()` that broke every JobRunTest**
- **Found during:** Task 2 (run_job implementation)
- **Issue:** The plan/research offered an *optional* `django.db.close_old_connections()` at the start/end of `run_job` for long-running-process hygiene. Calling it inside a Django `TestCase` closes the connection the per-test atomic transaction holds, so all 4 JobRunTests errored with `ProgrammingError: Attempt to use a closed connection`.
- **Fix:** Dropped the call (it was explicitly optional; jobs here are short and never outlive a pyodbc connection's server-side lifetime). Documented the rationale in the module docstring.
- **Files modified:** ops/jobrun.py
- **Verification:** `py -3.12 manage.py test ops.tests.JobRunTests` -> 4 passed.
- **Committed in:** `1de7e24` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The removed call was optional hygiene, not a correctness requirement; every ENV-04 behavior (record every run, notify on failure only, never crash the scheduler) is intact. No scope creep.

## Issues Encountered
- None beyond the deviation above.

## Verification
- `py -3.12 manage.py test ops scheduling` -> 56 tests, OK.
- `py -3.12 manage.py test` (full suite) -> 61 tests, OK.
- `py -3.12 manage.py makemigrations --check --dry-run` -> "No changes detected".
- runscheduler emitted output is pure ASCII (`->`, no arrows/emoji); only `§`/`—` appear, and only in docstrings/comments (matching the codebase convention).

## User Setup Required
None - no external service configuration required. (Operationally, prod launches a second systemd unit running `manage.py runscheduler` on the same instance; dev runs it in a second terminal alongside `runserver`.)

## Next Phase Readiness
- **Manual verification pending (D4, 02-VALIDATION.md manual-only):** run `py -3.12 manage.py runscheduler` alongside `runserver`; within ~5 min confirm `JobRun.objects.filter(job_name="sweep").exists()` and that a second web worker creates NO duplicate JobRun rows. Structural wiring (exactly-3-jobs, no-implicit-scheduler, record-on-run, failure-only-notify) is fully unit-covered.
- **Phase 6:** weekly_report job body (RPT-01 per-department CSV/PDF generation) fills the registered stub.
- **Phase 7:** SYS-04 reads the latest JobRun per job_name (the `(job_name, -started_at)` index serves this).

---
*Phase: 02-correctness-foundations*
*Completed: 2026-07-02*

## Self-Check: PASSED
- Files verified on disk: ops/jobrun.py, ops/migrations/0003_jobrun.py, scheduling/management/commands/runscheduler.py, 02-05-SUMMARY.md
- Commits verified in git: 6b65402 (test), 1de7e24 (feat), 3da104a (feat)
