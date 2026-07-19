---
phase: 07-remaining-operational-surfaces
plan: 03
subsystem: web/ifo
tags: [ifo, room-crud, delete-refusal, audit, authz]
requires:
  - campus.services.room_delete_blockers (07-02)
  - campus.codes.new_room_credentials (07-02)
  - ops migration 0005 (Booking.room PROTECT, 07-02)
provides:
  - web.ifo.room_new
  - web.ifo.room_edit
  - web.ifo.room_delete
  - ifo_room_new / ifo_room_edit / ifo_room_delete URL names
  - AuditLog events room.created / room.updated / room.deleted / room.delete_refused
affects:
  - templates/ifo/rooms.html
  - templates/ifo/room_detail.html
  - templates/ifo/_room_panel.html
tech-stack:
  added: []
  patterns:
    - hand-validated write + 400 re-render (no Django Forms), per PATTERNS.md 2.3
    - GET confirmation page for a destructive act (first in this codebase)
    - probe-as-primary-control + ProtectedError-as-backstop, both kept
key-files:
  created:
    - templates/ifo/room_form.html
    - templates/ifo/room_delete.html
    - web/tests_ifo_rooms.py
  modified:
    - web/ifo.py
    - web/urls.py
    - templates/ifo/rooms.html
    - templates/ifo/room_detail.html
    - templates/ifo/_room_panel.html
decisions:
  - Edit/Delete controls live on the slide-over panel and the room page, NOT on the polled board tiles
  - Room code is immutable on edit; renaming is create-then-delete, which the refusal correctly polices
  - The ProtectedError backstop got a deterministic test by blinding the probe
metrics:
  duration: ~35 min
  tasks: 3
  files: 8
  tests_added: 40
  completed: 2026-07-19
status: complete
---

# Phase 07 Plan 03: IFO Room CRUD + Named Delete Refusal — Summary

Rooms are now creatable, editable and deletable from the IFO console instead of
only through the Django admin or the importer — and a delete that would destroy
history is refused with every blocking relation named on screen.

## What Was Built

**Task 1 — create/edit** (`0833397`). `room_new` and `room_edit` in `web/ifo.py`
behind the existing `ifo_required`, GET renders the form, POST writes. New rooms
are born scannable: `qr_token` and `manual_code` come from
`campus.codes.new_room_credentials()` and nothing is minted inline, so the
importer's six-digit collision retry applies to the IFO path too. Editing
updates only name/capacity/floor and provably never touches the credentials.
Format and pk-numericness are validated before any ORM write (CR-04), so a
non-numeric floor or capacity is a friendly 400 with the submitted values kept,
never a 500. `room.created` and `room.updated` audit rows; the update payload
carries the changed field names and their before-values.

**Task 2 — delete with named refusal** (`63516bc`). `room_delete` serves a real
GET confirmation page (not a JS `confirm()`, which can show no detail and is
unreachable by keyboard/screen-reader users). An unreferenced room gets a Delete
button; a referenced room gets a `.tbl` table naming each blocking relation with
its count in plain language and **no delete control at all** — the refusal is
not advisory. POST re-runs the probe inside `transaction.atomic()`, catches
`ProtectedError` as the backstop, and audits both outcomes.

**Task 3 — tests** (`14ac7c9`). `web/tests_ifo_rooms.py`, 40 tests, four classes.

## Key Decisions

**Edit/Delete controls are not on the board tiles.** The plan said "add Edit /
Delete links to each room tile or row" *and* "keep the polled board partial
untouched" — those conflict, because the tiles live inside `_board.html`, which
is swapped wholesale every poll. A control rendered in a tile would be destroyed
mid-click every few seconds. Resolved by putting **New room** in the `rooms.html`
`page_actions` block (outside `#board`, so it survives polls) and **Edit/Delete**
on the slide-over panel and the full room page. The CRUD surface is fully
reachable and no filter or panel state is at risk. Documented in a template
comment so a later reader does not "fix" it back.

**Room code is immutable on edit.** The plan scoped edit to name/capacity/floor;
this makes the reason explicit in the view docstring — the code is what is
printed on the door and referenced by every schedule. Renaming means
create-then-delete, and the delete refusal correctly stops that if the old code
carries history.

**Audit writes happen after the `atomic` block, never inside it.** `ProtectedError`
subclasses `IntegrityError`, so writing an AuditLog inside the same transaction
after catching one risks a `TransactionManagementError` on MSSQL. Nothing is
written before Django's Collector raises, so the block commits as a clean no-op
and the audit row is written outside. The new backstop test confirms this
empirically.

## Deviations from Plan

**1. [Rule 3 — Blocking] Edit/Delete placement moved off the polled tiles.**
- **Found during:** Task 1
- **Issue:** The plan's two instructions for `rooms.html` were mutually exclusive.
- **Fix:** New room in `page_actions`; Edit/Delete on `_room_panel.html` and
  `room_detail.html`. Both files are outside the polled region.
- **Files modified:** `templates/ifo/rooms.html`, `templates/ifo/_room_panel.html`,
  `templates/ifo/room_detail.html` (the latter two are outside `files_modified`).
- **Commits:** `0833397`, `63516bc`

**2. [Rule 2 — Missing critical coverage] Added a deterministic ProtectedError test.**
- **Found during:** Task 3
- **Issue:** The plan named `ProtectedError` as one of two required controls but
  specified no test for it, since it is only reachable via a race. An untested
  backstop is indistinguishable from a decorative one.
- **Fix:** `test_the_protected_error_backstop_catches_what_the_probe_misses`
  patches `web.ifo.room_delete_blockers` to return `{}` with a real PROTECT
  reference present, reproducing the race deterministically.
- **Commit:** `14ac7c9`

**3. [Rule 2] Added authz POST coverage and a `preferred_room` negative test.**
- The plan asked for three-way GET authz; a 403 on GET with an unguarded POST
  would be no gate, so POST authz is asserted too. Separately,
  `test_a_faculty_preference_does_not_block` locks the deliberate exclusion
  `campus/services.py` documents — a preference is not a reservation.

## Plan Assumptions That Held

- The Wave 1 nuance was correct and load-bearing. `assigned_room` (SET_NULL) is
  genuinely refused **only** by the probe — the isolated reservation test passes
  with all four PROTECT relations at zero, which would delete silently without it.
- `campus.codes.new_room_credentials()` and `room_delete_blockers()` needed no
  changes; both were consumed exactly as built.
- `ifo/rooms/new` does get swallowed by `<str:code>` if registered after it;
  ordering is asserted by a test.

## Verification

Full suite: **`Ran 579 tests`, `FAILED (failures=3, skipped=2)`, 0 errors.**
Baseline was 539/3/0; the delta is exactly the 40 tests added here, and the 3
failures are the known pre-existing `DevLoginCoexistTests`,
`DevLoginCuratedDemoTests` and `HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

New module in isolation: `Ran 40 tests ... OK`.

No files under `static/` were touched, so `collectstatic` was not required.

Manual UAT items 2-6 in the plan (runserver, create TEST101, poster round-trip,
delete a real room with classes) are **not yet done** — they need a browser and
the loaded term.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, file access pattern or trust-boundary
schema change beyond the four `ifo_required`-gated views the threat model
already covers.

## Self-Check: PASSED

- `templates/ifo/room_form.html` — FOUND
- `templates/ifo/room_delete.html` — FOUND
- `web/tests_ifo_rooms.py` — FOUND
- `0833397`, `63516bc`, `14ac7c9` — all FOUND in git log
