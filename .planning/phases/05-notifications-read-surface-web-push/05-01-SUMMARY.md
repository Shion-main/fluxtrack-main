---
phase: 05-notifications-read-surface-web-push
plan: 01
subsystem: database
tags: [notifications, django, mute-preferences, textchoices, migration, tdd]

requires:
  - phase: 02-correctness-foundations
    provides: "notify() single Notification write path (NOTIF-00) + Notification model"
provides:
  - "NotificationMute model (per-user, presence-as-mute, default-unmuted)"
  - "Notification.pushed_at outbox stamp + (user, read_at) unread index"
  - "ops/notifications.py: NotificationCategory, CATEGORY_TYPES (single source of truth D-06), TYPE_CATEGORY, PUSH_TYPES, WEEKLY_REPORT_READY"
  - "muted_types / visible_qs / unread_count / _mark_read helpers"
affects: [05-03-push-filter, 05-04-list-filter, 05-05-render, phase-06-weekly-report]

tech-stack:
  added: []
  patterns:
    - "Single category->type map (D-06): one map both list filter and push filter import so they can never disagree"
    - "Presence-as-mute: row presence = muted, absence = unmuted; default-unmuted with zero seed rows and no boolean column"
    - "Derived-from-forward reverse map (TYPE_CATEGORY) so it can never drift"

key-files:
  created:
    - "ops/notifications.py"
    - "ops/tests_notifications.py"
    - "ops/migrations/0004_notificationmute_pushed_at.py"
  modified:
    - "ops/models.py"

key-decisions:
  - "CATEGORY_TYPES is the ONE place the three mute groups (ROOM/REPORTS/SYSTEM) are defined (D-06); TYPE_CATEGORY derived from it, never hand-maintained"
  - "Unmapped notify() types (checker_flag, online_*, modality_shift_*) are always-shown / never-mutable this phase (owner default #1) via .get(cat, set())"
  - "WEEKLY_REPORT_READY = 'weekly_report_ready' defined now as the Phase 5<->6 contract string (owner default #2); its push won't fire until Phase 6 emits rows"
  - "_mark_read writes NO AuditLog -- audit-silent read surface, a sanctioned exception to Convention #2 mirroring notify()'s own no-audit rule"
  - "Migration file renamed to plan artifact name 0004_notificationmute_pushed_at.py (Phase 04 precedent)"

patterns-established:
  - "Single source of truth map (D-06): forward map defined once, reverse derived"
  - "Presence-as-mute per-user preference with unique_together(user, category)"

requirements-completed: [NOTIF-01, NOTIF-02, NOTIF-03]

coverage:
  - id: D1
    description: "NotificationMute model + Notification.pushed_at + (user, read_at) index, migrated"
    requirement: "NOTIF-02"
    verification:
      - kind: unit
        ref: "py -3.12 manage.py makemigrations ops --check --dry-run (no pending)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Single category->type map CATEGORY_TYPES + TYPE_CATEGORY + PUSH_TYPES + WEEKLY_REPORT_READY contract (D-06)"
    requirement: "NOTIF-01"
    verification:
      - kind: unit
        ref: "ops/tests_notifications.py::MapInvariantTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "muted_types/visible_qs/unread_count: default-unmuted, mute suppresses list, unmapped-always-shown"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "ops/tests_notifications.py::MutedTypesTests,VisibleQsTests"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-09
status: complete
---

# Phase 5 Plan 01: Notifications Data Foundation Summary

**Per-user mute-by-category model, Notification.pushed_at outbox stamp, and the single D-06 category->type map with muted_types/visible_qs/unread_count helpers, TDD-locked by 15 unit tests.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-09
- **Tasks:** 3
- **Files modified:** 4 (2 created code, 1 migration, 1 model edit; + 1 test file)

