---
phase: 05-notifications-read-surface-web-push
plan: 03
subsystem: notifications
tags: [web-push, pywebpush, outbox, scheduler, apscheduler, fault-isolation, tdd, vapid]

# Dependency graph
requires:
  - phase: 05-notifications-read-surface-web-push
    provides: "ops/notifications.py PUSH_TYPES + muted_types (D-06 single source); Notification.pushed_at outbox stamp (05-01)"
  - phase: 05-notifications-read-surface-web-push
    provides: "settings.VAPID_PRIVATE_KEY_PATH / VAPID_SUB + push_outbox_interval_seconds policy (05-02)"
  - phase: 02-correctness-foundations
    provides: "ops.jobrun.run_job observability wrapper (never re-raises) + notify() write path"
provides:
  - "ops/push.py: _send_one(sub, payload) + send_push_outbox() — outbox sender with 404/410 pruning, mute suppression, single pushed_at stamp, VAPID-disabled short-circuit"
  - "push_outbox job registered as the 4th job on the single BlockingScheduler (runscheduler), wrapped in run_job (criterion #4)"
  - "ops/tests_push.py: 9 mocked-webpush tests (send/prune-404-410/transient-keep/mute/non-key/no-raise/disabled)"
affects: [05-05-client-subscription, phase-06-weekly-report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DB-backed outbox drained ONLY by the scheduler process — the triggering web request does zero push network I/O (criterion #4 by construction, not by timeout luck)"
    - "Prune-on-dead-only: subscriptions deleted solely on 404/410; transient failures kept and treated as handled this pass (T-05-08)"
    - "Windowed scan (created_at >= now-15m) bounds outbox work under keep-all retention"
    - "Same D-06 filter (PUSH_TYPES + muted_types) imported by push and list surfaces so they can never disagree"

key-files:
  created:
    - "ops/push.py"
    - "ops/tests_push.py"
  modified:
    - "scheduling/management/commands/runscheduler.py"
    - "scheduling/tests.py"

key-decisions:
  - "send_push_outbox() lives only in the scheduler's push_outbox job (4th job on the single BlockingScheduler); the scan/approval/job path only writes Notification rows, so a hung endpoint is structurally unable to touch the triggering request (criterion #4)"
  - "_send_one prunes ONLY on WebPushException 404/410; every other failure (429/5xx/timeout/network) returns True (kept, handled this pass) so a flaky vendor never drops a live subscription (T-05-08) and rows are never retried forever"
  - "timeout=10 hard cap on every webpush call so a hung endpoint can never stall the job (T-05-05); the function never raises"
  - "Muted category suppresses the push but still stamps pushed_at (D-05) so the row is never re-scanned; muted rows are stamped-not-counted (return value counts only actual sends)"
  - "Did not import PushSubscription into ops/push.py (pruning goes through n.user.push_subscriptions.all() + sub.delete()); avoided an unused import — plan named the symbol but the reverse relation is the only access path used"

patterns-established:
  - "Fault-isolated outbox: writer emits a row; a separate scheduler process drains it — no cross-process push I/O on the request path"
  - "run_job-wrapped job registration keeps every scheduled callable non-fatal to the BlockingScheduler"

requirements-completed: [NOTIF-02, NOTIF-03]

coverage:
  - id: D1
    description: "send_push_outbox sends only unpushed PUSH_TYPES rows in the recent window, stamps pushed_at once, never re-sends"
    requirement: "NOTIF-02"
    verification:
      - kind: unit
        ref: "ops/tests_push.py::PushOutboxTests::test_success_sends_once_and_stamps,test_non_key_type_ignored"
        status: pass
    human_judgment: false
  - id: D2
    description: "Dead endpoint (404/410) pruned; transient 5xx/no-response kept; never raises (D-09/T-05-08)"
    requirement: "NOTIF-02"
    verification:
      - kind: unit
        ref: "ops/tests_push.py::PushOutboxTests::test_prune_on_410,test_prune_on_404,test_transient_500_keeps_subscription,test_transient_no_response_keeps_subscription"
        status: pass
    human_judgment: false
  - id: D3
    description: "Muted category suppresses push but stamps pushed_at (D-05)"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "ops/tests_push.py::PushOutboxTests::test_mute_suppresses_send_but_stamps"
        status: pass
    human_judgment: false
  - id: D4
    description: "push_outbox registered as a 4th job on the single BlockingScheduler; run_job wrap keeps a bad pass non-fatal (criterion #4)"
    requirement: "NOTIF-02"
    verification:
      - kind: unit
        ref: "scheduling/tests.py::SchedulerWiringTests::test_build_scheduler_registers_exactly_four_jobs_unstarted; ops/tests_push.py::RunJobNoRaiseTests"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-07-09
status: complete
---

# Phase 05 Plan 03: Fault-Isolated Web-Push Outbox Summary

**A DB-backed push outbox (`ops/push.py`) drained ONLY by a new `push_outbox` job on the single BlockingScheduler: it sends unpushed key-event rows via pywebpush, prunes dead endpoints on 404/410, suppresses muted categories while still stamping, and can never raise into the triggering request (criterion #4) — locked by 9 mocked-webpush tests.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-07-09T14:25:13Z
- **Completed:** 2026-07-09T14:39:00Z
- **Tasks:** 3
- **Files modified:** 4 (2 created code, 2 modified)

## Accomplishments
- `ops/push.py` `_send_one(sub, payload)`: wraps `webpush(...)` with a hard `timeout=10` (T-05-05), prunes ONLY on WebPushException status 404/410 (returns False), keeps every transient/status-less failure (returns True), and never raises (criterion #4).
- `ops/push.py` `send_push_outbox()`: short-circuits to 0 when VAPID is unconfigured; scans `Notification` rows where `type in PUSH_TYPES`, `pushed_at IS NULL`, `created_at >= now-15m`; suppresses+stamps muted rows (D-05); pushes to every subscription, prunes dead endpoints (D-09), stamps `pushed_at` once, and returns the sent count.
- `runscheduler.build_scheduler()` now registers a 4th `push_outbox` job wrapped in `run_job`, `IntervalTrigger(seconds=get_policy("push_outbox_interval_seconds"))`, `max_instances=1`, `coalesce=True`, `misfire_grace_time=60`; the startup line lists `push_outbox (every N s)` in ASCII (Conventions #4). No second scheduler process (ENV-04 preserved).
- `ops/tests_push.py`: 9 tests with `ops.push.webpush` patched — success+re-send guard, 410 prune, 404 prune, transient-500 keep, status-less keep, mute suppression, non-key ignore, VAPID-disabled short-circuit, and run_job no-reraise.

## Task Commits

1. **Task 3 (RED): failing outbox tests** — `70b5226` (test) — committed failing (ModuleNotFoundError: ops.push).
2. **Task 1 (GREEN): ops/push.py sender + pruning** — `f42e7fb` (feat) — turned the RED suite green (9/9).
3. **Task 2: register push_outbox job + update wiring test** — `9db5c5b` (feat).

_TDD note: Task 1 (`tdd="true"`) and its Task 3 test file were executed RED -> GREEN. The test file was committed failing (module absent), then `ops/push.py` turned it green. No refactor commit needed._

## Files Created/Modified
- `ops/push.py` (created) — `_send_one` + `send_push_outbox` + module docstring citing NOTIF-02 / criterion #4 / D-08 / D-09; imports `PUSH_TYPES` + `muted_types` from `ops.notifications` (D-06 single source).
- `ops/tests_push.py` (created) — 9 mocked-webpush tests across `PushOutboxTests` + `RunJobNoRaiseTests`.
- `scheduling/management/commands/runscheduler.py` (modified) — `send_push_outbox` import, 4th `push_outbox` job, startup line, docstring updated to "4 jobs".
- `scheduling/tests.py` (modified) — `SchedulerWiringTests` updated to assert the 4-job set incl. `push_outbox` (see Deviations).

## Decisions Made
- Push send lives only in the scheduler; the emitting request writes rows only — criterion #4 is guaranteed by structure, not by a timeout.
- Prune on 404/410 exclusively; transient/status-less failures are kept and treated as handled this pass, so a flaky vendor never drops a live subscription (T-05-08) and no row is retried forever.
- Muted rows are stamped but not counted; the return value counts only real sends (matches the plan's "count of rows it processed to send").
- `PushSubscription` was not imported into `ops/push.py` — pruning uses `n.user.push_subscriptions.all()` + `sub.delete()`, so importing the class would be dead weight. The plan named the symbol; the reverse relation is the only access path exercised.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Updated SchedulerWiringTests for the 4th job**
- **Found during:** Task 2 verification (`py -3.12 manage.py test ops scheduling`).
- **Issue:** `scheduling/tests.py::SchedulerWiringTests::test_build_scheduler_registers_exactly_three_jobs_unstarted` asserts the scheduler holds EXACTLY `{materialize, sweep, weekly_report}`. The plan intentionally adds a 4th `push_outbox` job (ENV-04 still one process), so the existing guard went RED by design.
- **Fix:** Renamed the test to `..._exactly_four_jobs_unstarted`, added `push_outbox` to the expected set, and refreshed the class docstring/comment to "4 jobs". Behavior unchanged; the ENV-04 one-process invariant is still asserted.
- **Files modified:** `scheduling/tests.py`
- **Commit:** `9db5c5b`

## Issues Encountered
- One transient error surfaced once in a full `scheduling`-only run but not in the combined `ops scheduling` run nor on re-run of the wiring class; the authoritative combined regression is green (221 tests, `OK`, 2 skipped). Not related to this plan's changes.

## Threat Model Coverage
- **T-05-05 (DoS, hung endpoint):** `timeout=10` per `webpush` call + broad except that never raises; runs only in the scheduler, never a web worker. Covered structurally + by `test_transient_no_response_keeps_subscription`.
- **T-05-07 (DoS, outbox pass):** job wrapped by `run_job` (records failed, never re-raises — `RunJobNoRaiseTests`); windowed scan bounds work; `max_instances=1` + `coalesce` prevent pile-up.
- **T-05-08 (tampering, pruning):** prune ONLY on 404/410; `test_transient_500_keeps_subscription` + `test_transient_no_response_keeps_subscription` lock that a flaky vendor keeps live subscriptions.
- **T-05-13 (SSRF):** accepted — endpoints come only from validated `PushSubscription` rows (endpoint validation lands in 05-05); the sender never follows arbitrary user input.

## User Setup Required
None. Push activates automatically once `VAPID_PRIVATE_KEY_PATH` points at a real PEM (already populated locally in 05-02) and the scheduler runs; an empty key path keeps push disabled with no error.

## Next Phase Readiness
- 05-05 (client subscription/render) can rely on the outbox: once a `PushSubscription` exists and a key-event row is written, the scheduler delivers it within `push_outbox_interval_seconds`.
- Phase 6's weekly-report job emitting `WEEKLY_REPORT_READY` rows will start firing push automatically (that type is already in `PUSH_TYPES`).
- No blockers.

## Self-Check: PASSED

- FOUND: ops/push.py, ops/tests_push.py, scheduling/management/commands/runscheduler.py, scheduling/tests.py
- FOUND commits: 70b5226, f42e7fb, 9db5c5b
- Tests: `ops.tests_push` 9/9 OK; `SchedulerWiringTests` OK; combined `ops scheduling` 221 OK (2 skipped)

---
*Phase: 05-notifications-read-surface-web-push*
*Completed: 2026-07-09*
