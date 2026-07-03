---
phase: 04-modality-shift-approval-srs-v1-2
plan: 03
subsystem: ops
tags: [availability, room-booking, half-open-overlap, request-aware, modality-shift, mssql]

# Dependency graph
requires:
  - phase: 04-01
    provides: ModalityShiftRequest + ModalityShiftItem models (assigned_room reservation, status enum)
provides:
  - "ops.availability.room_is_free — the single half-open, building-scoped, Booking- and request-aware room-free primitive (D-08/D-18)"
  - "ops.availability.free_rooms_in_building — deterministically ordered free rooms, prefer_room floated first (D-06)"
  - "ops.availability.available_rooms_for — picker rooms free at the session's own slot, original room first (D-15 a/b)"
  - "ops.availability.available_times_for — same-day alternative time slots that never double-book the faculty (D-15c/D-16/D-17)"
  - "ops.availability.faculty_has_conflict — faculty double-book guard (D-17)"
  - "RoomAvailabilityTests — 15-case property-style suite in ops/tests.py"
affects: [04-05, 04-06, 04-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "half-open overlap predicate (O.start < end AND start < O.end) — adjacent slots free"
    - "effective-modality read (declared_modality or schedule.modality) shared verbatim with verification/services.py"
    - "list()-materialize candidate querysets before evaluation (MSSQL/pyodbc HY010 single-active-result-set guard)"
    - "request-aware occupancy: approved non-Online ModalityShiftItem.assigned_room reserves the slot before its Session materializes"

# Key files
key-files:
  created:
    - ops/availability.py
  modified:
    - ops/tests.py

# Decisions
decisions:
  - "available_times_for steps candidate slots across a fixed campus operating window (07:00-21:00) by the session's own duration, keeping class length unchanged and the current slot excluded as an 'alternative'"
  - "date-from-aware-datetime uses timezone.localtime(start).date() so weekday/window matching is done in Asia/Manila (project TIME_ZONE), consistent with the fixture and make_aware"

# Metrics
metrics:
  duration: ~35m
  completed: 2026-07-03
  tasks: 3
  files: 2
  commits: 6
  tests_added: 15

status: complete
---

# Phase 4 Plan 03: Room Availability Primitive Summary

A single `ops/availability.py` module now defines "is room R free for [start, end)?" once,
with half-open overlap semantics, building scope, `Booking` awareness, request-aware reservation
occupancy (D-18), and the picker/faculty-conflict helpers (D-15/D-17) that the approval apply
(04-05), materialize hook (04-06), and faculty picker (04-07) all consume rather than re-deriving.

## What was built

- **`room_is_free(room, start, end, *, exclude_session_id=None)`** — a room is occupied by (1) a
  SCHEDULED/ACTIVE, un-released same-room `Session` whose effective modality is not Online, (2) an
  active `Booking`, or (3) an approved ->F2F/Blended `ModalityShiftItem` reservation covering the
  slot. Overlap is half-open, so adjacent slots (`O.end == start`) do not collide. `exclude_session_id`
  removes the session being moved so it never blocks itself.
- **`free_rooms_in_building(building, start, end, *, exclude_session_id=None, prefer_room=None)`** —
  rooms in the building, ordered by `code`, filtered to the free ones, with `prefer_room` floated to
  the front when free.
- **`faculty_has_conflict(faculty, start, end, *, exclude_session_id=None)`** — True when the faculty
  already has another overlapping SCHEDULED/ACTIVE session (D-17 double-book guard).
- **`available_rooms_for(session)`** — building rooms free at the session's own scheduled slot,
  original `schedule.room` preferred first; empty when the preferred time is fully booked.
- **`available_times_for(session)`** — same-day alternative (start, end) slots (session duration,
  stepped across the operating window) that have a free room and do not double-book the faculty.

The effective-modality read (`declared_modality or schedule.modality`) is copied verbatim from
`verification/services.py` so the availability contract can never diverge from the resolver/sweep.
Every candidate queryset is `list()`-materialized before evaluation (MSSQL/pyodbc HY010 guard),
mirroring `scheduling/jobs.py`.

## How it was verified

TDD RED→GREEN per task (6 commits). `RoomAvailabilityTests` (15 cases) covers: overlap True/False,
adjacent-boundary free, released/online/absent/completed exclusion, active vs inactive Booking,
`exclude_session_id` self-exclusion, building scoping + `prefer_room` ordering, approved-reservation
occupies-before-materialize, ->Online/pending/out-of-window reserve nothing, faculty-conflict
true/exclude-moved/false, preferred-room-first, empty-rooms-when-full, and alternative-time offered
without double-booking.

- `py -3.12 manage.py test ops.tests.RoomAvailabilityTests -v2` → 21 tests OK
- `py -3.12 manage.py test ops` → 38 tests OK (no regression)

## Deviations from Plan

None - plan executed exactly as written. (The plan's five functions and the full property-suite were
implemented as specified; the picker helpers `available_rooms_for`/`available_times_for` reuse the
Task 1/2 primitives without re-deriving overlap.)

## Threat model coverage

| Threat ID | Disposition | How covered |
|-----------|-------------|-------------|
| T-04-02 | mitigate | Availability is computed server-side from Session/Booking/approved-request rows only — no client "is free" input; the 04-05 approval path re-checks in a transaction |
| T-04-05 | mitigate | `room_is_free` consults approved non-Online `ModalityShiftItem.assigned_room`; `test_approved_f2f_reservation_occupies_before_materialize` proves the not-yet-materialized case |
| T-04-06 | mitigate | `faculty_has_conflict` blocks offering a slot where the faculty already teaches; `available_times_for` filters on it |
| T-04-HY010 | mitigate | All candidate querysets `list()`-materialized before evaluation |

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: ops/availability.py (room_is_free, free_rooms_in_building, faculty_has_conflict, available_rooms_for, available_times_for)
- FOUND: ops/tests.py RoomAvailabilityTests (15 tests, all green)
- FOUND commits: e7db164, 58e541c, b07ab2a, 90c98f0, d89b70b, 0e37f91
