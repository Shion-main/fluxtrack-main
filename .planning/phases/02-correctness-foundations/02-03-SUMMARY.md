---
phase: 02-correctness-foundations
plan: 03
subsystem: scheduling
tags: [django, orm, status-sweep, room-conflict, mssql, filtered-unique, audit, notify, tdd]

# Dependency graph
requires:
  - phase: 02-01
    provides: is_no_show_past_grace shared no-show predicate (scheduling/resolver.py)
  - phase: 02-02
    provides: notify() single Notification write path (ops/notify.py)
  - phase: 01
    provides: MSSQL foundation + proven filtered-unique index pattern (azure_oid)
provides:
  - "sweep_no_shows(now=None): marks unscanned F2F/Blended no-shows ABSENT, backfilled, idempotent, audited, online-excluded, never auto-releasing a room (JOB-02b)"
  - "detect_room_conflicts(now=None): raises ONE deduped IFO room-conflict notification per contradictory occupancy, auto-resolving on clear (JOB-02c)"
  - "RoomConflictFlag model + migration 0002 with filtered UniqueConstraint (one open flag per conflict_key)"
  - "run_status_sweep ASCII-only management command wrapping both service functions"
affects: [02-05, 03-checker-teams, 04-modality-shift, 07-ifo-resolution]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sweep shares the atomic is_no_show_past_grace predicate (not the whole resolver) so scan-time and sweep-time can never disagree"
    - "Dedup via a source-of-truth RoomConflictFlag with a filtered UniqueConstraint (resolved_at IS NULL) rather than per-user Notification inspection"
    - "System-initiated writes use AuditLog(actor=None, payload={by: sweep}) to distinguish sweep- from scan-marked absences"

key-files:
  created:
    - scheduling/jobs.py
    - ops/migrations/0002_roomconflictflag.py
    - scheduling/management/commands/run_status_sweep.py
  modified:
    - ops/models.py
    - scheduling/tests.py

key-decisions:
  - "Online sessions are EXCLUDED from Absent-marking (effective modality = declared_modality or schedule.modality == online); documented Phase-3 hook (Checker + MS Teams verification), NOT Phase 7"
  - "Dedup key is f\"room:{room_id}\" — one open conflict flag per room"
  - "The sweep NEVER stamps room_released_at (no timer-based auto-release; MOD-03/Phase 4 owns room release)"
  - "detect_room_conflicts reads room_released_at only as part of the ACTIVE-occupancy conflict query; it never writes it"

patterns-established:
  - "Pattern: pure-predicate-shared + thin-apply service function (sweep_no_shows) mirroring resolver/_apply split, with per-mutation transaction.atomic + AuditLog"
  - "Pattern: filtered-unique flag model for notification dedup with auto-resolve on state clear"

requirements-completed: [JOB-02b, JOB-02c]

coverage:
  - id: D1
    description: "A still-SCHEDULED F2F/Blended no-show past grace is marked ABSENT by the sweep via the shared is_no_show_past_grace predicate (JOB-02b)"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_scheduled_f2f_no_show_becomes_absent"
        status: pass
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_blended_no_show_becomes_absent"
        status: pass
    human_judgment: false
  - id: D2
    description: "The sweep backfills ALL past-date no-shows (self-heal after outage)"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_past_date_no_show_is_backfilled"
        status: pass
    human_judgment: false
  - id: D3
    description: "Online no-shows (declared_modality or schedule.modality == online) stay SCHEDULED — Phase-3 exclusion hook"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_online_no_show_stays_scheduled_declared"
        status: pass
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_online_no_show_stays_scheduled_via_schedule"
        status: pass
    human_judgment: false
  - id: D4
    description: "The sweep is idempotent: only SCHEDULED -> ABSENT; active/completed/already-absent untouched across reruns"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_idempotent_only_scheduled_to_absent"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every sweep-marked absence writes AuditLog(session.marked_absent, payload by=sweep)"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_marked_absence_writes_auditlog_by_sweep"
        status: pass
    human_judgment: false
  - id: D6
    description: "The sweep NEVER stamps room_released_at (no timer-based auto-release)"
    requirement: "JOB-02b"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#SweepTests.test_sweep_never_stamps_room_released_at"
        status: pass
    human_judgment: false
  - id: D7
    description: "Contradictory occupancy (2+ ACTIVE sessions, room_released_at NULL) raises ONE open RoomConflictFlag + one IFO notification per admin (JOB-02c)"
    requirement: "JOB-02c"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#RoomConflictTests.test_conflict_raises_one_flag_and_ifo_notifications"
        status: pass
    human_judgment: false
  - id: D8
    description: "A re-run against the same unresolved conflict creates NO new flag and NO new notification (dedup)"
    requirement: "JOB-02c"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#RoomConflictTests.test_second_detection_is_deduped"
        status: pass
    human_judgment: false
  - id: D9
    description: "When the conflict clears, a detection run stamps the flag's resolved_at (auto-resolve)"
    requirement: "JOB-02c"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#RoomConflictTests.test_conflict_auto_resolves_when_cleared"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-03
