---
phase: 07-remaining-operational-surfaces
plan: 12
subsystem: notifications / scheduled jobs
tags: [GRD-04, notifications, web-push, status-sweep, guard]
status: complete
requires:
  - ops.notify.notify (NOTIF-00 single write path)
  - ops.notifications PUSH_TYPES / CATEGORY_TYPES (D-21)
  - verification.resolver.assignment_covers_now (shared duty predicate)
  - scheduling.jobs sweep_no_shows / detect_room_conflicts
provides:
  - ops.guard_alerts.notify_floor_guards (coalesced GRD-04 fan-out)
  - ops.guard_alerts.summarize_floor_events (pure summary helper)
  - optional `collect=` seam on both sweep functions
affects:
  - scheduling/management/commands/runscheduler.py (_job_sweep)
  - scheduling/management/commands/run_status_sweep.py
tech-stack:
  added: []
  patterns: [caller-side coalescing, additive optional-keyword seam]
key-files:
  created:
    - ops/guard_alerts.py
    - scheduling/tests_guard_alerts.py
  modified:
    - ops/notifications.py
    - ops/tests_notifications.py
    - scheduling/jobs.py
    - scheduling/management/commands/runscheduler.py
    - scheduling/management/commands/run_status_sweep.py
decisions: [D-05, D-06, D-21]
metrics:
  tests_before: 595
  tests_after: 629
  failures: 3 (all pre-existing, out of scope)
  errors: 0
---

# Phase 07 Plan 12: GRD-04 Coalesced Guard Floor Alerts Summary

On-duty Guards now receive exactly one web-push per sweep run summarizing everything that happened on their posted floors, delivered through an additive collector seam that leaves the safety-critical status sweep's scalar returns byte-identical.

## What Was Built

**Task 1 — `32ae044`.** `GUARD_FLOOR_ALERT = "guard_floor_alert"` registered in BOTH `PUSH_TYPES` and the ROOM `CATEGORY_TYPES` group per D-21. `TYPE_CATEGORY` stays derived. `GuardAlertTypeRegistrationTests` locks all five behaviours and documents the two half-registered failure modes (unmutable; writes-but-never-pushes with `pushed_at` stuck NULL, which misreads as a VAPID failure).

**Task 2 — `28a65c0`.** `sweep_no_shows(now=None, collect=None)` and `detect_room_conflicts(now=None, collect=None)`. The keyword is optional and the scalar `int` returns are unchanged. Floor ids are read off `s.room.floor_id` via an added `select_related("room")` — rows the loop already iterates — so no `pk__in` is ever built from the unbounded backfill batch. `ops/guard_alerts.py` resolves recipients in one scalar-equality query, materialized with `list()` before the emit loop (HY010), reads floors via `a.floors.all()` (not `values_list`, which bypasses the prefetch cache), checks `is_active` explicitly, and gates duty through the shared `assignment_covers_now`.

**Task 3 — `de9e9cf`.** Both callers create one collector, pass it to both sweep functions, and fan out once afterwards. No fifth scheduler job. `run_status_sweep` now reports the guard count on its ASCII success line.

## Verification

Full suite: **Ran 629 tests — `FAILED (failures=3, skipped=26)`, 0 errors.** Baseline in this worktree was 595 / same 3 failures / 0 errors. The 3 are the known pre-existing `DevLoginCoexistTests`, `DevLoginCuratedDemoTests`, `HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

The 14 scalar call sites all hold, unmodified. The per-conflict `notify(role=Role.IFO_ADMIN, type="room_conflict", ...)` has zero diff lines.

## Deviations from Plan

**None affecting behaviour.** Two additions beyond the literal task text, both Rule 2:

1. **`CallerWiringTests`** added to `scheduling/tests_guard_alerts.py`. The plan's ten behaviours are all satisfiable by driving the sweep functions directly, which would leave the caller wiring — the actual coalescing boundary — untested. Without these, `notify_floor_guards` could be perfectly correct and simply never invoked in production. Covers `_job_sweep`, the `run_status_sweep` command output, and the four-job count.
2. **Extra scoping cases** beyond the plan's list: inactive `Assignment` status, and an `ONLINE`-scoped assignment (which must not count as a floor posting).

## Known Stubs

None.

## Threat Flags

None. No new network surface, auth path, file access, or schema change.

## Notes for Follow-up

- `ops/guard_alerts.py` is not in `ops/tests.py` `NOTIFIER_MODULES` (the NOTIF-00 source-grep allow-list). The module demonstrably routes through `notify()`, but adding it to that list would extend the automated guard. `ops/tests.py` was outside this plan's `files_modified`, so it was left alone.
- `web/guard.py:54` `_guard_floor_ids` still uses `a.floors.values_list("pk", flat=True)` after `prefetch_related("floors")`, which re-queries per assignment. Harmless there (one user, per poll) and `web/` was explicitly out of scope for this plan, but it is the same mistake `ops/guard_alerts.py` deliberately avoids.
