---
phase: 07-remaining-operational-surfaces
plan: 01
subsystem: web
tags: [guard, grd-05, read-only, refactor, shared-module]
requires: []
provides:
  - web.room_state.room_tile
  - web.room_state.occupies
  - web.room_state.ROOM_STATE_ORDER
  - web.room_state.ROOM_PROBLEM_STATES
  - GuardReadOnlyTests.GUARD_URLS
affects:
  - web/ifo.py
  - web/guard.py
  - web/urls.py
tech-stack:
  added: []
  patterns:
    - "role-neutral derivation module shared by two role modules (web/room_state.py)"
    - "@require_http_methods(['GET']) under the role gate — house decorator order"
key-files:
  created:
    - web/room_state.py
  modified:
    - web/ifo.py
    - web/guard.py
    - web/urls.py
    - web/tests.py
    - web/tests_ifo_board.py
    - docs/USE_CASES.md
decisions:
  - "Test-module import repointed via alias (`from web.room_state import room_tile as _room_tile`) so the 13 existing tile assertions stay byte-identical and the move is provably behaviour-neutral."
  - "GRD-05 RED was verified by temporarily removing one decorator rather than by ordering the test before the fix, because the plan sequenced enforcement (Task 2) ahead of the test (Task 3)."
metrics:
  duration: ~25m
  completed: 2026-07-19
status: complete
---

# Phase 07 Plan 01: GRD-05 Enforcement + Shared Room-State Module Summary

GRD-05 is now a contract rather than an absence — all three Guard views refuse POST with 405 — and the five-state room-tile derivation lives in a role-neutral `web/room_state.py` that both IFO and the coming Guard per-room schedule can consume without crossing a private module boundary.

## What Was Built

**Task 1 — `web/room_state.py` (commit `37e61cf`).** `ROOM_STATE_ORDER`, `ROOM_PROBLEM_STATES`, `occupies()` and `room_tile()` moved verbatim out of `web/ifo.py`, dropping their leading underscores because they are now a cross-module contract. Both docstrings and every inline comment carried over intact — specifically the online-occupancy rationale (an ONLINE class does not occupy a physical room; virtual rooms invert that) and the past-grace rule (the board must call a no-show before the sweep job stamps it). The module docstring states that it is consumed by both `web/ifo.py` (IFO-07/IFO-11) and `web/guard.py` (GRD-01/GRD-02) and that it carries no role gating of its own.

`web/ifo.py` now imports all four and defines none. All five call sites rewired: `_room_board` (1), `room_panel` (2), `room_detail` (1) — plus the sort/filter references to the two constants. `SessionStatus` was dropped from the `web/ifo.py` imports since the tile derivation was its only consumer there; `Modality` stays (still used at four other sites).

**Task 2 — GRD-05 + label fix (commit `6e863b0`).** `@require_http_methods(["GET"])` added to `monitor`, `monitor_rows` and `locate`, placed directly under `@guard_required` per the house order at `web/hr.py:178` / `web/ifo.py:477`. The locator relabelled GRD-02 → GRD-03 in both the module docstring and the view docstring; the module docstring now names GRD-05 as enforced rather than merely observed. `web/urls.py` Guard block renamed to GRD-01/GRD-03/GRD-05 with an explicit note reserving GRD-02 for plan 07-09. No view body, query, template or URL path touched.

**Task 3 — `GuardReadOnlyTests` (commit `6dceafd`).** Three tests over a `GUARD_URLS` tuple: POST → 405 on all three, GET → 200 on all three, and non-Guard GET → 403 (proving the role gate stays outermost and the method decorator does not shadow it). Independent fixture, not shared with `GuardSurfaceTests`. Class docstring instructs that any future Guard view joins `GUARD_URLS`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `web/tests_ifo_board.py` imported the moved private**

