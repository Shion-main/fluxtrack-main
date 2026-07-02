---
phase: 02-correctness-foundations
plan: 04
subsystem: api
tags: [django, orm, auditlog, occupancy, room-release, tdd]

# Dependency graph
requires:
  - phase: 02-correctness-foundations (Plan 02-02)
    provides: ops/tests.py (NotifyTests/SingleWritePathTests) — the file this plan appends ReleaseRoomTests to
  - phase: 01-mssql-environment-data-foundation
    provides: Session model with room_released_at field, AuditLog model, make_session() test factory, TEST[NAME] override
provides:
  - "ops/occupancy.py::release_room(session, *, actor=None, now=None) — single source of truth for releasing a room"
  - "session.room_released AuditLog event contract (target_type=session, target_id=pk, payload.released_at)"
  - "ReleaseRoomTests proving the stamp + audit behaviour standalone"
affects: [phase-04-modality-shift, MOD-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-write-path helper for a state mutation (mirrors NOTIF-00 notify()): one auditable function owns room release"
    - "Built-not-wired: helper fully tested in Phase 2 with zero callers, reserved for a later phase (grep guard proves the cut)"

key-files:
  created:
    - ops/occupancy.py
  modified:
    - ops/tests.py

key-decisions:
  - "release_room() has ZERO Phase-2 callers by design — timer-based auto-release was cut 2026-07-03; only MOD-03 (Phase 4) will call it"
  - "Method-local imports in ReleaseRoomTests so only that class goes RED before ops/occupancy.py exists (02-02 classes stay collectable/green)"
  - "actor=None denotes a system-initiated release; AuditLog.actor is nullable (SET_NULL)"

patterns-established:
  - "State-mutation helper pairs save(update_fields=[...]) with an AuditLog row (Conventions rule 2)"
  - "released_at carried in AuditLog.payload as ISO-8601 string for a durable audit trail"

requirements-completed: [JOB-02c]

coverage:
  - id: D1
    description: "release_room(session) stamps Session.room_released_at with an aware datetime and writes exactly one session.room_released AuditLog (target_id=pk, payload.released_at); explicit actor/now recorded, default actor=None"
    requirement: "JOB-02c"
    verification:
      - kind: integration
        ref: "ops/tests.py#ReleaseRoomTests (5 tests) via `DB_TEST_NAME=test_fluxtrack_ops py -3.12 manage.py test ops.tests.ReleaseRoomTests`"
        status: pass
    human_judgment: false
  - id: D2
    description: "release_room() has zero Phase-2 production callers (reserved for MOD-03/Phase 4) — the sweep never releases rooms"
    requirement: "JOB-02c"
    verification:
      - kind: other
        ref: "grep `release_room(` across *.py → matches only ops/occupancy.py (defn) + ops/tests.py (tests)"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-03
status: complete
---

# Phase 02 Plan 04: release_room() Occupancy Helper Summary

**`ops.occupancy.release_room(session, *, actor=None, now=None)` — the single source of truth that stamps `Session.room_released_at` and writes a `session.room_released` AuditLog, fully tested but wired to nothing in Phase 2 (reserved for MOD-03 / Phase 4).**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-07-03T05:46Z (local session)
- **Completed:** 2026-07-03
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Built `ops/occupancy.py` with `release_room(session, *, actor=None, now=None)`: defaults `now` to `timezone.now()`, stamps `room_released_at` via `save(update_fields=["room_released_at"])`, and writes `AuditLog(event_type="session.room_released", target_type="session", target_id=str(pk), payload={"released_at": now.isoformat()})`.
- Added `ReleaseRoomTests` (5 tests) covering: the stamp is a non-null aware datetime, exactly one audit row per release, explicit `actor` recorded, default `actor=None`, and explicit `now=` honored on both the field and the payload.
- Confirmed the JOB-02c cut of timer-based auto-release: `release_room(` appears only in `ops/occupancy.py` (definition) and `ops/tests.py` (tests) — no Phase-2 production caller.
- Full `ops` suite green (12/12): the 7 Plan 02-02 tests (NotifyTests/SingleWritePathTests) remain untouched and passing.

## Task Commits

Each task was committed atomically (TDD):

1. **Task 1: Add ReleaseRoomTests (RED)** - `1acbd35` (test)
2. **Task 2: Build ops/occupancy.py release_room() (GREEN)** - `52516a9` (feat)

No REFACTOR commit — the GREEN implementation matched the research body exactly; no cleanup needed.

_Note: TDD tasks may have multiple commits (test → feat → refactor)_

## Files Created/Modified
- `ops/occupancy.py` (created) - `release_room()` occupancy helper; module + function docstrings state it is invoked ONLY by MOD-03 (Phase 4) and NEVER by the sweep.
- `ops/tests.py` (modified) - appended `ReleaseRoomTests(TestCase)` with method-local imports; added `datetime`/`timezone` stdlib imports for aware-datetime cases.

## Decisions Made
- **release_room() built but not wired:** zero Phase-2 callers by design. Timer-based auto-release was cut on 2026-07-03; the only future caller is MOD-03 (Phase 4) on an approved ->Online modality shift. The paired "sweep never stamps room_released_at" guard lives in Plan 02-03 SweepTests, not here.
- **Method-local imports in the test class:** mirrors the existing `NotifyTests` pattern so only `ReleaseRoomTests` goes RED before `ops/occupancy.py` exists — the 02-02 classes stay collectable and green throughout.
- **`actor=None` = system-initiated:** `AuditLog.actor` is nullable (SET_NULL), so an unauthenticated/system release is valid and audited.

## Deviations from Plan

None - plan executed exactly as written. The `Session.room_released_at` field already existed (added in Phase 1), so no model/migration change was needed; this plan touched only `ops/occupancy.py` and `ops/tests.py` per the parallel-execution coordination boundary.

## Issues Encountered
None. Test DB isolation via `DB_TEST_NAME=test_fluxtrack_ops` worked as specified — no collision with Plan 02-03's default `test_fluxtrack` under parallel Wave-2 execution.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `release_room()` is ready for MOD-03 (Phase 4) to consume without re-opening the module: it accepts an `actor` (the approving Dean) and an optional `now`, and self-audits.
- Coordination note for Plan 02-03: the "sweep NEVER stamps room_released_at" guard is that plan's responsibility (SweepTests); this plan proves the helper works standalone.

## Self-Check: PASSED

- FOUND: ops/occupancy.py
- FOUND: ops/tests.py (ReleaseRoomTests)
- FOUND: .planning/phases/02-correctness-foundations/02-04-SUMMARY.md
- FOUND commit: 1acbd35 (test RED)
- FOUND commit: 52516a9 (feat GREEN)

---
*Phase: 02-correctness-foundations*
*Completed: 2026-07-03*
