---
phase: 11-metrics-the-mission-promises
plan: 03
subsystem: reporting
tags: [reporting, aggregates, verification-coverage, django, mssql-django, ifo-dashboard, safe-card]

# Dependency graph
requires:
  - phase: 06-reporting
    provides: scheduling/reporting.py aggregate layer (_verified_map separate-query discipline, _exclude_virtual, _scoped_sessions, _pct, safe_card, dashboard safe_card wiring)
  - phase: 11-01
    provides: reporting.py extended in Wave 1 without collision (lateness helpers/fields)
provides:
  - "coverage_by_building_day(*, start, end, as_of=None) -> list[CoverageRow] — verified/HELD by (building, weekday), physical-only"
  - "zero_coverage_floors(*, start, end, as_of=None) -> list[ZeroCoverageFloor] — held>0 AND verified==0 floors listed explicitly"
  - "CoverageRow / ZeroCoverageFloor dataclasses"
  - "web/ifo.py::_coverage_card (weekday-label resolution inside safe_card) + dashboard coverage/zero_floors context tuples"
  - "templates/ifo/_coverage.html (verified/held table + explicit zero-floor list, per-section .1 error guards)"
  - "scheduling/test_support.py::make_coverage_fixture"
affects: [11-04 (ghost-room list + per-room CSV reuse the same aggregate/surface patterns), IFO management consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Coverage = verified/HELD, HELD denominator never scheduled (D-04), consistent with every other reporting.py rate"
    - "Verified count is a SEPARATE distinct-count query keyed on (building, weekday) / (building, floor) — never a same-query multi-join with the held count, so a reverse-join can never inflate coverage"
    - "Physical-only via _exclude_virtual (Room.is_virtual is a property, unusable in filter()); an online V-room session with a verified validation is invisible to the physical rate"
    - "Weekday label resolved in the view (_coverage_card) inside the safe_card unit, mirroring _saturation_card — the aggregate layer stays display-free (returns a DayOfWeek int)"

key-files:
  created:
    - scheduling/tests_reporting_coverage.py
    - web/tests_ifo_coverage.py
    - templates/ifo/_coverage.html
  modified:
    - scheduling/reporting.py
    - scheduling/test_support.py
    - web/ifo.py
    - templates/ifo/dashboard.html

key-decisions:
  - "MERGED siblings are NOT special-cased: a MERGED held session has no CheckerValidation, so it counts in the HELD denominator and lowers coverage honestly (never a phantom verification)"
  - "ABSENT/CANCELLED are excluded from both numerator and denominator by the HELD_STATUSES filter; a stray verified validation on an ABSENT session still never counts (status filter dominates), pinned by test"
  - "zero_coverage_floors is FLOOR-granular (building_code, floor_number) while the coverage rate is (building, weekday)-granular — the itemized zero list is the coverage analogue of _absence_map, so a checker-less floor is VISIBLE not merely a low percentage"
  - "Coverage pills use the ok/warn/bad ladder (unlike the neutral occupancy pill) because D-04 has a target: 0% is a genuine problem and should read red; the percentage still prints inside the pill so colour is never the only signal (Claude's Discretion on labels/placement)"

patterns-established:
  - "Pattern: two independent safe_card owners for one feature (coverage rate + zero-floor list) each guard their OWN .1 error and include reports/_error_card.html — a raising rate never blanks the zero-floor list (RPT-05 per-section isolation)"
  - "Pattern: a display-only attribute (day_label) attached to a non-frozen aggregate dataclass inside the safe_card wrapper keeps the reporting module free of DayOfWeek label lookups"

requirements-completed: [A6]

coverage:
  - id: D1
    description: "coverage_by_building_day computes verified/HELD per (building, weekday) with a HELD denominator (never scheduled) and a SEPARATE distinct-count verified query; pct == _pct(verified, held) (D-04)"
    requirement: A6
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_coverage.py#CoverageByBuildingDayTests.test_coverage_pct_verified_over_held"
        status: pass
    human_judgment: false
  - id: D2
    description: "Coverage is physical-only: an online V-room session (even one carrying a verified validation) is excluded so the rate measures physical checker verification (D-04)"
    requirement: A6
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_coverage.py#CoverageByBuildingDayTests.test_coverage_excludes_virtual_rooms"
        status: pass
    human_judgment: false
  - id: D3
    description: "A MERGED sibling is held with no CheckerValidation, so it counts in the denominator and lowers coverage — never a phantom verification"
    requirement: A6
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_coverage.py#CoverageByBuildingDayTests.test_merged_sibling_lowers_coverage"
        status: pass
    human_judgment: false
  - id: D4
    description: "An ABSENT session contributes zero to the numerator and is excluded from the HELD denominator; a CANCELLED session contributes nothing to either side"
    requirement: A6
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_coverage.py#CoverageByBuildingDayTests.test_absent_and_cancelled_excluded_from_coverage"
        status: pass
    human_judgment: false
  - id: D5
    description: "zero_coverage_floors lists every (building, floor) with held>0 AND verified==0 explicitly; a fully-covered floor does NOT appear"
    requirement: A6
    verification:
      - kind: integration
        ref: "scheduling/tests_reporting_coverage.py#ZeroCoverageFloorsTests (test_zero_coverage_floor_listed / test_covered_floor_absent)"
        status: pass
    human_judgment: false
  - id: D6
    description: "The coverage sections render on the IFO dashboard, each wrapped in its own safe_card so a raising coverage aggregate errors in its own section and the page still returns 200; @ifo_required still gates access"
    requirement: A6
    verification:
      - kind: integration
        ref: "web/tests_ifo_coverage.py (CoverageSectionTests / ZeroFloorSurfaceTests / CoverageIsolationTests / CoverageAuthTests)"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-20
status: complete
---

# Phase 11 Plan 03: Verification Coverage on the IFO Dashboard Summary

**A checker-verified / HELD coverage aggregate (`coverage_by_building_day`) grouped by building x weekday plus an explicit floor-granular zero-coverage list (`zero_coverage_floors`), physical-rooms-only and HELD-denominated with a SEPARATE distinct-count verified query, surfaced as two independently fault-isolated sections on the IFO dashboard — so a checker-less floor is now VISIBLE rather than indistinguishable from a covered one (A6 / D-04).**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-20T08:59Z
- **Completed:** 2026-07-20T09:17Z
- **Tasks:** 3
- **Files modified:** 7 (3 created)

## Accomplishments
- **`coverage_by_building_day` (Task 1):** verified / HELD by `(building, weekday)`, physical-only via `_exclude_virtual`. Held is one grouped `Count("id", filter... HELD_STATUSES)`-style query; verified is a SEPARATE `Count("id", distinct=True)` query keyed on `(building_code, day)` and folded in Python, mirroring `_verified_map` so a reverse-join can never inflate the rate. `pct = _pct(verified, held)`; deterministic `(building_code, day)` order. MERGED siblings lower the rate by construction (held, no validation) — not special-cased.
- **`zero_coverage_floors` (Task 1):** the coverage analogue of the itemized absence list, at FLOOR granularity `(building_code, floor_number)`. Emits a `ZeroCoverageFloor` for every held floor whose verified count is 0 (held > 0 AND verified == 0), ordered `(building_code, floor_number)`. `CoverageRow` / `ZeroCoverageFloor` dataclasses added beside the existing reporting dataclasses.
- **`make_coverage_fixture` + tests (Task 2):** two physical buildings x two floors, one V-room, seeding partial / zero / full / merged floors + ABSENT (with a stray verified validation, to prove the HELD filter dominates) + CANCELLED + a verified V-room session. Seven mutation-resistant tests, one per D-04 rule.
- **IFO dashboard wiring (Task 3):** `_coverage_card` resolves the `DayOfWeek` int to a label inside its `safe_card` unit (mirroring `_saturation_card`); `dashboard` context carries `coverage` and `zero_floors` `(value, error)` tuples. `templates/ifo/_coverage.html` renders the verified/held table and the explicit zero-floor list, each guarding its OWN `.1` error with `reports/_error_card.html`, with a calm empty state ("Every floor with held sessions had at least one checker verification."). Included in `dashboard.html` after `#report-panel` so it re-renders point-in-time on the GET Apply.

## Task Commits

Each task was committed atomically:

1. **Task 1: coverage_by_building_day + zero_coverage_floors aggregates** - `96880eb` (feat)
2. **Task 2: make_coverage_fixture + mutation-resistant coverage tests** - `1b9432c` (test)
3. **Task 3: wire verification-coverage cards onto the IFO dashboard** - `049a6ca` (feat)

**Plan metadata:** committed separately with STATE.md/ROADMAP.md updates (docs: complete plan).

## Files Created/Modified
- `scheduling/reporting.py` - Added `CoverageRow` / `ZeroCoverageFloor` dataclasses; `coverage_by_building_day` and `zero_coverage_floors` aggregates.
- `scheduling/test_support.py` - `make_coverage_fixture` + `COV_MON/COV_TUE/COV_WED/COV_WEEK_START/COV_WEEK_END` constants.
- `scheduling/tests_reporting_coverage.py` - NEW: DB-backed coverage/zero-floor tests, one per D-04 rule.
- `web/ifo.py` - Extended the `scheduling.reporting` import; added `_coverage_card`; wired `coverage`/`zero_floors` into `dashboard`.
- `templates/ifo/_coverage.html` - NEW: coverage rate table + explicit zero-floor list, per-section `.1` error guards.
- `templates/ifo/dashboard.html` - Included `ifo/_coverage.html` after `#report-panel`.
- `web/tests_ifo_coverage.py` - NEW: render / zero-floor-named / card-isolation / `@ifo_required` tests.

## Decisions Made
- Coverage pills use the ok/warn/bad ladder rather than the neutral occupancy pill: D-04 has a real target, so 0% should read red (colour still never the only signal — the percentage prints inside the pill). This is within the plan's "Claude's Discretion on labels/placement".
- Attached the ABSENT session a stray verified validation in the fixture so the exclusion test is mutation-resistant: it proves the `HELD_STATUSES` filter (not the mere absence of a validation) is what keeps ABSENT out of the numerator.
- Everything else followed the plan and D-04 exactly.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Every targeted module run was green on first execution; no auto-fixes required. The `RuntimeError` lines in test output are intentional `safe_card` leak-isolation / card-isolation side effects (captured, asserted-against), not failures.

## Verification
- `scheduling.tests_reporting_coverage` (7) + `web.tests_ifo_coverage` (13) + `scheduling.tests_reporting` + `scheduling.tests_reporting_rooms` + `web.tests_ifo_utilization` — **180 tests, all green.**
- Coverage denominator is HELD and physical-only; zero-coverage floors are listed explicitly; a raising coverage aggregate degrades to an error card without 500ing the dashboard; `@ifo_required` still refuses a non-IFO user.
- Targeted module runs only (not the full suite), so `FluxTrack_SRS.docx` was NOT regenerated — confirmed untouched in git status (MEMORY guard honored).
- Did NOT touch the live per-floor board in `web/checker.py` — this is the historical/management rollup, distinct from the on-duty view (D-04).

## User Setup Required
None - no external service configuration required. No schema change, no migration.

## Next Phase Readiness
- Plan 11-04 (ghost-room list + per-room utilization CSV, D-05/D-06) is unblocked; it reuses the same `room_breakdown` consumer / `safe_card` surface patterns.
- A6 verification coverage is now visible end-to-end: aggregate (`coverage_by_building_day` / `zero_coverage_floors`) -> IFO dashboard sections. A checker-less week is no longer indistinguishable from a covered one.

## Self-Check: PASSED

All created/modified files exist on disk; all three task commits (`96880eb`, `1b9432c`, `049a6ca`) present in git history.

---
*Phase: 11-metrics-the-mission-promises*
*Completed: 2026-07-20*