- **Found during:** Task 1
- **Issue:** `from web.ifo import _room_board, _room_tile, _room_timetable` — the move broke this import, so the plan's own Task 1 verification command could not run. The file was not listed in `files_modified`.
- **Fix:** Split the import: `_room_board`/`_room_timetable` still from `web.ifo`, and `from web.room_state import room_tile as _room_tile`. The alias is deliberate — it keeps all 13 existing `_room_tile(...)` assertions byte-identical, so those tests remain a clean before/after proof that the move changed no behaviour. Module docstring updated to name the new home and note that these tests now guard both roles.
- **Files modified:** `web/tests_ifo_board.py`
- **Commit:** `37e61cf`

**2. [Rule 1 - Bug] Stale code pointer in `docs/USE_CASES.md`**

- **Found during:** Task 1
- **Issue:** `docs/USE_CASES.md:270` pointed at `web/ifo.py:_room_tile`, which no longer exists after the move.
- **Fix:** Repointed to `web/room_state.py:room_tile` and noted it is shared with the Guard surfaces.
- **Files modified:** `docs/USE_CASES.md`
- **Commit:** `37e61cf`

### TDD Gate Compliance

Task 3 was marked `tdd="true"`, but the plan sequenced GRD-05 enforcement (Task 2) *before* the test (Task 3), so a literal RED-first commit was not reachable — the decorator already existed when the test was written. Rather than skip the gate, RED was verified empirically: the decorator was temporarily removed from `monitor`, `test_post_is_refused_on_every_guard_url` failed with `AssertionError: 200 != 405`, and the decorator was restored (confirmed by a clean `git diff` on `web/guard.py`). The test is therefore proven to test the thing it claims to. Commit sequence is `refactor` → `feat` → `test` rather than `test` → `feat`.

## Verification

Full suite, `manage.py test`:

```
Ran 527 tests in 113.222s
FAILED (failures=3, skipped=2)
```

The 3 failures are exactly the documented pre-existing set (`DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`, `DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`, `HomeSurfaceNavTests.test_faculty_home_links_modality_request`). **0 errors. No new failures.** Count is above the 515 baseline because this plan adds 3 tests and plan 07-02 was landing tests in parallel on the same tree.

Targeted runs: `web.tests_ifo_board` 28/28 OK (the extraction is behaviour-neutral); `web.tests.GuardSurfaceTests` 4/4 OK unchanged; `web.tests.GuardReadOnlyTests` 3/3 OK.

No `static/` file was created or edited, so `collectstatic` was not required.

Manual verification steps 3 and 4 in the plan (browser check of `/guard/monitor`, `/guard/locate`, `/ifo/rooms`) were **not** performed — see Deferred Issues.

## Deferred Issues

- **Manual browser verification not run.** The plan's verification steps 3–4 ask for a `runserver` pass as demo guard and as IFO. Plan 07-02 was executing in parallel against the same working tree, and the test database was already contended (one full-suite attempt aborted on a locked test DB). Starting a dev server against the shared tree mid-parallel-wave risked interfering with the sibling agent. The automated coverage is strong here — the extraction is a pure move proven by 28 unchanged assertions, and the decorator change is proven RED-and-GREEN — but the two visual confirmations remain open and should be folded into the phase's UAT pass.
- **Guard/IFO poll-source inconsistency (PATTERNS.md §4.1).** `web/guard.py:_poll_ms()` reads `settings.FLUXTRACK_POLICY` directly while `web/ifo.py` goes through `get_policy(...)`. Flagged by the pattern map, out of scope for this plan, untouched.

## Threat Flags

None. No new network endpoint, auth path, file access or schema change was introduced; T-07-01 and T-07-02 are both mitigated as planned, and T-07-03 was accepted with no query change.

## Known Stubs

None.

## Self-Check: PASSED

- `web/room_state.py` — FOUND
- `.planning/phases/07-remaining-operational-surfaces/07-01-SUMMARY.md` — FOUND
- commit `37e61cf` — FOUND
- commit `6e863b0` — FOUND
- commit `6dceafd` — FOUND
