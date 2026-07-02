---
phase: 02-correctness-foundations
verified: 2026-07-03T00:00:00Z
status: passed
resolved_note: "Human-verification item accepted by user 2026-07-03 after live MSSQL smoke test (sweep confirmed marking real no-shows via run_job; scheduler wiring confirmed) discharged all code-level risk; residual is optional operational observation only."
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "In a dedicated terminal run `py -3.12 manage.py runscheduler` alongside `runserver`. Wait ~5 minutes."
    expected: "A JobRun row for job_name='sweep' appears (JobRun.objects.filter(job_name='sweep').exists() is True) within ~5 minutes. Starting a second runscheduler/web-worker process produces NO duplicate JobRun rows for the same tick — proving exactly one dedicated scheduler process fires each job, with no per-worker double-fire."
    why_human: "Wall-clock scheduler timing across a live process over several minutes is not unit-testable without freezing time across a process boundary. Structural wiring (exactly 3 jobs registered, scheduler constructed only in build_scheduler(), never in AppConfig.ready()) IS proven by automated tests (SchedulerWiringTests, NoImplicitSchedulerTests); only the live tick + concurrent-process non-duplication is unverifiable by grep/unit test. This is documented as the phase's sole Manual-Only Verification in 02-VALIDATION.md and harvested from 02-05-PLAN.md's <human-check> block."
---

# Phase 2: Correctness Foundations Verification Report

## Post-Verification Live Validation (2026-07-03, orchestrator)

During the human-verification live smoke test, running the sweep through
`run_job` against the real MSSQL dev database surfaced a **real defect** the
unit tests missed:

