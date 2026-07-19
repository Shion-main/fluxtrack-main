---
phase: 07-remaining-operational-surfaces
plan: 11
subsystem: guard-surfaces
tags: [GRD-02, guard, room-state, authorization, read-only]
requires:
  - web/room_state.py (07-01)
  - web/guard.py _guard_floor_ids (Phase 6)
  - verification.resolver.assignment_covers_now
provides:
  - web.room_state.room_timetable (public, shared by IFO + Guard)
  - guard_room URL + web.guard.room_detail
  - templates/guard/room.html
affects:
  - web/ifo.py (room_detail now calls the shared timetable helper)
  - web/tests_ifo_board.py (import moved)
tech-stack:
  added: []
  patterns:
    - server-computed card/pill/icon/label token dict (mirrors web/checker._CARD_STYLES)
    - 404-not-403 for out-of-scope resources (mirrors web/checker.online_open)
key-files:
  created:
    - templates/guard/room.html
  modified:
    - web/room_state.py
    - web/ifo.py
    - web/guard.py
    - web/urls.py
    - web/tests.py
    - web/tests_ifo_board.py
    - templates/guard/_monitor_rows.html
    - templates/base.html
    - static/faculty/faculty.css
    - static/css/timetable.css
decisions:
  - "Guard room page 404s (not 403s) for an off-floor or off-shift room, so the response never confirms the room code exists."
  - "_poll_ms now reads get_policy('poll_interval_seconds') instead of settings.FLUXTRACK_POLICY - a SystemSetting override now reaches the Guard monitor. Observable behaviour change for anyone who set one."
metrics:
  duration: ~35m
  tasks: 3
  completed: 2026-07-19
status: complete
---

# Phase 07 Plan 11: Guard per-room schedule (GRD-02) Summary

A Guard can open any room on a floor they are posted to right now and see that
room's live state, today's timeline and its weekly timetable — derived from the
same `web/room_state.py` code the IFO board uses, with floor authorization
re-derived server-side on every request.

## What shipped

**Task 1 — shared helper + two corrections (`9166eb7`)**
- `_room_timetable` moved out of `web/ifo.py` into `web/room_state.py` as public
  `room_timetable(room, term)`, docstring intact. `web/ifo.room_detail` and
  `web/tests_ifo_board.py` now import it from there. Pure move.
- `_guard_floor_ids` reads `a.floors.all()` (the prefetch cache) instead of
  `a.floors.values_list(...)`, which bypassed the prefetch and re-queried once
  per assignment.
- `_poll_ms` reads `get_policy("poll_interval_seconds")`. **Behaviour change:**
  a `SystemSetting` poll-interval override previously did not affect the Guard
  monitor; now it does.

**Task 2 — the view and page (`9e6c92e`)**
- `web.guard.room_detail`, `@guard_required` outermost, `@require_http_methods(["GET"])`
  inner. Fetches the room by code, then re-derives the guard's active floors via
  `_guard_floor_ids(request.user, timezone.now())`; a room whose `floor_id` is not
  in that set raises `Http404`. No fourth copy of the on-duty predicate.
- Content from `web/room_state.py`: `room_tile` for the five states (including
  the past-grace no-show), `occupies` to filter today's list, `room_timetable`
  for the week. Each queryset materialized with `list()` before the next (MARS off).
- `_ROOM_CARD_STYLES` maps each state to card/pill/icon/label server-side; the
  template never branches on colour, and every state carries an icon and text.
- `templates/guard/room.html`: navy `.ft-*` shell, `.ft-appbar` back link to the
  monitor, `.ft-card--*` state card, `.ft-list`/`.ft-row` timeline, and the
  weekly grid reusing `static/css/timetable.css` with the IFO room page's markup.
- `templates/guard/_monitor_rows.html`: each room card is now a plain `<a>` to
  the room page — a navigation link, deliberately not an htmx swap, since the
  partial is re-swapped on every poll.
- URL `guard/rooms/<str:code>` name `guard_room`; the Guard block comment no
  longer reserves GRD-02.

**Task 3 — tests (`3992394`)**
`GuardRoomScheduleTests` covers all ten behaviours in the plan. `guard_room`
joins `GuardReadOnlyTests.GUARD_URLS`, which now carries reverse args.

## Deviations from Plan

**1. [Rule 3 — Blocking] `web/tests_ifo_board.py` imported `_room_timetable` from `web/ifo`**
- Found during: Task 1. Not listed in `files_modified`.
- Fix: import switched to `from web.room_state import room_timetable as _room_timetable`,
  keeping the existing local alias so no test body changed.
