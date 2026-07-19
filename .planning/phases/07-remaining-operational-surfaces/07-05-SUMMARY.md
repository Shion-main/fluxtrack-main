---
phase: 07-remaining-operational-surfaces
plan: 05
subsystem: web/ifo + ops/occupancy
tags: [ifo, room-release, room-conflicts, invariant-amendment, audit, authz]
requires:
  - ops.occupancy.release_room (Phase 2)
  - scheduling.jobs.detect_room_conflicts JOB-02c auto-resolve (Phase 2)
  - ops.RoomConflictFlag filtered unique constraint (Phase 2)
provides:
  - web.ifo.session_release
  - web.ifo.conflicts
  - ifo_conflicts / ifo_session_release URL names
  - ops.tests.ReleaseRoomCallerGuardTests (new source guard)
affects:
  - ops/occupancy.py (docstrings only)
  - ops/tests.py
  - ops/models.py (comment only)
  - templates/ifo/_room_panel.html
  - templates/ifo/_console.html
tech-stack:
  added: []
  patterns:
    - view delegates to a domain service and adds NO audit row of its own
    - server-side re-gate as the control, not the button
    - htmx action targets a small result region, never the polled container
    - source guard pinning a caller set (mirrors SingleWritePathTests)
key-files:
  created:
    - templates/ifo/conflicts.html
    - templates/ifo/_release_result.html
    - web/tests_ifo_ops.py
  modified:
    - ops/occupancy.py
    - ops/tests.py
    - ops/models.py
    - web/ifo.py
    - web/urls.py
    - templates/ifo/_room_panel.html
    - templates/ifo/_console.html
decisions:
  - The MOD-03-only invariant was STRENGTHENED, not weakened - it went from prose to an asserted caller set
  - SCHEDULED counts as room-holding; COMPLETED and ABSENT do not
  - No manual flag-close anywhere; resolution stays entirely with detect_room_conflicts
metrics:
  duration: ~40 min
  tasks: 3
  files: 10
  tests_added: 17
status: complete
---

# Phase 7 Plan 05: IFO-08 Manual Room Release Summary

`ops.occupancy.release_room` has its second and final legitimate caller. IFO can release a room a session is still holding, from the room panel or a new open-conflicts page, and the RoomConflictFlag closes on the next sweep because the cause is fixed.

## What was built

**Task 1 — the invariant amendment (expected, not a regression).** All four documented sites now name IFO-08 as the second caller:

- `ops/occupancy.py` module docstring — rewritten to state the two legitimate callers explicitly, with the sweep prohibition kept intact and the "zero Phase-2 callers" line reframed as a historical note about Phase 2 rather than a standing embargo.
- `ops/occupancy.py` `release_room` docstring — "INVOKED BY EXACTLY TWO CALLERS", with the `actor=None` semantics preserved and a new explicit note that this function is the only writer of the `session.room_released` row.
- `ops/tests.py` module docstring.
- `ops/tests.py` `ReleaseRoomTests` docstring.

`scheduling/tests.py test_sweep_never_stamps_room_released_at` is untouched and still green. The four `ReleaseRoomTests` assertions needed no change.

**Task 2 — the surface.** `web/ifo.py` gained an `IFO-08` section:

- `session_release` — `@require_http_methods(["POST"])`. Re-fetches by pk, re-gates server-side on `room_id`, `room_released_at` and status, then calls `release_room(session, actor=request.user)`. Writes no AuditLog and touches no flag. Renders `ifo/_release_result.html` at 200 or 400.
- `conflicts` — `@require_http_methods(["GET"])`. Open flags with `select_related("room__floor__building")`, paginated, materialized with `list()` before the contending-session query (HY010 guard), then one grouped query for all contending sessions via `_contending_sessions`.

`templates/ifo/conflicts.html` explains in plain words that there is no dismiss button and why. `templates/ifo/_room_panel.html` gained the same Release control, targeting a small `#release-<pk>` region. `templates/ifo/_console.html` gained the nav entry.

**Task 3 — `web/tests_ifo_ops.py`**: `ManualReleaseTests` (7), `ConflictSurfaceTests` (4), `IfoOpsAuthzTests` (4).

## Key decisions