## Accomplishments
- `NotificationMute` model implementing presence-as-mute (row present = category muted; absent = unmuted), unique_together on (user, category), zero seed rows so default is everything-unmuted (D-05).
- `Notification.pushed_at` outbox stamp for the 05-03 push scheduler, plus a `(user, read_at)` index backing the unread-badge query.
- `ops/notifications.py` establishing the D-06 single source of truth: `CATEGORY_TYPES` (ROOM/REPORTS/SYSTEM), `TYPE_CATEGORY` derived from it, `PUSH_TYPES`, and the `WEEKLY_REPORT_READY` Phase 5<->6 contract constant.
- `muted_types`, `visible_qs`, `unread_count`, and audit-silent `_mark_read` helpers, all user-scoped (no cross-user PK access).
- 15 unit tests covering the partition invariant, contract constants, default-unmuted, mute-suppresses-list, unmapped-always-shown, and unread_count semantics.

## Task Commits

1. **Task 1: NotificationMute + pushed_at + unread index** - `9d9d7d5` (feat)
2. **Task 3 (RED): failing tests for map + helpers** - `d9599e2` (test)
3. **Task 2 (GREEN): category->type map + helpers** - `b09a386` (feat)

_TDD note: Task 2 (`tdd="true"`) and its Task 3 test file were executed RED -> GREEN. The test file was committed failing (module absent), then the implementation turned it green. No refactor commit needed._

## Files Created/Modified
- `ops/models.py` - Added `NotificationMute` model; added `pushed_at` field and `(user, read_at)` index to `Notification`.
- `ops/migrations/0004_notificationmute_pushed_at.py` - Migration for the model + field + index (renamed to plan artifact name).
- `ops/notifications.py` - Category enum, single map, derived reverse map, push set, contract constant, and the four helpers.
- `ops/tests_notifications.py` - 15 tests across MapInvariantTests / MutedTypesTests / VisibleQsTests.

## Decisions Made
- Verified all four mapped notify() type strings exist in-repo before mapping them: `room_event` (web/scan.py), `room_conflict` (scheduling/jobs.py), `job_failed` (ops/jobrun.py), `modality_materialize_no_room` (materialize_sessions.py). `weekly_report_ready` is the only forward-declared type (Phase 6 contract).
- `muted_types` uses `CATEGORY_TYPES.get(cat, set())` so a stored category outside the map contributes nothing (T-05-02) and unmapped types can never be muted (owner #1).
- Kept `NotificationMute.category` a plain `CharField` (not a FK/enum-typed column) holding a `NotificationCategory` value, avoiding a models.py -> notifications.py import cycle.

## Deviations from Plan

**Migration filename** — `makemigrations` produced `0004_notificationmute_notification_pushed_at_and_more.py`; renamed to the plan's declared artifact name `0004_notificationmute_pushed_at.py` before it was depended upon (Phase 04 rename precedent). Migration internals were not hand-edited. Not a behavioral deviation.

Otherwise: None - plan executed exactly as written.

## Issues Encountered
None. RED failed as expected (ModuleNotFoundError), GREEN passed 15/15, ops regression 53/53 green, `makemigrations --check` reports no pending changes.

## Threat Model Coverage
- T-05-01 (info disclosure): helpers query only `user.notifications` / `user.notification_mutes` — no PK-addressed cross-user access. Verified by user-scoped tests.
- T-05-02 (tampering): `.get(cat, set())` neutralizes unknown stored categories; partition test blocks a type landing in two groups. `test_unknown_stored_category_mutes_nothing` covers it.
- T-05-03 (XSS at render): accepted here (store/filter only); escaping enforced in 05-04/05-05.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 05-03 (push filter) and 05-04 (list filter) can now both import `CATEGORY_TYPES` / `PUSH_TYPES` / `visible_qs` / `unread_count` from the single source of truth.
- Phase 6 weekly-report job can import `WEEKLY_REPORT_READY` and emit rows of that type; push will start firing once rows exist.

## Self-Check: PASSED

- FOUND: ops/models.py, ops/migrations/0004_notificationmute_pushed_at.py, ops/notifications.py, ops/tests_notifications.py
- FOUND commits: 9d9d7d5, d9599e2, b09a386

---
*Phase: 05-notifications-read-surface-web-push*
*Completed: 2026-07-09*
