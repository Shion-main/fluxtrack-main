---
phase: 07-remaining-operational-surfaces
plan: 06
subsystem: web/ifo
tags: [ifo, bookings, availability, audit, authz]
requires:
  - ops.availability.room_is_free (Phase 4)
  - ops.Booking (Phase 1) + ops migration 0005 room PROTECT (07-02)
  - web.pagination.paginate
provides:
  - web.ifo.bookings_list
  - web.ifo.booking_create
  - web.ifo.booking_cancel
  - web.ifo._safe_parse_date / _safe_parse_time
  - ifo_bookings / ifo_booking_create / ifo_booking_cancel URL names
  - AuditLog events booking.created / booking.cancelled
affects:
  - templates/ifo/_console.html
  - web.ifo.assignment_create (latent 500 fixed)
tech-stack:
  added: []
  patterns:
    - single-oracle conflict check; no second overlap query in the web layer
    - cancellation as a status flip, never a delete
    - format-before-ORM validation ladder (CR-04)
key-files:
  created:
    - templates/ifo/bookings.html
    - templates/ifo/_booking_form.html
  modified:
    - web/ifo.py
    - web/urls.py
    - templates/ifo/_console.html
    - web/tests_ifo_ops.py
decisions:
  - No override control is built - a deliberate reading of D-09, recorded for operator review
  - Cancelled bookings stay visible in the list because they still block room deletes
  - parse_date/parse_time need a ValueError guard, not just an is-None test
metrics:
  duration: ~35 min
  tasks: 3
  files: 6
  tests_added: 22
status: complete
---

# Phase 7 Plan 06: IFO-05 Ad-hoc Bookings Summary

`ops.Booking` — a model that has existed since Phase 1 with only a Django-admin surface — now has a real IFO console UI, conflict-checked by the single canonical occupancy oracle and cancellable by a status flip.

## What was built

**`web/ifo.py`** gained an `Ad-hoc bookings (IFO-05)` section:

- `bookings_list` — GET-only. Renders the create form plus a paginated table (`BOOKING_PAGE_SIZE = 25`), `select_related("room__floor__building", "created_by")`, newest-first by `start_datetime`.
- `booking_create` — POST-only. Validation ladder in the plan's order: occupant name present and within length, purpose within length, room pk numeric, date parses, start parses, end parses, room resolves, `end > start`, then `room_is_free(room, start, end)`. Datetimes built with `timezone.make_aware(datetime.combine(...))`, matching `ops/availability.py:106`.
- `booking_cancel` — POST-only. Re-gates on `status != "active"`, flips to `"cancelled"`, saves with `update_fields`, audits.

`ops/availability.py` is **unmodified**, and no second overlap query exists anywhere in `web/ifo.py`.

**Templates.** `templates/ifo/bookings.html` is a thin shell around `#booking-panel`; `templates/ifo/_booking_form.html` holds the form and the table and is what create and cancel swap in, matching the `#assignment-panel` arrangement. Status chips use the existing `.pill--ok` / `.pill--neutral` family with an icon and a text label. Nav entry added to `templates/ifo/_console.html`.

**`web/tests_ifo_ops.py`** gained `BookingCreateTests` (10), `BookingCancelTests` (8), `BookingListTests` (3), plus a booking authz case on the existing authz class.

## Key decisions

**No override control — a deliberate reading of D-09, flagged for operator review.** D-09's parenthetical ("absent an explicit override") describes the default refusal; nothing in IFO-05 asks for a way to double-book over a scheduled class. Building one would let this console manufacture exactly the contradictory occupancy that JOB-02c detects and that IFO-08 (plan 07-05) now exists to clean up — three surfaces working against each other. Recorded here so the operator can overrule it. This is threat register entry T-07-27, disposition `accept`.

**The abutting-window and online-session tests are the ones that prove the oracle is shared.** A naive inclusive overlap comparison refuses a booking that starts exactly when another ends, which would make back-to-back bookings of a room impossible. A naive "any session in this room" query refuses a booking during an online class, needlessly locking a room nobody is in. Both pass only because the surface calls `room_is_free`.

**Cancelling is asserted against `room_is_free`, not against the status column.** Freeing the room is the property D-10 promises; the flip is merely the mechanism. The test calls the oracle directly before and after.

## Deviations from Plan

**1. [Rule 1 - Bug] `parse_time` / `parse_date` raise `ValueError` instead of returning `None`**

- **Found during:** Task 3
- **Issue:** The plan's ladder — and the existing `assignment_create` ladder it was modelled on — test `parse_time(raw) is None`. Django returns `None` only when the string does not *match* the expected shape. A string that matches the shape but carries an impossible value (`"25:99"`, `"2026-13-45"`) gets as far as constructing the `time`/`date` object and raises `ValueError`. So the ladder let through exactly the inputs an operator is most likely to fat-finger, as a 500 — the precise failure T-07-25 exists to prevent, arriving through the mitigation itself.
- **Fix:** Added `_safe_parse_date` / `_safe_parse_time` wrappers that catch `ValueError` and return `None`, and routed the booking ladder through them. Covered by the `"bad start time": {"start_time": "25:99"}` subtest.
- **Files modified:** `web/ifo.py`
- **Commit:** c2b6302

**2. [Rule 1 - Bug] `assignment_create` (IFO-06) carried the same latent 500**

- **Found during:** Task 3, immediately after fixing deviation 1
- **Issue:** Pre-existing, same file, same trap: `web/ifo.py assignment_create` validates `parse_date(date_raw) is None` and `parse_time(start_raw) is None`, so a `25:99` shift time 500s the duty-assignment form.
- **Fix:** Routed those three checks through the same `_safe_parse_*` helpers. No behaviour any test asserted changed — the form now returns its existing friendly 400 for these inputs instead of a 500.
- **Files modified:** `web/ifo.py`
- **Commit:** c2b6302
- **Note:** strictly this is outside the plan's scope boundary (a pre-existing defect, not one caused by this task). Fixed anyway because it is the identical defect in the same module, the fix is two lines against a helper this task already had to write, and leaving a known 500 sitting beside its cure would be worse than the scope purity.

## Files touched outside `files_modified`

- `templates/ifo/_console.html` — the Bookings nav entry. The plan's Task 1 text asked for this; the frontmatter list omitted it.

## Plan assumptions that turned out wrong

- **The validation ladder as specified would have shipped a 500.** See deviation 1. The plan explicitly cited the CR-04 format-before-ORM rule and still specified an `is None` test, because the underlying `assignment_create` precedent it pointed at has the same hole.
- **`paginate()` returns `page`, not `page_obj`** (carried over from 07-05).

## Verification

`DB_TEST_NAME=test_fluxtrack_ifo python manage.py test` — **Ran 634 tests, FAILED (failures=3, skipped=2), 0 errors.** The 3 are the documented pre-existing ones.

`web.tests_ifo_ops` alone: Ran 37 tests, OK (15 from 07-05 + 22 new).

No files under `static/` were touched — the `.pill--ok` / `.pill--neutral` classes already existed in `static/css/app.css` — so no `collectstatic` was required.

## Self-Check: PASSED

- `templates/ifo/bookings.html` — FOUND
- `templates/ifo/_booking_form.html` — FOUND
- commit c2b6302 — FOUND