- **Bug:** `sweep_no_shows` (and `detect_room_conflicts`' auto-resolve loop)
  iterated a SELECT cursor via `.iterator()` / a live queryset while issuing
  per-row `save()` + `AuditLog` INSERTs inside the loop. On SQL Server/pyodbc
  (single active result set per connection, MARS off) this raises
  `HY010 "Function sequence error (SQLFetch)"` as soon as there are real
  F2F no-shows to mark. Unit tests passed only because 1–2 rows drain the
  cursor before the first write.
- **Fix (commit `92b7027`):** materialize each candidate queryset into a list
  before mutating (cursor closed first). Added
  `SweepTests.test_batch_of_no_shows_all_marked_absent` (5-row regression).
- **Live confirmation on real MSSQL dev DB:** a fabricated batch of 5 F2F
  no-shows now marks 5/5 Absent, `run_job` returns `status=ok`,
  `rows_affected=5`, no error. Fabricated rows cleaned up afterward.
- **Scheduler wiring re-confirmed on real settings:** `build_scheduler()`
  returns a `BlockingScheduler` with exactly 3 jobs (materialize interval[6h],
  sweep interval[5m from policy], weekly_report cron[mon 06:00]), unstarted.
- Full suite after fix: **59 tests OK**; `makemigrations --check` clean.

**Residual human item (optional, operational):** observing the scheduler
process fire the sweep on its 5-minute cadence over live wall-clock time. The
sweep's job logic + observability are now proven on real MSSQL; nothing starts
a scheduler in any `AppConfig.ready()`, so web workers never fire jobs — the
"no double-fire" property is structural, and only ONE `runscheduler` process is
ever launched by design (a dedicated systemd unit in prod).

---


**Phase Goal:** "Absent" is trustworthy without relying on scans, contradictory room occupancy is flagged to IFO, every event flows through one notification write path, and all jobs run from one scheduler process. (Timer-based auto-release was CUT 2026-07-03.)
**Verified:** 2026-07-03
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (amended Success Criteria) | Status | Evidence |
|---|-----------|--------|----------|
| 1 | A session nobody scans into is marked Absent within one sweep interval, using the SAME grace predicate the live scanner uses — scan and sweep never disagree | ✓ VERIFIED | `is_no_show_past_grace(scheduled_start, now, grace_min)` defined once in `scheduling/resolver.py:39-52`; called by `resolve_faculty_scan` (`resolver.py:104`) and by `sweep_no_shows` (`scheduling/jobs.py:60`). `CouplingIntegrityTests.test_resolver_absent_iff_predicate_true` (scheduling/tests.py:153-162) asserts resolver ABSENT ⇔ predicate across a 6-point delta sweep. `SweepTests` proves the sweep marks a real DB session Absent independent of any scan. All pass. |
| 2 | Contradictory room occupancy raises a single (DEDUPED) IFO room-conflict notification. `release_room()` EXISTS and is TESTED but invoked ONLY by modality-approval (Phase 4), NOT on a timer | ✓ VERIFIED | `RoomConflictFlag` (ops/models.py:77-104) has `UniqueConstraint(fields=["conflict_key"], condition=Q(resolved_at__isnull=True))`. `detect_room_conflicts` (scheduling/jobs.py:75-114) raises exactly one flag + one `notify(role=IFO_ADMIN, type="room_conflict")` fan-out per new conflict, dedupes on rerun, auto-resolves on clear — proven by `RoomConflictTests` (3/3 passing). `release_room()` (ops/occupancy.py) has ZERO callers anywhere in the codebase outside `ops/tests.py::ReleaseRoomTests` (grep confirmed). `SweepTests.test_sweep_never_stamps_room_released_at` proves the sweep never stamps `room_released_at`. |
| 3 | Every notification is created by one shared `notify()` write path — `_notify_ifo` is gone and no other inline notifier remains | ✓ VERIFIED | `web/scan.py` read in full: no `def _notify_ifo`, imports `from ops.notify import notify`, both former call sites (room-change ~L107, force-handover ~L124) route through `notify(role=Role.IFO_ADMIN, type="room_event", ...)`. Repo-wide grep for `Notification.objects.create` finds exactly one hit: `ops/notify.py:33`. `SingleWritePathTests` (2 tests) source-guards both facts and passes. `ScanNotifyTests` (web/tests.py) drives the real two-step confirm endpoints and confirms IFO rows are created. |
| 4 | materialize, sweep, weekly-report jobs run from ONE dedicated scheduler process, never duplicated across web workers, last-run status recordable | ✓ VERIFIED (structural); wall-clock live-tick is human-verification item | `runscheduler.py::build_scheduler()` returns an unstarted `BlockingScheduler` registering exactly 3 jobs (`materialize`, `sweep`, `weekly_report`) — `SchedulerWiringTests` confirms `{j.id for j in sched.get_jobs()} == {"materialize","sweep","weekly_report"}` and `sched.running is False`. All 6 `apps.py` files (accounts, campus, ops, scheduling, verification, web) contain no `ready()` method and no scheduler-related tokens — confirmed by direct read AND `NoImplicitSchedulerTests` (source-guard, passes). `JobRun` model (ops/models.py:107-129) records status/rows_affected/timestamps; `run_job()` (ops/jobrun.py) wraps every job. Live 5-minute tick + no-double-fire across concurrent processes is NOT unit-testable and is explicitly flagged as the phase's one Manual-Only Verification in 02-VALIDATION.md and 02-05-PLAN.md — routed to human verification below. |
| 5 | Re-running the sweep never changes an already-decided session (idempotent) | ✓ VERIFIED | `SweepTests.test_idempotent_only_scheduled_to_absent` creates scheduled/active/completed/already-absent fixtures, runs the sweep twice, and asserts only the SCHEDULED session transitions (first=1, second=0) while active/completed/already-absent are untouched. Passes. |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Locked Decisions from 02-CONTEXT.md

| # | Decision | Status | Evidence |
|---|----------|--------|----------|
| 1 | Sweep excludes online sessions (effective modality = declared_modality or schedule.modality), documented PHASE-3 hook | ✓ VERIFIED | `scheduling/jobs.py:50-57` — explicit comment citing "Phase-3 hook"; `test_online_no_show_stays_scheduled_declared` + `test_online_no_show_stays_scheduled_via_schedule` both pass; `test_blended_no_show_becomes_absent` confirms Blended (not online) IS swept. |
| 2 | Sweep backfills past-date no-shows (not just today) | ✓ VERIFIED | `sweep_no_shows` query has no date filter beyond `scheduled_start__lt=cutoff`; `test_past_date_no_show_is_backfilled` (2-days-ago session) passes. |
| 3 | Every sweep-marked absence writes an AuditLog | ✓ VERIFIED | `scheduling/jobs.py:67-70` creates `AuditLog(event_type="session.marked_absent", payload={"by":"sweep"})`; `test_marked_absence_writes_auditlog_by_sweep` passes. |
| 4 | run_job notifies System Admins on FAILURE only (never success) | ✓ VERIFIED | `ops/jobrun.py:36-45` — notify() call is only inside the `except` branch; `JobRunTests.test_success_records_ok_rows_and_no_failure_notice` asserts zero `job_failed` notifications on success; `test_failure_records_failed_detail_and_notifies_active_sysadmins_only` asserts exactly one, to the active admin only. |
| 5 | sweep cadence + grace sourced from get_policy(), not hardcoded | ✓ VERIFIED | `runscheduler.py:78` — `IntervalTrigger(minutes=get_policy("sweep_interval_minutes"))`; `scheduling/jobs.py:42` — `grace_min = get_policy("grace_minutes")`. `config/settings.py:154` sets the default (5). `ops/policy.py::get_policy` reads `SystemSetting` override first, falls back to `FLUXTRACK_POLICY`. |
| 6 | APScheduler pinned >=3.10,<4 | ✓ VERIFIED | `requirements.txt:15` — `APScheduler>=3.10,<4`. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scheduling/resolver.py` | `is_no_show_past_grace` predicate; resolver wired to call it | ✓ VERIFIED | Present, substantive, wired (L39-52, L104) |
| `scheduling/tests.py` | `NoShowPredicateTests`, `CouplingIntegrityTests`, `SweepTests`, `RoomConflictTests`, `SchedulerWiringTests` | ✓ VERIFIED | All 5 classes present, all pass |
| `ops/notify.py` | `notify(*, type, title, body, link, role, users)` | ✓ VERIFIED | Present, substantive, sole `Notification.objects.create` site |
| `web/scan.py` | `_notify_ifo` removed; call sites migrated | ✓ VERIFIED | Confirmed by full read |
| `ops/tests.py` | `NotifyTests`, `SingleWritePathTests`, `ReleaseRoomTests`, `JobRunTests`, `NoImplicitSchedulerTests` | ✓ VERIFIED | All 5 classes present, all pass |
| `web/tests.py` | `ScanNotifyTests` | ✓ VERIFIED | Present, drives real endpoints, passes |
| `ops/models.py` | `RoomConflictFlag` (filtered unique), `JobRun` | ✓ VERIFIED | Both present with correct constraints/fields |
| `scheduling/jobs.py` | `sweep_no_shows`, `detect_room_conflicts` | ✓ VERIFIED | Present, substantive, wired to predicate/notify/RoomConflictFlag |
| `ops/occupancy.py` | `release_room()` | ✓ VERIFIED | Present, substantive, tested, zero callers outside tests (by design) |
| `scheduling/management/commands/runscheduler.py` | `build_scheduler()` + `Command` using `BlockingScheduler` | ✓ VERIFIED | Present, substantive, unit-tested |
| `ops/jobrun.py` | `run_job()` | ✓ VERIFIED | Present, substantive, tested |
| `config/settings.py` | `sweep_interval_minutes` in `FLUXTRACK_POLICY` | ✓ VERIFIED | L154, value 5 |
| `requirements.txt` | APScheduler pin `>=3.10,<4` | ✓ VERIFIED | L15 |
| `ops/migrations/0002_roomconflictflag.py`, `0003_jobrun.py` | Migrations exist, applied | ✓ VERIFIED | Present; `makemigrations --check --dry-run` reports "No changes detected" |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `resolve_faculty_scan` ABSENT branch | `is_no_show_past_grace` | direct call | ✓ WIRED | resolver.py:104 |
| `sweep_no_shows` | `is_no_show_past_grace` | import + call | ✓ WIRED | jobs.py:32, :60 |
| `web/scan.py` room-change/handover | `ops.notify.notify` | `notify(role=Role.IFO_ADMIN, ...)` | ✓ WIRED | scan.py:107, :124 |
| `detect_room_conflicts` | `ops.notify.notify` + `RoomConflictFlag` | create flag then notify on first detection | ✓ WIRED | jobs.py:101-113 |
| sweep-marked absence | `ops.models.AuditLog` | `AuditLog.objects.create(event_type="session.marked_absent")` | ✓ WIRED | jobs.py:67-70 |
| `release_room(session)` | `Session.room_released_at` + `AuditLog` | save + create | ✓ WIRED (tested, zero production callers by design) | occupancy.py:27-36 |
| `runscheduler build_scheduler()` | `run_job` + `scheduling.jobs` + `materialize_sessions` | `add_job(lambda: run_job(...))` | ✓ WIRED | runscheduler.py:69-86 |
| `run_job` failure branch | `ops.notify.notify(role=SYSTEM_ADMIN)` | inside `except` | ✓ WIRED | jobrun.py:41-42 |

### Behavioral Spot-Checks / Test Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-relevant suite | `py -3.12 manage.py test ops scheduling web` | `Ran 58 tests in 1.366s — OK` | ✓ PASS |
| No pending model/migration drift | `py -3.12 manage.py makemigrations --check --dry-run` | `No changes detected` | ✓ PASS |
| `_notify_ifo` fully removed | direct read + grep across repo | 0 source hits (only in .planning docs / test guard string) | ✓ PASS |
| Sole `Notification.objects.create` site | grep across repo | 1 hit: `ops/notify.py:33` | ✓ PASS |
| `release_room()` zero production callers | grep across repo | Hits only in `ops/occupancy.py` (definition) and `ops/tests.py` (tests) | ✓ PASS |
| No `AppConfig.ready()` anywhere | direct read of all 6 `apps.py` | No `ready()` method in any | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| NOTIF-00 | 02-02 | Single shared `notify()` write path replacing `_notify_ifo` | ✓ SATISFIED | ops/notify.py + SingleWritePathTests + ScanNotifyTests |
| JOB-02a | 02-01 | Pure no-show-past-grace predicate shared by scan and sweep | ✓ SATISFIED | resolver.py::is_no_show_past_grace + CouplingIntegrityTests |
| JOB-02b | 02-03 | Status sweep marks no-show sessions Absent independent of scan | ✓ SATISFIED | scheduling/jobs.py::sweep_no_shows + SweepTests |
| JOB-02c | 02-03 / 02-04 | Room-conflict flag via notify(), deduped; release_room() built+tested, invoked only by MOD-03 (Phase 4) | ✓ SATISFIED | RoomConflictFlag + detect_room_conflicts + RoomConflictTests; ops/occupancy.py + ReleaseRoomTests, zero callers |
| ENV-04 | 02-05 | All scheduled jobs run from one dedicated scheduler process, last-run status recordable | ✓ SATISFIED (structural); live-tick human item | runscheduler.py + JobRun + SchedulerWiringTests + NoImplicitSchedulerTests |

No orphaned requirements found — REQUIREMENTS.md maps exactly NOTIF-00, JOB-02a, JOB-02b, JOB-02c, ENV-04 to Phase 2, and all five appear in PLAN frontmatter `requirements:` fields.

### Anti-Patterns Found

None. Scanned all phase-modified files (`scheduling/resolver.py`, `scheduling/tests.py`, `ops/notify.py`, `web/scan.py`, `ops/tests.py`, `web/tests.py`, `ops/models.py`, `scheduling/jobs.py`, `scheduling/management/commands/run_status_sweep.py`, `ops/occupancy.py`, `ops/jobrun.py`, `scheduling/management/commands/runscheduler.py`, `config/settings.py`, `requirements.txt`) for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` and stub patterns — zero hits.

### Human Verification Required

### 1. APScheduler live 5-minute tick, no double-fire across processes

**Test:** In a dedicated terminal run `py -3.12 manage.py runscheduler` alongside `runserver`. Wait ~5 minutes. Then start a second concurrent process/worker (per the deployment design, a second `runscheduler` or web worker) and observe.
**Expected:** A `JobRun` row for `job_name="sweep"` appears within ~5 minutes (`JobRun.objects.filter(job_name="sweep").exists()`). No duplicate `JobRun` rows for the same tick appear when a second worker/process is running — proving exactly one dedicated scheduler process fires each job.
**Why human:** Wall-clock scheduler timing across a live, long-running process is not unit-testable without freezing time across a process boundary. This is the phase's sole documented Manual-Only Verification (02-VALIDATION.md) and appears verbatim as a `<human-check>` block in 02-05-PLAN.md. All structural wiring around it (exactly 3 jobs registered, scheduler constructed only in `build_scheduler()`, never in `AppConfig.ready()`) IS proven by automated tests and was independently re-verified above by direct source read.

### Gaps Summary

No gaps found. All 5 amended Success Criteria, all 6 locked decisions from 02-CONTEXT.md, and all 5 requirement IDs (NOTIF-00, JOB-02a, JOB-02b, JOB-02c, ENV-04) are backed by substantive, wired, tested code. The full relevant test suite (58 tests across ops/scheduling/web) is green, migrations are clean, and no debt markers or stub patterns were found in any phase-modified file.

The only open item is a single, explicitly-scoped manual verification (live scheduler tick / no cross-process double-fire) that the plan itself correctly identified as untestable by automated means. This routes the phase to `human_needed` rather than `passed` per the verification decision tree — it does not indicate a gap in the implementation.

---

_Verified: 2026-07-03_
_Verifier: Claude (gsd-verifier)_
