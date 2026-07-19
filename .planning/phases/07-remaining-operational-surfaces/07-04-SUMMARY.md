---
phase: 07-remaining-operational-surfaces
plan: 04
subsystem: web/ifo
tags: [ifo, qr, credential-rotation, audit, authz]
requires:
  - campus.codes.new_room_credentials (07-02)
  - web.ifo.room_poster / ifo_room_poster (Phase 1)
  - campus.Room.code_rotated_at / code_rotated_by (Phase 1, previously unwritten)
provides:
  - web.ifo.room_rotate_confirm
  - web.ifo.room_rotate
  - ifo_room_rotate_confirm / ifo_room_rotate URL names
  - AuditLog event room.code_rotated
affects:
  - templates/ifo/poster.html
  - templates/ifo/room_detail.html
tech-stack:
  added: []
  patterns:
    - GET confirmation page for a destructive act (second use, after room_delete)
    - destructive act redirects to its remedy (D-14)
    - credential minting stays in campus.codes, never inline
key-files:
  created:
    - templates/ifo/room_rotate.html
  modified:
    - web/ifo.py
    - web/urls.py
    - templates/ifo/poster.html
    - templates/ifo/room_detail.html
    - web/tests_ifo_rooms.py
decisions:
  - Audit payload carries room code, floor label and rotation instant only -- never a credential value, old or new
  - Rotate entry point sits on the room detail page, not on the poster (the poster is the remedy, not the decision)
  - Collision regression guard is deterministic (patched randbelow), never probabilistic
metrics:
  duration: ~20 min
  tasks: 2
  files: 6
  tests_added: 16
status: complete
---

# Phase 7 Plan 04: IFO-02 Credential Rotation Summary

Rotating a room's QR token and six-digit code is now a two-step IFO console act: a confirm page that names the dead-poster consequence for that specific room, then a POST-only rotation that mints through `campus.codes.new_room_credentials()` and lands the operator on the reprint page.

## What was built

**`web/ifo.py`** gained a `Credential rotation (IFO-02)` section with two views behind `ifo_required`:

- `room_rotate_confirm` — `@require_http_methods(["GET"])`. Renders `templates/ifo/room_rotate.html` with the room and its last-rotated stamp.
- `room_rotate` — `@require_http_methods(["POST"])`. Inside `transaction.atomic()`: obtains a fresh pair from `new_room_credentials()`, assigns `qr_token` / `manual_code`, stamps `code_rotated_at` / `code_rotated_by`, saves with `update_fields` naming exactly those four columns, writes the `room.code_rotated` AuditLog, then `redirect("ifo_room_poster", code=room.code)`.

**`templates/ifo/room_rotate.html`** — new confirm page extending `ifo/_console.html`. Names the room code in the warning, states that the QR and the printed six digits die together, lists what happens on confirm (new pair, land on poster, reprint and re-tape), shows the last-rotated stamp, and points at `room_edit` for the case where the operator actually wanted a name/capacity change. `uk-alert uk-alert-destructive` with `role="alert"`, icon plus text label, no border-left stripes.

**`templates/ifo/poster.html`** — a screen-only (`no-print`) rotation stamp so the operator arriving from a rotation can tell the new poster from a cached render of the old one.

**`web/tests_ifo_rooms.py`** — `RoomRotateTests` (13) and `RoomRotateAuthzTests` (3).

## Key decisions

**The audit payload carries no credential value.** `qr_token` and `manual_code` are resolver-only secrets never rendered client-side (SCAN-07, §6.2), and the AuditLog table is read far more widely than the two columns a payload would be describing. Payload is `{code, floor, rotated_at}`. Asserted by a test that checks the serialized payload against all four values (old pair and new pair).

**The "old credentials are dead" assertions are the load-bearing ones.** Asserting inequality on the two columns is a strictly weaker claim than asserting the old values resolve to no Room at all — an implementation that rotated only the token would pass the first and still leave a live six-digit code printed on a poster the operator believes is dead. The tests assert `Room.objects.filter(qr_token=<old>)` and `...filter(manual_code=<old>)` both come back empty.

**The collision guard is deterministic.** `campus.codes.secrets.randbelow` is patched to hand back a value another Room already holds on the first draw. The rotation must still succeed with a distinct code and no `IntegrityError`. That only passes if the view goes through `generate_manual_code`, so the test is also the structural guard against a future inline remint.

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Rotation had no entry point**

- **Found during:** Task 1
- **Issue:** The plan's `files_modified` listed `templates/ifo/poster.html` but not `templates/ifo/room_detail.html`. Without an entry point the two views were reachable only by typing the URL — a stub surface.
- **Fix:** Added a `Rotate codes` ghost button to the `page_actions` block in `templates/ifo/room_detail.html`, beside the existing Edit and Delete controls. Placed there rather than on the poster because the poster is the remedy for a rotation, not the decision to make one. Per the 07-03 note, it is on the full page, not inside a polled region.
- **Files modified:** `templates/ifo/room_detail.html`
- **Commit:** acb0d34

## Files touched outside `files_modified`

- `templates/ifo/room_detail.html` — the entry-point deviation above.

## Plan assumptions that held

- `campus.codes.new_room_credentials()` exists and retries the six-digit half only — confirmed, used verbatim.
- `ifo_room_poster` accepts `code=` — confirmed.
- `room_qr` regenerates from `room.qr_token` on demand, so nothing needed cache invalidation — confirmed.

## Verification

`DB_TEST_NAME=test_fluxtrack_ifo python manage.py test` — **Ran 595 tests, FAILED (failures=3, skipped=2), 0 errors.** The 3 are the documented pre-existing `DevLoginCoexistTests`, `DevLoginCuratedDemoTests` and `HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

`web.tests_ifo_rooms` alone: Ran 56 tests, OK (40 pre-existing from 07-03 + 16 new).

No files under `static/` were touched, so no `collectstatic` was required.

## Self-Check: PASSED

- `templates/ifo/room_rotate.html` — FOUND
- commit acb0d34 — FOUND