- Commit: `9166eb7`

**2. [Rule 1 — Bug] `templates/base.html` navy-shell exclusion list**
- Found during: Task 2. Not listed in `files_modified`.
- Issue: `base.html` renders the Franken standard header for any URL name not in
  its exclusion list. `guard_room` was absent, so the page rendered the admin
  header stacked on top of its own `.ft-appbar` — two headers, and a Franken
  `uk-*` shell on a Guard surface, violating the UI contract.
- Fix: added `or un == "guard_room"` to that one condition (a single token; the
  sibling sub-flow `checker_online_open` is handled the same way).
- Commit: `9e6c92e`

**3. [Docs] `static/css/timetable.css` header comment** pointed at
`web.ifo._room_timetable` and said "Loaded by ifo/room_detail.html". Both are now
false; updated. Commit `9e6c92e`.

## Contended files — exact appended blocks

`static/faculty/faculty.css` — one contiguous append at EOF, no existing line touched:

```
/* --- Guard room detail (GRD-02) --------------------------------------------
   ... rationale comment ...
   -------------------------------------------------------------------------- */
.gd-roomlink { display: block; text-decoration: none; color: inherit; }
.gd-roomlink:hover { border-color: var(--nv-hero); }
.gd-roomlink:focus-visible { ... }
.gd-roomlink__go { margin-left: auto; display: inline-flex; align-items: center; }
.gd-roomlink__go uk-icon, .gd-roomlink__go svg { ... }
.gd-roomlink .ft-card__meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.gd-room__grid { margin-top: 2px; }
.gd-room__note { margin-top: 10px; font-size: .8rem; color: var(--ft-muted); }
/* --- end Guard room detail (GRD-02) --------------------------------------- */
```

`web/urls.py` — one delimited block inside the existing Guard section:

```python
    # --- Guard room detail (GRD-02) ---
    # Keyed by room code like every other room route. Floor authorization is
    # re-derived server-side per request; an off-floor code 404s.
    path("guard/rooms/<str:code>", guard.room_detail, name="guard_room"),
    # --- end Guard room detail (GRD-02) ---
```

The pre-existing `# GRD-02 ... lands in 07-09` comment two lines above was also
edited (it is now stale) — a one-line change inside the same Guard block.

## Threat mitigations applied

| Threat | Mitigation | Test |
|---|---|---|
| T-07-58 | Floor set re-derived per request; off-floor room `Http404` | `test_room_on_other_floor_is_404_and_not_named` |
| T-07-59 | 404 not 403; room code absent from the body | same test, `assertNotContains(..., status_code=404)` |
| T-07-60 | `@require_http_methods(["GET"])`; URL in `GuardReadOnlyTests` | `test_post_is_refused`, `test_post_is_refused_on_every_guard_url` |
| T-07-61 | Page shows room state + current class only; no absence or flag history | reviewed; no flag / status-history rendering on `guard/room.html` |
| T-07-62 | `assignment_covers_now` reached only through `_guard_floor_ids` | `test_shift_not_covering_now_is_404`, `test_standing_posting_is_always_on_duty` |

## Verification

`py -3.12 manage.py check` — no issues.
`py -3.12 manage.py collectstatic --noinput` — 170 files (run unconditionally, as the plan requires).

Full suite: **Ran 746 tests, failures=3, errors=0, skipped=26.**
The three failures are exactly the known pre-existing set:
`DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`,
`DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`,
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`.
Skips are elevated versus the main tree because gitignored fixtures
(`data/raw/`, `keys/`, `media/`) are absent from the worktree.

Manual steps 2–6 in the plan's verification section (runserver, post the demo
guard via `/ifo/assignments`, click through) were **not** performed — no browser
session was driven in this worktree. Every one of those steps has an equivalent
automated assertion in `GuardRoomScheduleTests`.

## Known Stubs

None.

## Self-Check: PASSED

- `templates/guard/room.html` — FOUND
- commits `9166eb7`, `9e6c92e`, `3992394` — FOUND in `git log`

## Note on STATE.md / ROADMAP.md

Not updated by this agent. This plan ran in an isolated worktree concurrently
with plan 07-08 in the main tree; both writing `.planning/STATE.md` would
guarantee a merge conflict on files neither agent owns. The orchestrator should
apply the plan-counter, progress, metric and `GRD-02` requirement updates after
the wave merges.