status: complete
---

# Phase 2 Plan 03: JOB-02 Status Sweep + Room-Conflict Safety Net Summary

**A scan-independent status sweep marks unscanned F2F/Blended no-shows ABSENT via the shared `is_no_show_past_grace` predicate — backfilled, idempotent, audited, online-excluded, never auto-releasing a room — plus a deduped, auto-resolving IFO room-conflict flag through the shared `notify()` path.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-02T21:47:42Z
- **Completed:** 2026-07-02T21:51:23Z
- **Tasks:** 3
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments
- `sweep_no_shows(now=None) -> int`: marks every still-SCHEDULED F2F/Blended session past grace ABSENT, using the SAME `is_no_show_past_grace` atom the scan resolver uses; backfills all past dates; idempotent (only SCHEDULED->ABSENT); writes `AuditLog(event_type="session.marked_absent", payload={"by": "sweep"})`; excludes online with a documented Phase-3 hook; never touches `room_released_at`.
- `detect_room_conflicts(now=None) -> int`: detects 2+ ACTIVE sessions holding one room (`room_released_at` NULL), raises exactly one open `RoomConflictFlag` (key `room:{room_id}`) + one `notify(role=IFO_ADMIN, type="room_conflict")` per admin on first detection, dedups on re-run, and stamps `resolved_at` when the conflict clears.
- `RoomConflictFlag` model + migration `0002_roomconflictflag` with a filtered `UniqueConstraint(fields=["conflict_key"], condition=Q(resolved_at__isnull=True))` proven on SQL Server.
- `run_status_sweep` ASCII-only management command wrapping both service functions.
- 12 new tests (SweepTests + RoomConflictTests) green; full `scheduling`+`ops` suite 50/50 green.

## Task Commits

Each task was committed atomically (TDD: test -> feat):

1. **Task 1: SweepTests + RoomConflictTests (RED)** - `e4e5145` (test)
2. **Task 2: RoomConflictFlag model + migration** - `770c184` (feat)
3. **Task 3: scheduling/jobs.py + run_status_sweep (GREEN)** - `968abab` (feat)

**Plan metadata:** `<final-docs-commit>` (docs: complete plan)

## Files Created/Modified
- `scheduling/jobs.py` (created) - `sweep_no_shows` + `detect_room_conflicts` service functions.
- `ops/migrations/0002_roomconflictflag.py` (created) - RoomConflictFlag table + filtered unique index.
- `scheduling/management/commands/run_status_sweep.py` (created) - thin ASCII command wrapping both jobs.
- `ops/models.py` (modified) - added `RoomConflictFlag` (filtered UniqueConstraint `uniq_open_conflict_per_key`) + `Q` import.
- `scheduling/tests.py` (modified) - appended `SweepTests` + `RoomConflictTests` (12 DB-backed tests) with a shared `_JobFixtureMixin`.

## Decisions Made
- **Online exclusion, not "mark regardless":** the plan/coordination note locked the online-exclusion interim (research had floated the alternative). The skip cites Phase 3 (Checker + MS Teams verification) as the hook that will later flip attended online sessions to ACTIVE — explicitly NOT Phase 7.
- **Dedup key `room:{room_id}`:** one open conflict flag per room, matching manual IFO resolution granularity.
- **Sweep never stamps `room_released_at`:** guarded by `SweepTests.test_sweep_never_stamps_room_released_at`. `detect_room_conflicts` only *reads* `room_released_at` in its ACTIVE-occupancy query.
- Test fixtures use a local `_JobFixtureMixin` (mints distinct unique keys per session) rather than the single-shot `make_session` factory, since several tests persist multiple sessions in one method.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Task 1 was correctly RED via `ImportError` (scheduling.jobs + RoomConflictFlag absent); Tasks 2-3 turned it GREEN. Ran with the default test DB (`test_fluxtrack`) per the Wave-2 isolation note, avoiding collision with parallel plan 02-04 (`test_fluxtrack_ops`).

## Threat Flags

None. All threat-register mitigations (T-02-06 idempotency guard + shared predicate + AuditLog; T-02-07 by=sweep audit; T-02-08 filtered-unique dedup + auto-resolve; T-02-09 no room_released_at stamp) are implemented and test-covered. No new security surface introduced.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `sweep_no_shows` is ready for Plan 02-05 to register as the scheduler's `sweep` job (on `ops` migration 0003_jobrun, which stacks on this plan's 0002).
- Phase-3 will remove the online-exclusion skip once the online-verify path exists.
- Phase 4 (MOD-03) owns `room_released_at` via the `release_room()` helper; the sweep deliberately does not call it.

---
*Phase: 02-correctness-foundations*
*Completed: 2026-07-03*

## Self-Check: PASSED
- All created files present (scheduling/jobs.py, ops/migrations/0002_roomconflictflag.py, run_status_sweep.py, 02-03-SUMMARY.md).
- All task commits verified in git history (e4e5145 test, 770c184 feat, 968abab feat).
