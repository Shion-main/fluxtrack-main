---
phase: 03-duty-assignments-checker-verification
plan: 04
subsystem: verification
tags: [checker, floor-board, htmx-poll, coverage, priority-queue, franken-ui, chk-07]
requires:
  - web.checker._active_floor_ids (03-02 — on-duty floor pks)
  - web.checker.checker_required (03-02 — Role.CHECKER guard)
  - scheduling.models.Session.verified_by_checker (derived flag)
  - settings.FLUXTRACK_POLICY[poll_interval_seconds] (policy poll interval)
provides:
  - web.checker.floor_board (CHK-07 board shell view)
  - web.checker.floor_rows (CHK-07 polled partial — cards + queue + coverage)
  - templates/checker/floor.html + _floor_rows.html (UI-SPEC-conformant)
  - /checker/floor + /checker/floor/rows routes
affects:
  - 03-05 (online surface is separate from this F2F/Blended board)
tech-stack:
  added: []
  patterns: [htmx-polled-partial, single-shared-queryset, server-computed-state-token]
key-files:
  created:
    - templates/checker/floor.html
    - templates/checker/_floor_rows.html
  modified:
    - verification/tests.py
    - web/checker.py
    - web/urls.py
    - web/views.py
decisions:
  - One materialized board list (exclude ABSENT, active-floor scoped, effective-online dropped in Python so declared-modality overrides schedule) feeds cards, the priority queue, and the coverage denominator — the three can never disagree (Pitfall 5).
  - Card display state is computed server-side with flagged winning over verified for the card face; coverage counting stays independent (any 'verified' validation counts, matching Session.verified_by_checker).
  - Cards and queue rows link to /checker/scan (the existing scan surface); there is no per-room GET view in this phase.
metrics:
  duration: ~9m
  completed: 2026-07-03
  tasks: 2
  files: 5
status: complete
---

# Phase 3 Plan 04: Checker Floor Board (CHK-07) Summary

Built the CHK-07 Checker floor board — a mobile-first, htmx-polled surface that mirrors the shipped IFO live view. It shows the checker's active-floor F2F/Blended rooms as color-coded cards (state = Lucide icon + text label + color, never color alone), an oldest-unverified-first priority queue, and a coverage % that excludes Absent and reads 100% when the floor is fully verified. A single materialized queryset feeds the cards, the queue, and the coverage denominator, so the numbers stay consistent.

## What Was Built

### Task 1 — FloorBoardTests (TDD RED)
`verification/tests.py` gains `FloorBoardTests(_CheckerFixtureMixin, TestCase)`, driving the yet-to-exist `/checker/floor/rows` route through the test Client and asserting on rendered context:
- `test_coverage_excludes_absent` — 2 verified + 1 unverified active + 1 ABSENT → `total=3` (Absent out of the denominator), `verified=2`, `coverage=67`, and the Absent room is never carded; verifying the last active session brings `coverage` to 100.
- `test_priority_queue_oldest_first` — three active-unverified sessions return in `scheduled_start` ascending order (longest-waiting on top).
- `test_board_excludes_online` — an ONLINE session on a floor room does not appear on the F2F/Blended board.
- `test_board_scoped_to_active_floor` — a session on a floor the checker is not assigned to does not appear.
Confirmed RED before Task 2 (404 on the unwired route + missing `queue`/`total` context keys).

### Task 2 — floor_board + floor_rows views + board templates (GREEN)
`web/checker.py` gains two `checker_required` views:
- `floor_board` mirrors `ifo.live`, passing `poll_ms = settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000` — the interval is policy-driven, never hardcoded (Convention rule #3, T-03-14).
- `floor_rows` builds ONE shared list: `Session.filter(room__floor_id__in=_active_floor_ids(...), date=today).exclude(status=ABSENT)`, then drops effective-online sessions in Python (declared modality overrides schedule). From that single list it computes `total`, `verified`, `coverage = round(100*verified/total) if total else 100`, the priority queue (active + unverified, already oldest-first), and a per-card display-state token via `_card_state` + the `_CARD_STYLES` palette table.

`templates/checker/floor.html` (shell, sibling of `ifo/live.html`) polls a `#floor-rows` container with `hx-trigger="load, every {{ poll_ms }}ms"`; `templates/checker/_floor_rows.html` renders the coverage indicator, the priority queue, and the color-coded card grid per the approved 03-UI-SPEC (Franken UI `uk-*` classes, `border-l-4` status rail, each state carrying icon + label + color). Routes `/checker/floor` + `/checker/floor/rows` wired in `web/urls.py`; the home `SURFACES[Role.CHECKER]` "Floor view" card now points at `/checker/floor`.

## Deviations from Plan

None — plan executed exactly as written. Both tasks landed on their planned files; no auto-fix (Rule 1-3) or architectural (Rule 4) deviations were needed. RED manifested via 404 routing (the same Client-driven approach 03-02 established, kept consistent here) rather than an ImportError.

## Verification Results

- `py -3.12 manage.py test verification.tests.FloorBoardTests` — 4 tests, OK (coverage excludes Absent; queue oldest-first; online + off-floor excluded; fully-verified reads 100).
- `py -3.12 manage.py test verification scheduling web` — 68 tests, OK (no regression to the Checker scan, faculty scan, sweep, or IFO surfaces).
- Task-2 grep gates: `poll_interval_seconds` present in `web/checker.py`; no literal `every Nms` in `templates/checker/floor.html`; `exclude(status=SessionStatus.ABSENT)` present in `floor_rows`; `checker_floor` + `checker_floor_rows` routes wired; home "Floor view" href == `/checker/floor`.

## Threat Mitigations Applied

- **T-03-12 (Info disclosure, cross-floor leak):** `floor_rows` scopes strictly to `_active_floor_ids(request.user, now)` server-side; the checker never selects the floor from the client. Verified by `test_board_scoped_to_active_floor`.
- **T-03-13 (EoP, non-checker viewing the board):** `checker_required` guards both `floor_board` and `floor_rows` (superuser bypass only).
- **T-03-14 (DoS, poll storm):** the poll interval is sourced from `settings.FLUXTRACK_POLICY[poll_interval_seconds]` (single tunable), matching the shipped IFO live surface; no per-request tightening is possible from the client.

## Known Stubs

None. The board renders live data from the shared queryset; cards and queue rows link to the existing `/checker/scan` surface (a real target, not a placeholder). Exact card colors were specified by the approved 03-UI-SPEC and are implemented; the deferred `/gsd-ui-phase 3` manual checks are visual/responsive judgment only (card hue contrast, one-handed layout), not missing functionality.

## Notes for Downstream Plans

- **03-05 (online):** the online-to-verify list is a separate surface (per 03-UI-SPEC #9); this board is F2F/Blended only and already drops effective-online sessions, so no rework is needed there.
- Reuse `_CARD_STYLES` / `_card_state` if any other checker surface needs the same functional-state palette.

## Self-Check: PASSED
- FOUND: templates/checker/floor.html
- FOUND: templates/checker/_floor_rows.html
- FOUND: web/checker.py (floor_board, floor_rows)
- FOUND: web/urls.py (/checker/floor + /checker/floor/rows)
- FOUND: web/views.py ("Floor view" -> /checker/floor)
- FOUND commit: 5ca1a00 (test RED), 322ebd0 (feat board)
