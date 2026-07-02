---
phase: 02-correctness-foundations
plan: 02
subsystem: api
tags: [django, notifications, notify, single-write-path, scan, tdd]

# Dependency graph
requires:
  - phase: 01-mssql-foundation
    provides: Notification/AuditLog models on MSSQL, scan confirm flow (web/scan.py), Role choices
provides:
  - "ops/notify.py::notify() — the single Notification write path (NOTIF-00)"
  - "Role fan-out to active users reproducing the old _notify_ifo query exactly"
  - "web/scan.py room-change + force-handover migrated onto notify(); _notify_ifo deleted"
  - "SingleWritePathTests source guard preventing future inline Notification creation"
affects: [02-03 room-conflict flags, 02-05 job-failure alerts, phase-04 modality notices, phase-05 notif read/push]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single write-path service: one keyword-only notify() is the only Notification.objects.create call site"
    - "Source-guard test: assert a forbidden token (assembled from parts) is absent from named notifier modules"

key-files:
  created:
    - ops/notify.py
  modified:
    - web/scan.py
    - ops/tests.py
    - web/tests.py

key-decisions:
  - "notify() emits NO AuditLog — the triggering domain action (session.room_changed/force_handover) already carries the audit; auditing in notify() would double every event"
  - "notify() is keyword-only; targets a role (fan out to active users) OR an explicit users iterable; neither -> empty list, no rows"
  - "Notification import dropped from web/scan.py after _notify_ifo removal; AuditLog retained"

patterns-established:
  - "Pattern 1: notify(*, type, title, body='', link='', role=None, users=None) -> list[Notification] as the sole Notification creation site (NOTIF-00)"
  - "Pattern 2: SingleWritePathTests reads named module source and asserts absence of a part-assembled forbidden token so the guard never self-matches"

requirements-completed: [NOTIF-00]

coverage:
  - id: D1
    description: "notify(role=...) fans out to ACTIVE users of that role only (inactive/other-role users get nothing); notify(users=...) targets an explicit iterable; empty target creates nothing; no AuditLog written"
    requirement: "NOTIF-00"
    verification:
      - kind: integration
        ref: "ops/tests.py#NotifyTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Ad-hoc _notify_ifo helper removed from web/scan.py; no inline Notification create exists outside ops/notify.py"
    requirement: "NOTIF-00"
    verification:
      - kind: unit
        ref: "ops/tests.py#SingleWritePathTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Confirmed room-change and force-handover scan flows still create type=room_event IFO Notification rows via notify()"
    requirement: "NOTIF-00"
    verification:
      - kind: integration
        ref: "web/tests.py#ScanNotifyTests"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-03
status: complete
---

# Phase 02 Plan 02: Shared notify() Write Path (NOTIF-00) Summary

**`ops/notify.py::notify()` is now the single Notification write path; both `web/scan.py` IFO notifications route through it and the ad-hoc `_notify_ifo` helper is deleted.**

## Performance

- **Duration:** ~2 min (execution), TDD RED→GREEN
- **Started:** 2026-07-03T05:41:09+08:00
- **Completed:** 2026-07-03T05:42:25+08:00
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- Built `notify(*, type, title, body="", link="", role=None, users=None) -> list[Notification]` — role fan-out reproduces the exact old query `filter(role=role, is_active=True)`, plus explicit-users targeting; empty target is a no-op.
- Migrated both `web/scan.py` call sites (WRONG_ROOM room-change, ROOM_OCCUPIED force-handover) onto `notify(role=Role.IFO_ADMIN, type="room_event", ...)` with byte-identical titles/bodies.
- Deleted the ad-hoc `_notify_ifo` helper and its unused `Notification` import; every `audit(...)` call left intact.
- Added a source-guard test (`SingleWritePathTests`) that makes any future inline `Notification` creation outside `ops/notify.py` fail CI.

## Task Commits

Each task was committed atomically (TDD cycle):

1. **Task 1: Add NotifyTests + SingleWritePathTests + ScanNotifyTests (RED)** - `b6e1ded` (test)
2. **Task 2: Build ops/notify.py notify() write path (GREEN)** - `9cb5922` (feat)
3. **Task 3: Migrate web/scan.py onto notify(), delete _notify_ifo (GREEN)** - `1cf1a28` (feat)

_TDD gates present: test(...) RED commit → feat(...) GREEN commits._

## Files Created/Modified
- `ops/notify.py` - NEW. The single `notify()` Notification write path (NOTIF-00); the only permitted `Notification.objects.create` caller. No AuditLog emitted.
- `web/scan.py` - Migrated two IFO notifications to `notify()`; removed `_notify_ifo` + unused `Notification` import.
- `ops/tests.py` - Replaced stub with `NotifyTests` (role fan-out / explicit users / no-op / no-audit) and `SingleWritePathTests` (source guard).
- `web/tests.py` - Replaced stub with `ScanNotifyTests` driving the real two-step confirm endpoints.

## Decisions Made
- **notify() writes no AuditLog** (per 02-RESEARCH recommendation): the domain action that triggers the notification is already audited in `_apply` (`session.room_changed`, `session.force_handover`), so auditing inside notify() would double every event. `NotifyTests.test_notify_emits_no_auditlog` locks this in.
- **Keyword-only signature** with role OR users targeting; both omitted returns `[]` and writes nothing.
- **Dropped the now-unused `Notification` import** from `web/scan.py` (kept `AuditLog`), since notify() is the sole creation site.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. RED state was exactly as predicted (NotifyTests ImportError on `ops.notify`; SingleWritePathTests failing on the still-present helper; ScanNotifyTests already green against the old helper as a behavior-preservation baseline). All 25 tests across `ops`, `web`, and `scheduling.tests.FacultyResolverTests` pass after migration.

## Coordination Notes
- Ran in parallel (Wave 1) with plan 02-01, which owns `scheduling/resolver.py` and `scheduling/tests.py`. This plan touched only `ops/notify.py`, `web/scan.py`, `ops/tests.py`, `web/tests.py` — no file contention. Plan 02-01's commit (`31a4cfb`) landed interleaved as expected.

## Next Phase Readiness
- `ops.notify.notify` is the chokepoint ready for downstream importers:
  - **Plan 02-03** (room-conflict flags) — `notify(role=IFO_ADMIN, type="room_conflict", ...)`.
  - **Plan 02-05** (job-failure alerts) — `notify(role=SYSTEM_ADMIN, type="job_failure", ...)`.
  - **Phases 4/5** — modality-approval notices and NOTIF-01/02/03 read+push.
- `SingleWritePathTests` will keep those callers honest — inline `Notification.objects.create` outside `ops/notify.py` breaks CI.

## Self-Check: PASSED

All created/modified files present on disk; all three task commits (`b6e1ded`, `9cb5922`, `1cf1a28`) exist in git history.

---
*Phase: 02-correctness-foundations*
*Completed: 2026-07-03*
