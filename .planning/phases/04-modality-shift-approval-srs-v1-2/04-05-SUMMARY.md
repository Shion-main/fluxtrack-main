---
phase: 04-modality-shift-approval-srs-v1-2
plan: 05
subsystem: api
tags: [django, transactions, toctou, room-availability, notifications, modality-shift]

# Dependency graph
requires:
  - phase: 04-04
    provides: submit_modality_shift, affected_sessions, _in_window_sessions, reject/withdraw, ModalityShiftError
  - phase: 04-03
    provides: ops/availability room_is_free / free_rooms_in_building / faculty_has_conflict (request-aware, D-18)
  - phase: 02
    provides: ops/occupancy release_room (room_released_at + audit), ops/notify notify single write path
provides:
  - "apply_approval — transactional, TOCTOU-safe, all-or-nothing Dean-approval apply"
  - "_apply_online — declared_modality=Online + release_room per in-window session (MOD-03)"
  - "_apply_f2f — server-side room re-resolution + reservation + bundled time-move (MOD-04)"
  - "resolve_shift_room — original-room-if-free-else-first-free-in-building selector"
  - "terminal DENIED on no free room / double-book (D-07 REVISED), decision + IFO notifications (D-11)"
affects: [04-06 materialize born-released/assigned, 04-07 web submit/picker, dean approval queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Nested transaction.atomic() savepoint for all-or-nothing apply with a rollback-and-DENY sentinel"
    - "Server-side room re-resolution at write time (never trust a client room pk) — TOCTOU re-check"
    - "declared_modality override as the single effective-modality signal read by all consumers"

key-files:
  created: []
  modified:
    - scheduling/services.py
    - scheduling/tests.py

key-decisions:
  - "No-room / double-book raises an internal _NoRoomAvailable sentinel caught outside a nested savepoint so the DENIED status commits while every session/item write rolls back"
  - "resolve_shift_room resolves BEFORE mutating the session (exclude_session_id keeps a session from blocking itself)"
  - "item.assigned_room stores the resolved room as the D-18 reservation the 04-03 availability query treats as occupied"

patterns-established:
  - "Savepoint-scoped consequence: apply inside an inner atomic; catch the domain sentinel in the outer atomic to persist a terminal decision with nothing changed"
  - "Effective-modality coupling asserted with the exact `declared_modality or schedule.modality` expression the resolver/sweep/availability readers use"

requirements-completed: [MOD-03, MOD-04, MOD-05, MOD-06]

coverage:
  - id: D1
    description: "Approving a ->Online shift sets declared_modality=Online + modality_changed_at/by and calls release_room() (room_released_at stamped, room FK never nulled) on each in-window session"
    requirement: "MOD-03"
    verification:
      - kind: integration
        ref: "scheduling/tests.py#ApplyOnlineTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Effective modality (declared_modality or schedule.modality) reads Online after apply; a released online session no longer occupies its room"
    requirement: "MOD-06"
    verification:
      - kind: integration
        ref: "scheduling/tests.py#EffectiveModalityCouplingTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Approving a ->F2F/Blended shift assigns the original room if free else the first free room in the building, re-resolved inside the transaction, and reserves it on item.assigned_room; bundled time-move rewrites scheduled_start/end after faculty_has_conflict re-check"
    requirement: "MOD-04"
    verification:
      - kind: integration
        ref: "scheduling/tests.py#ApplyF2FTests"
        status: pass
      - kind: integration
        ref: "scheduling/tests.py#ApproveRaceTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "No free room that day (or a double-booking time-move) denies the whole ticket terminally with nothing changed on any session (all-or-nothing, D-07 REVISED)"
    requirement: "MOD-04"
    verification:
      - kind: integration
        ref: "scheduling/tests.py#ApplyF2FNoRoomTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "submit notifies Dean; approve notifies requester + IFO informational; reject and deny notify requester — all via notify()"
    requirement: "MOD-05"
    verification:
      - kind: integration
        ref: "scheduling/tests.py#ShiftNotifyTests"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-03
status: complete
---

# Phase 4 Plan 05: Modality-Shift Approval Apply Summary

**Transactional, TOCTOU-safe Dean-approval apply — releases rooms for ->Online, re-resolves and reserves a real room for ->F2F/Blended, terminally denies the whole ticket when no room is free, applies bundled time-moves without double-booking, and fires decision + IFO notifications — all atomic and audited.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-03T15:55Z (approx)
- **Completed:** 2026-07-03T16:15Z
- **Tasks:** 3 (all TDD)
- **Files modified:** 2

## Accomplishments
- `apply_approval(request, dean, *, now=None)` re-gates Dean + department + PENDING inside `transaction.atomic()` (03-02 re-gate) and dispatches the modality consequence.
- ->Online path (`_apply_online`): each in-window session flips to `declared_modality=Online` and calls `release_room()` (stamps `room_released_at`, never nulls the room FK), making the shift visible to every effective-modality reader unchanged (MOD-03/MOD-06).
- ->F2F/Blended path (`_apply_f2f` + `resolve_shift_room`): re-resolves the room INSIDE the transaction (original if free, else first free in building), rewrites scheduled_start/end for a bundled time-move after a `faculty_has_conflict` re-check, and writes `item.assigned_room` as the D-18 reservation for future sessions (MOD-04/D-06/D-16).
- No-room / double-book: an internal `_NoRoomAvailable` sentinel rolls back all session/item writes via a nested savepoint and sets a terminal `DENIED` with a reason — no silent partial apply (D-07 REVISED / D-19).
- Notifications via the single `notify()` path: approve -> requester + IFO informational; deny -> requester (D-11).

## Task Commits

Each task was committed atomically (test + implementation in one commit per task):

1. **Task 1: apply_approval skeleton + ->Online consequence + effective-modality coupling** - `75bcee5` (feat)
2. **Task 2: ->F2F/Blended consequence — TOCTOU re-resolve, reserve, time-move** - `d04af32` (feat)
3. **Task 3: no-room DENY (terminal, all-or-nothing) + decision/IFO notifications** - `909a415` (feat)

_Each TDD task went RED (failing test) -> GREEN (implementation) before commit._

## Files Created/Modified
- `scheduling/services.py` - Added `apply_approval`, `_apply_online`, `_apply_f2f`, `resolve_shift_room`, `_NoRoomAvailable`; extended imports (`room_is_free`, `free_rooms_in_building`, `release_room`).
- `scheduling/tests.py` - Added `ApplyOnlineTests`, `EffectiveModalityCouplingTests`, `ApplyF2FTests`, `ApproveRaceTests`, `ApplyF2FNoRoomTests`, `ShiftNotifyTests` + `_pending_request` / `_occupy_room` helpers.

## Decisions Made
- **Nested savepoint for all-or-nothing:** the consequence runs inside an inner `transaction.atomic()`; `_NoRoomAvailable` is caught in the outer atomic so the rollback discards every session/item write while the terminal `DENIED` status still commits. This is the cleanest way to satisfy "no partial apply" (D-19) without pre-collecting every resolution.
- **Resolve before mutate:** `resolve_shift_room` runs with `exclude_session_id=session.pk` so the session being moved never blocks itself, and the room is chosen before `declared_modality`/`room` are written.
- **IFO body is descriptive, not a gate:** the applied notification names the count of sessions moved online or the room codes assigned, informational only (D-11).

## Deviations from Plan

The plan's Task 3 nested the no-free-room case into `ApplyF2FTests`. I placed it in a dedicated `ApplyF2FNoRoomTests` class instead (plus a `test_time_move_double_book_denies_terminally` case) for clarity of intent — the DENY behavior and no-partial-apply assertions are fully covered. This is a test-organization choice, not a behavioral change; all plan-named suites (`ApplyOnlineTests`, `ApplyF2FTests`, `ApproveRaceTests`, `ShiftNotifyTests`, `EffectiveModalityCouplingTests`) exist as specified.

Otherwise: None - plan executed as written.

## Issues Encountered
None. All three TDD cycles went RED then GREEN on the first implementation pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `apply_approval` and `resolve_shift_room` are ready for the 04-06 materializer (born-released/assigned future sessions consume `item.assigned_room` and `declared_modality`) and for the 04-07 Dean approval-queue view.
- Full regression green: `py -3.12 manage.py test scheduling ops` -> 118 tests OK (no regression in the effective-modality readers).

## Self-Check: PASSED

- FOUND: `.planning/phases/04-modality-shift-approval-srs-v1-2/04-05-SUMMARY.md`
- FOUND: commit `75bcee5` (Task 1)
- FOUND: commit `d04af32` (Task 2)
- FOUND: commit `909a415` (Task 3)
- Verification: `py -3.12 manage.py test scheduling ops` -> 118 tests OK.

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-03*