**The caller-set guard is new, and it strengthens the invariant.** The plan described "a paired grep-guard test" asserting `release_room`'s callers. No such test existed — the only paired guard was the *behavioural* `test_sweep_never_stamps_room_released_at`, and the single-caller claim lived purely in three prose docstrings. Prose does not fail a build when someone wires up a fourth caller. `ReleaseRoomCallerGuardTests` now scans the application trees and asserts the call-site set equals exactly `{scheduling/services.py, scheduling/management/commands/materialize_sessions.py, web/ifo.py}`, with a separate explicit assertion that `scheduling/jobs.py` is not among them. Adding IFO-08 therefore converted an unenforced comment into an asserted set.

**SCHEDULED counts as room-holding.** A class nobody has checked into yet is still occupying its room on paper — that is precisely the ghost booking IFO-08 exists to clear. COMPLETED and ABSENT have finished with the room on their own, so releasing them would stamp a release instant for an occupancy that ended elsewhere; both are refused at 400.

**No manual flag-close, verified end to end.** `test_release_then_sweep_auto_resolves_the_flag` builds two ACTIVE sessions on one room, runs `detect_room_conflicts` to open the flag, releases one session, runs the job again, and asserts `resolved_at` is stamped. A companion test asserts the release alone leaves the flag open — together they prove the handoff is the job's, not the view's.

## Deviations from Plan

**1. [Rule 1 - Bug] `%-d` / `%-I` strftime format raised ValueError on Windows**

- **Found during:** Task 3
- **Issue:** The already-released refusal message formatted the release instant with `%b %-d, %-I:%M %p`. The `%-` padding-stripper is a glibc extension; on Windows `strftime` raises `ValueError: Invalid format string`, turning the friendly 400 into a 500 — the exact failure mode T-07-20 exists to prevent.
- **Fix:** Switched to the portable `%b %d, %I:%M %p` with a comment naming the trap.
- **Files modified:** `web/ifo.py`
- **Commit:** d70f29d

**2. [Rule 1 - Bug] `ops/models.py` still asserted the superseded D-19 rationale**

- **Found during:** Task 2
- **Issue:** The `Booking.room` comment ended "Under PROTECT the database itself is the guarantee." The locked D-19 CORRECTION establishes that this is factually wrong — Django never encodes `on_delete` in DDL, every FK to `campus_room` is `NO_ACTION`, and what the migration actually closed is the ORM path. `web/ifo.py room_delete` already carried the corrected wording, so the two files disagreed on a security-relevant claim.
- **Fix:** Replaced the closing sentence with the corrected mechanism, including why it makes `room_delete_blockers` more load-bearing rather than less.
- **Files modified:** `ops/models.py`
- **Commit:** d70f29d

## Files touched outside `files_modified`

- `templates/ifo/_console.html` — nav entry for the conflicts page. The plan's Task 2 text asked for this ("Add the new page to the IFO console navigation in `templates/ifo/_console.html`") but the frontmatter `files_modified` list omitted it.
- `templates/ifo/_release_result.html` — new partial, not named in the plan. The plan required the release POST to target "a small result region"; that region needs a response body, and rendering `conflicts.html` or `_room_panel.html` into it would have defeated the purpose.
- `ops/models.py` — deviation 2 above.

## Plan assumptions that turned out wrong

**"a paired grep-guard test" asserting the caller set.** It did not exist. The plan's Task 1 item 4 described amending `ops/tests.py` docstrings and referred to "the paired guard test it points at in Plan 02-03 SweepTests" — but that guard is behavioural (the sweep must not stamp `room_released_at`), not a caller scan. The single-caller invariant was documentation-only. Written and now asserted; see Key decisions.

**`paginate()` returns `page`, not `page_obj`.** Minor; corrected against `web/pagination.py`.

**`scheduling.tests.make_session` cannot be called twice in one test.** It mints its own Building with code `"R"` per call, which is `unique=True`, so a second call collides. The fixture base calls it once for the FK chain and hangs sibling sessions off the same schedule — which is also the only way to get two sessions contending for *one* room, the shape every test here needs.

## Verification

`DB_TEST_NAME=test_fluxtrack_ifo python manage.py test` — **Ran 612 tests, FAILED (failures=3, skipped=2), 0 errors.** The 3 are the documented pre-existing ones.

`web.tests_ifo_ops` alone: Ran 15 tests, OK. `ops.tests.ReleaseRoomTests scheduling.tests.SweepTests` — green and unchanged.

No files under `static/` were touched, so no `collectstatic` was required.

## Self-Check: PASSED

- `templates/ifo/conflicts.html` — FOUND
- `templates/ifo/_release_result.html` — FOUND
- `web/tests_ifo_ops.py` — FOUND
- commit d70f29d — FOUND
