---
phase: 11-metrics-the-mission-promises
plan: 04
subsystem: reporting
tags: [reporting, aggregates, ghost-rooms, csv-export, csv-injection, django, ifo-utilization, safe-card]

# Dependency graph
requires:
  - phase: 06.1-reporting
    provides: "room_breakdown / RoomLoad (physical-only room universe, unrounded *_seconds fields), _session_contribution single definition of used, safe_card fault isolation, the utilization page + _reporting_range wiring"
  - phase: 11-01
    provides: "reporting.py extended in Wave 1 without collision (lateness helpers/fields)"
  - phase: 11-03
    provides: "reporting.py + web/ifo.py extended in Wave 2 (coverage aggregates + dashboard cards) without collision"
provides:
  - "scheduling/reporting.py::ghost_rooms(*, start, end, term, as_of=None) -> list[RoomLoad] — a PURE reduction of room_breakdown keeping booked_seconds > 0 AND used_seconds == 0 (D-05), keyed on the UNROUNDED seconds"
  - "web/ifo.py::utilization_csv(request) — @ifo_required + GET-only per-room CSV export (D-06 / 06.1-07)"
  - "web/ifo.py::UTILIZATION_CSV_HEADER — a THIRD distinct CSV header contract"
  - "web/urls.py route ifo/utilization.csv name=ifo_utilization_csv"
  - "templates/ifo/utilization.html — 'Booked but never used' ghost section (own safe_card guard) + scoped Export CSV link"
