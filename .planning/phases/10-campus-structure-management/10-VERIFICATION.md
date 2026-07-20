# Phase 10 — Verification

**Status: COMPLETE (3/3 criteria). 2026-07-20.**
Suite: 994 tests, 0 failures, 2 skips. 29 new tests (14 structure + 6 room-service
+ 9 schedule-ops).

| # | Success criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | IFO can create/edit/delete buildings and floors; PROTECT-aware named delete; room-create floor picker shows new floors | PASS | `/ifo/buildings` + `/ifo/buildings/<pk>`; `campus.services.building_delete_blockers`/`floor_delete_blockers` (bottom-up: rooms -> floor -> building, refuse by name); `BuildingCrudTests`, `FloorCrudTests`, `BlockerServiceTests`. New floors flow into the room-create picker (shared `Floor` queryset). |
| 2 | Room out-of-service: scans refuse, cannot be booked, dropped from utilization denominator | PASS | `Room.out_of_service` (migration 0003) toggled from room detail; `web/scan.py` out-of-service outcome; `ifo.booking_create` refusal; `reporting._physical_rooms` exclusion; `ScanRefusalTests`, `BookingRefusalTests`, `UtilizationDenominatorTests`, `ToggleTests`. |
| 3 | IFO can add/edit/cancel a single schedule mid-term (not Django admin) + safe re-import note | PASS | `scheduling/schedule_ops.py` (update_schedule propagates to FUTURE SCHEDULED only; cancel_schedule ARCHIVE + Phase 9 CANCELLED); `/ifo/schedules/new|edit|cancel`; `UpdateScheduleTests`, `CancelScheduleTests`, `ScheduleConsoleTests`. |

## Design notes / deliberate scope
- **Bottom-up deletion** (rooms -> floor -> building), never a silent cascade — the
  same no-silent-loss discipline as `room_delete_blockers`.
- **Out-of-service vs delete:** a closed room keeps its record and schedules (soft,
  operational); deletion stays refused while a room carries history (integrity).
- **Schedule edit safety rule:** only future SCHEDULED sessions are ever touched;
  attendance history is never rewritten. `day_of_week` is not editable (would
  strand materialized sessions on the old weekday — a delete+rematerialize op).
- **KNOWN LIMITATION (deferred to Phase 14 / M3):** a schedule room move runs NO
  occupancy conflict check, consistent with the importer's existing behavior;
  JOB-02c surfaces contradictory ACTIVE occupancy. The conflict-checked version is
  Phase 14.

## Follow-ups
- Browser UAT of the new console pages (buildings, building_detail, schedule_form,
  the room-detail service/schedule cards) not yet run — fold into the milestone UI
  review / Phase 13.
- "Safe mid-term re-import procedure" doc (criterion 3's documentation half) still
  to be written — belongs with the Phase 16 docs pass.