affects: [IFO facilities consumers, any later utilization/capacity work (capacity-fit + trend remain deferred)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ghost-rooms is a PURE reduction of room_breakdown (no re-query), so the list reconciles with the on-screen breakdown table by construction — a room can never appear here that is absent there"
    - "The ghost predicate keys on the UNROUNDED *_seconds fields, NEVER the quantized _hours Decimals: a room with ~40s of use rounds to used_hours 0.0 but used_seconds > 0, and is NOT a ghost (Pitfall 2 / D-05)"
    - "A THIRD distinct CSV header contract (UTILIZATION_CSV_HEADER) beside report_render.HEADER and web.hr.CSV_HEADER — editing one never touches the others (Pitfall 5)"
    - "In-memory CSV (StringIO + HttpResponse) mirroring scorecard_csv, safe because the physical-room universe is bounded (~125); csv_safe on every text cell; server-built filename (no request-derived path)"

key-files:
  created: []
  modified:
    - scheduling/reporting.py
    - scheduling/tests_reporting_rooms.py
    - web/ifo.py
    - web/urls.py
    - templates/ifo/utilization.html
    - web/tests_ifo_utilization.py

key-decisions:
  - "ghost_rooms is implemented as a one-line reduction of room_breakdown rather than a new query, so it inherits the physical-only room universe, the never-used rooms, the virtual-room exclusion, and the ascending-utilization ordering for free — and cannot drift from the table it sits beside"
  - "Predicate is booked_seconds > 0 AND used_seconds == 0 on the UNROUNDED integer-seconds fields; a named rounding-guard test proves a ~40s-use room (used_hours rounds to 0.0) is NOT flagged"
  - "A CANCELLED-only room booked nothing (_session_contribution returns (0,0) for CANCELLED per the Phase-9 A1 fix), so booked_seconds == 0 and it fails the booked>0 half of the predicate — not a ghost, pinned by test"
  - "utilization_csv is in-memory (mirrors scorecard_csv, not the streaming attendance_csv) per the D-06 discretion note — the physical-room universe is bounded, so no server-side cursor / HY010 concern; the view stays side-effect-free"
  - "UTILIZATION_CSV_HEADER columns mirror the on-screen room_breakdown table (Room, Name, Building, Floor, Seats, Sessions, Absent sessions, Used h, Booked h, Available h, Reclaimable h, Utilization %) so the export and the screen can never disagree"
  - "No seat/enrolment field read or added on RoomLoad — capacity-vs-enrolment fit stays a T3 deferral (reporting.py:947); week-over-week trend also untouched (CONTEXT <deferred>)"

patterns-established:
  - "Pattern: a fifth independent safe_card owner (ghosts) added to the utilization page alongside grid/rollup/breakdown/saturation, each guarding its OWN .1 error + reports/_error_card.html — a raising ghost_rooms renders one error card and the four sections around it still stand (D-05 per-section isolation)"
  - "Pattern: a per-room CSV export as a THIRD header contract, csv_safe-neutralized text cells + server-built filename, reusing the in-memory scorecard_csv idiom rather than re-implementing streaming"

requirements-completed: [A8, IFO-09]

coverage:
  - id: D1
    description: "ghost_rooms returns exactly the physical rooms with booked_seconds > 0 AND used_seconds == 0 over the range, a strict reduction of room_breakdown (D-05)"
    requirement: A8
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_rooms.py#GhostRoomsTests.test_ghost_room_booked_never_used_listed"
        status: pass
    human_judgment: false
  - id: D2
    description: "The ghost predicate keys on the UNROUNDED used_seconds, not the rounded used_hours: a ~40s-use room (rounds to 0.0 h) is NOT flagged"
    requirement: A8
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_rooms.py#GhostRoomsTests.test_ghost_rounding_guard_tiny_use_not_flagged"
        status: pass
    human_judgment: false
  - id: D3
    description: "A CANCELLED-only room (0 booked) is not a ghost; a fully-used room is not a ghost"
    requirement: A8
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_rooms.py#GhostRoomsTests (test_cancelled_room_not_ghost / test_used_room_not_ghost)"
        status: pass
    human_judgment: false
  - id: D4
    description: "utilization_csv emits one row per physical room from room_breakdown (row count == physical rooms), scoped to the same range/term as the on-screen table"
    requirement: IFO-09
    verification:
      - kind: integration
        ref: "web/tests_ifo_utilization.py#UtilizationCsvTests.test_utilization_csv_row_per_physical_room"
        status: pass
    human_judgment: false
  - id: D5
    description: "Text cells (room code/name/building) in the per-room CSV are csv_safe-neutralized so a formula-triggering room name cannot become a live spreadsheet formula (T-11-10)"
    requirement: IFO-09
    verification:
      - kind: integration
        ref: "web/tests_ifo_utilization.py#UtilizationCsvTests.test_utilization_csv_formula_neutralized"
        status: pass
    human_judgment: false
  - id: D6
    description: "utilization_csv is @ifo_required and GET-only (non-IFO -> 403, POST -> 405) with a server-built filename (T-11-11/T-11-12)"
    requirement: IFO-09
    verification:
      - kind: integration
        ref: "web/tests_ifo_utilization.py#UtilizationCsvAccessTests (test_utilization_csv_gate / test_utilization_csv_post_405) + UtilizationCsvTests.test_the_filename_is_server_built_not_request_derived"
        status: pass
    human_judgment: false
  - id: D7
    description: "The ghost-room section renders on the IFO utilization page inside its own safe_card so a raising ghost_rooms errors in its own card and the page still returns 200 (T-11-13)"
    requirement: IFO-09
    verification:
      - kind: integration
        ref: "web/tests_ifo_utilization.py#GhostCardIsolationTests.test_ghost_card_isolation"
        status: pass
    human_judgment: false
  - id: D8
    description: "Human-verify the three Phase-11 metric surfaces render and export correctly in the browser (coverage cards, ghost list + CSV, scorecard lateness) — Task 3 checkpoint"
    verification:
      - kind: manual_procedural
        ref: "11-04-PLAN.md Task 3 how-to-verify (dev server, IFO login, /ifo/dashboard + /ifo/utilization + /ifo/scorecard/<id>, Export CSV opened in a spreadsheet)"
        status: unknown
    human_judgment: true
    rationale: "Visual/functional confirmation of the rendered surfaces and the exported CSV opening safely in a real spreadsheet cannot be automated; auto-mode recorded it as a Manual-Verification item and continued (yolo)."

# Metrics
duration: 20min
completed: 2026-07-20
status: complete
---

# Phase 11 Plan 04: Ghost-Room List + Per-Room Utilization CSV Summary

**A booked-but-never-used ghost-room list (`ghost_rooms`, a pure reduction of `room_breakdown` keyed on the UNROUNDED `used_seconds == 0 AND booked_seconds > 0`, so a ~40s-use room that rounds to 0.0 h is never falsely flagged) plus a per-room utilization CSV export (`utilization_csv`, `@ifo_required` GET-only, `csv_safe` text cells, server-built filename, its own THIRD header contract) — both surfaced on the IFO utilization page and scoped to the applied window, finishing the deliberately-dropped 06.1-07 (A8 partial / IFO-09 / D-05/D-06).**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-20T09:25Z
- **Completed:** 2026-07-20T09:45Z
- **Tasks:** 3 (Task 3 is a human-verify checkpoint, recorded as a Manual-Verification item under auto-mode)
- **Files modified:** 6

## Accomplishments
- **`ghost_rooms` (Task 1):** a one-line reduction of `room_breakdown` — `[r for r in room_breakdown(...) if r.booked_seconds > 0 and r.used_seconds == 0]`. No re-query, so it inherits the whole physical room universe, the virtual-room exclusion, and the ascending-utilization order, and stays reconciled with the on-screen breakdown by construction. Predicate keys on the UNROUNDED integer-seconds fields, never the quantized `_hours` Decimals (D-05 / Pitfall 2). Docstringed against reading or adding any seat/enrolment field (T3 deferral held).
- **Ghost tests (Task 1):** `GhostRoomsTests` — the ABSENT room is listed; a fully-used room is not; a `~40s`-use room that rounds to `used_hours 0.0` is proven NOT flagged (the binding rounding guard, keyed on `used_seconds > 0`); a CANCELLED-only room (0 booked) is not a ghost. One assertion per rule.
- **`utilization_csv` + `UTILIZATION_CSV_HEADER` (Task 2):** an `@ifo_required` + `@require_http_methods(["GET"])` view mirroring `scorecard_csv` — `_reporting_range` unpacked first, active term resolved inline, one row per physical room from the SAME `room_breakdown` aggregate the page renders, in-memory `csv.writer(io.StringIO())` -> `HttpResponse`. Every text cell (`code`, `name`, `building_name`) runs through `csv_safe` (T-11-10); numeric cells pass through. Server-built `utilization-{start}.csv` filename, never request-derived (T-11-11). A THIRD distinct header contract, separate from `report_render.HEADER` and `web.hr.CSV_HEADER` (Pitfall 5).
- **Utilization page surfaces (Task 2):** `ghosts = safe_card(ghost_rooms, **scope)` added as a fifth independent error owner; a "Booked but never used" section renders under its own `ghosts.1` guard + `reports/_error_card.html`, with a calm empty state ("No rooms were booked and left completely unused in this window."). A scoped "Export CSV" link in the least-used-rooms header carries the applied `from`/`to` window. Route `ifo/utilization.csv` -> `ifo_utilization_csv`.
- **Web tests (Task 2):** CSV row-count == physical rooms (virtual excluded), formula-name neutralization (leading-quote), range/term scope, server-built filename, distinct-header contract, `403` for a non-IFO user, `405` for a POST; ghost section render + scope; and a ghost-card isolation test (patched `ghost_rooms` raises -> its error card renders, the four other sections stand, page still 200).

## Task Commits

Each task was committed atomically:

1. **Task 1: ghost_rooms reduction + rounding-guard tests** - `701a069` (feat)
2. **Task 2: utilization_csv view + route + ghost/CSV surfaces on the utilization page** - `bb051d2` (feat)
3. **Task 3: human-verify checkpoint** - not a code commit; recorded as Manual-Verification item D8 (auto-mode, yolo).

**Plan metadata:** committed separately with STATE.md/ROADMAP.md updates (docs: complete plan).

## Files Created/Modified
- `scheduling/reporting.py` - Added `ghost_rooms(*, start, end, term, as_of=None)` beside `room_breakdown`.
- `scheduling/tests_reporting_rooms.py` - Imported `ghost_rooms`; added `GhostRoomsTests` (4 tests, one per D-05 rule incl. the rounding guard).
- `web/ifo.py` - `import csv`; extended the `report_render` import with `csv_safe` and the `reporting` import with `ghost_rooms`; added `UTILIZATION_CSV_HEADER` + `utilization_csv`; wired `ghosts` into the `utilization` view + context.
- `web/urls.py` - Added `ifo/utilization.csv` -> `ifo_utilization_csv`.
- `templates/ifo/utilization.html` - Added the ghost-room section (own `ghosts.1` safe_card guard + empty state) and a scoped Export CSV link in the least-used-rooms header.
- `web/tests_ifo_utilization.py` - Imported `csv`/`io`/`Room`/`UTILIZATION_CSV_HEADER`; added `GhostRoomSectionTests`, `GhostCardIsolationTests`, `UtilizationCsvTests`, `UtilizationCsvAccessTests`.

## Decisions Made
- Implemented `ghost_rooms` as a pure reduction rather than a query so it cannot drift from the on-screen breakdown table (reconciliation by construction), exactly as the plan and PATTERNS Pattern 4 direct.
- Chose the in-memory CSV idiom (`scorecard_csv`) over the streaming one (`attendance_csv`) per the D-06 discretion note — the ~125-room universe is bounded, so there is no server-side-cursor / HY010 concern and the view stays side-effect-free.
- Placed the ghost section as section "3b", directly under the least-used-rooms table it complements, with its own `data-util-section="ghosts"` marker (the existing four-section markers are untouched, so no existing test breaks).
- Everything else followed the plan, CONTEXT D-05/D-06, and the named `must_haves` verbatim.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Both task modules were green on first run (4 ghost tests; 56 web utilization tests). The `RuntimeError: aggregate exploded` line in the web test output is the intentional ghost-card isolation side effect (captured by `assertLogs` and asserted against), not a failure.

## Verification
- `scheduling.tests_reporting_rooms` (99, incl. 4 new ghost tests) + `scheduling.tests_reporting` + `web.tests_ifo_utilization` (56, incl. the new CSV/ghost tests) + `web.tests_ifo_coverage` — **191 tests, all green** under the Python312 Django runner.
- Ghost predicate keys on the UNROUNDED `used_seconds`; the per-room CSV is `csv_safe`-neutralized, GET-only, IFO-only, server-built filename; the header is a distinct third contract.
- No seat/enrolment field read or added on `RoomLoad`; nothing from CONTEXT `<deferred>` (capacity-fit / week-over-week trend) was touched.
- Targeted module runs only (never the full suite), so `FluxTrack_SRS.docx` was NOT regenerated — confirmed untouched in `git status` (MEMORY guard honored).

## Manual Verification (Task 3 checkpoint — recorded, not blocked under auto/yolo)
Human should confirm in the browser (dev server, IFO admin dev-login):
1. `/ifo/dashboard` — verification-coverage section renders (verified/held by building x weekday) and any floor with held sessions but no verification is listed explicitly.
2. `/ifo/utilization` — the "Booked but never used" ghost section renders; click "Export CSV", open `utilization-*.csv` in a spreadsheet: one row per physical room, columns match the on-screen table, no cell is interpreted as a formula.
3. `/ifo/scorecard/<id>` for a faculty with late sessions — the avg-minutes-late figure shows and the chronic pill appears only at >= 5 held sessions in range.
4. Change the From/To window and Apply — the coverage grid, ghost list, and CSV all rescope to the new range.

## User Setup Required
None - no external service configuration required. No schema change, no migration.

## Next Phase Readiness
- Phase 11 (Metrics the Mission Promises) is now complete (4/4 plans): lateness (A3, 11-01/02), verification coverage (A6, 11-03), and utilization depth — ghost-room list + per-room CSV (A8 partial / IFO-09, this plan). 06.1-07's deferred CSV export is shipped.
- Deferred and untouched by design: capacity-vs-enrolment "fit" (T3, reporting.py:947) and week-over-week utilization trend — candidates for a later follow-up once `enrolled_count` is validated on a real imported term.

## Self-Check: PASSED

All modified files exist on disk; both task commits (`701a069`, `bb051d2`) present in git history.

---
*Phase: 11-metrics-the-mission-promises*
*Completed: 2026-07-20*
