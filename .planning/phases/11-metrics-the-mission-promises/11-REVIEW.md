---
phase: 11-metrics-the-mission-promises
reviewed: 2026-07-20T18:30:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - scheduling/reporting.py
  - scheduling/report_render.py
  - web/hr.py
  - web/ifo.py
  - web/urls.py
  - templates/reports/scorecard.html
  - templates/ifo/dashboard.html
  - templates/ifo/_coverage.html
  - templates/ifo/_cards.html
  - templates/ifo/utilization.html
  - scheduling/tests_reporting_lateness.py
  - scheduling/tests_reporting_coverage.py
  - web/tests_hr.py
  - web/tests_ifo_utilization.py
findings:
  blocker: 0
  major: 0
  minor: 0
  nit: 1
  total: 1
status: clean
---

# Phase 11: Metrics the Mission Promises — Code Review Report

**Reviewed:** 2026-07-20
**Depth:** deep (cross-file, aggregate-correctness focus)
**Files reviewed:** 14 (source + templates + the four decisive test modules)
**Status:** clean — no actionable BLOCKER / MAJOR / MINOR findings

## Summary

This is a metrics phase, so I reviewed it as an aggregate-correctness problem first
and a code-quality problem second. I traced every locked decision (D-01…D-06) from
`11-CONTEXT.md` through the aggregate layer, the render/CSV layers, the views, the
templates, and the mutation-resistant tests, exercising the edge cases the prompt
flagged as highest-risk (NULL `actual_start`, early arrival, in-flight ACTIVE,
MERGED-but-unverified siblings, reverse-join inflation, the seconds-vs-rounded
ghost predicate, CSV injection, and the deferred capacity-fit prohibition).

Every hazard is handled correctly and, in almost every case, additionally pinned by
a named test. The implementation is unusually disciplined: a single shared helper
per concept (`session_minutes_late`, `_session_contribution`), separate-query folds
that structurally cannot inflate status counts, and consistent `as_of`/range/term
scoping across every surface. I could not surface a defensible correctness, security,
or maintainability defect. One documentation imprecision (NIT) is noted below; it is
not a defect and requires no fix to ship.

## Verification performed (adversarial trace)

**1. Lateness fold (D-01 / D-02) — correct.**
- `session_minutes_late` (`scheduling/reporting.py:710-733`) is a pure Python fold:
  `max(0, int((actual_start - scheduled_start).total_seconds()))`. NOT ORM
  DurationField subtraction. `actual_start is None → 0` (explicit, line 731-732);
  early arrival floors at 0. `scheduled_start` is a non-null model field
  (`scheduling/models.py:156`), so the subtraction can never see a `None` left
  operand.
- `_lateness_map` (`reporting.py:444-473`) filters `status__in=HELD_STATUSES,
  actual_start__isnull=False`, so ABSENT/CANCELLED (no start) are excluded and an
  in-flight ACTIVE (`actual_end` NULL) still contributes — lateness needs only the
  start. Magnitude is continuous (`tot + secs`); the chronic-frequency count is
  gated at `secs >= 60` (line 472), so sub-minute check-in noise adds magnitude but
  never trips the flag.
- Chronic flag `held_ws >= 5 and late_ct / held_ws >= 0.30` (lines 537, 706) matches
  D-02 exactly. The `held` (status count) vs `held_with_start` denominator can never
  diverge: the only path that sets a held status without a scan — the Phase 9 Absent
  correction (`web/ifo.py:1914`) — stamps `actual_start = actual_start or
  scheduled_start`, so every held session always carries a start (and a corrected
  session correctly reads as on-time, 0 lateness).
- Tests `tests_reporting_lateness.py` pin all of this (within-grace-late counts,
  sub-minute never counts, ABSENT/CANCELLED excluded, in-flight contributes, chronic
  boundary at 40% vs 20%, the <5-held floor, FacultyRow/Scorecard parity).

**2. Shared-helper contract — honored.**
`web/hr.py:38` imports `session_minutes_late` and the payroll CSV derives its
"Minutes late" cell as `session_minutes_late(s.scheduled_start, s.actual_start) //
60` (line 249) — the same single rule, only floored to whole minutes for payroll
presentation. Lateness is never re-derived anywhere. No DB access occurs inside the
streaming generator (the helper reads already-loaded fields), preserving the MSSQL
HY010 contract.

**3. Coverage (D-04) — correct, no inflation.**
`coverage_by_building_day` / `zero_coverage_floors` (`reporting.py:561-655`) use
denominator = HELD (`HELD_STATUSES`), numerator = a SEPARATE
`Count("id", distinct=True)` query over `validations__action=VERIFIED`, joined back
by key — so a session with multiple verified validations cannot inflate coverage,
and the held count (computed on a queryset with no validations join) cannot be
multiplied. Physical-only via `_exclude_virtual` → `exclude(room__code__startswith
="V")` (the code-prefix idiom, NOT the `is_virtual` property in a filter).
ABSENT/CANCELLED fall outside `HELD_STATUSES`; a MERGED sibling has no
CheckerValidation and therefore lowers the rate. Zero-coverage floors with held
sessions surface as explicit rows (`held > 0 and (code, floor) not in verified_keys`).
`tests_reporting_coverage.py` pins verified/HELD, virtual exclusion (verified total
4 not 5), MERGED lowering, ABSENT+CANCELLED exclusion, and the explicit zero-floor.

**4. Ghost-room (D-05) — correct predicate.**
`ghost_rooms` (`reporting.py:1313-1344`) is a pure reduction of `room_breakdown`
filtered on the UNROUNDED `r.booked_seconds > 0 and r.used_seconds == 0` — never the
quantized `_hours`. `tests_reporting_rooms.py:1150` (`test_ghost_rounding_guard_tiny
_use_not_flagged`) proves a ~40 s-use room (`used_hours == 0.0`, `used_seconds > 0`)
is NOT flagged, and `test_cancelled_room_not_ghost` proves a CANCELLED-only room
(`booked_seconds == 0`) is excluded.

**5. CSV (`utilization_csv`, `web/ifo.py:1585-1631`) — safe.**
`@ifo_required` + `@require_http_methods(["GET"])` (POST→405, non-IFO→403, both
tested). Text cells (code, name, building) pass through `csv_safe`; numeric/Decimal
cells are inert. `UTILIZATION_CSV_HEADER` is a distinct third contract, asserted
`!=` both `report_render.HEADER` and `hr.CSV_HEADER`. Filename is server-built from
the range start (`utilization-{start}.csv`), never request-derived. Scoped to the
same `_reporting_range` + active term as the on-screen table (tests assert the
`start`/`end`/`term`/`as_of` kwargs reach `room_breakdown`).

**6. safe_card fault isolation + scoping — consistent.**
`dashboard` and `utilization` wrap each aggregate in its own `safe_card` owner
(`summary`, `occupancy`, `rows`, `coverage`, `zero_floors`, `grid`, `rollup`,
`breakdown`, `saturation`, `ghosts`), and the templates guard each `.1` error
independently. The load-bearing `breakdown[0] or []` / `rows[0] or []` guards
prevent a single card failure from 500-ing via `Paginator(None)` — regression tests
`DashboardCardIsolationTests` / the ghost-card isolation test hold that line. All
surfaces share the same `_reporting_range` and active-term lookup.

**7. Prohibition (capacity-vs-enrolment T3) — respected.**
`RoomLoad` (`reporting.py:1165-1207`) carries `capacity` (pre-existing) but computes
nothing from it; no seat/enrolment field was added, and `ghost_rooms` explicitly
reads no enrolment. The `reporting.py:947`-era T3 deferral remains closed.

## Narrative Findings (AI reviewer)

### NIT-01: `utilization_csv` docstring says columns "mirror" the on-screen table, but the CSV is a superset

**File:** `web/ifo.py:1576` (docstring) vs `UTILIZATION_CSV_HEADER` at `web/ifo.py:1578-1582`
**Observation:** The on-screen least-used-rooms table (`templates/ifo/utilization.html`,
section 3) renders 8 columns (Room, Building, Floor, Seats, Sessions, Used h,
Reclaimable h, Utilization), while the CSV emits 12 (adds Name, Absent sessions,
Booked h, Available h). The docstring's phrasing "Columns mirror the on-screen
`room_breakdown` table" reads as strict equality; it is actually a superset.
**Why this is not a defect:** The load-bearing contract — "the export and the screen
can never disagree about a room's row" — holds: every value comes from the same
`room_breakdown` rows, so no cell can drift, and a more complete export is expected
and correct behavior. This is a wording imprecision only.
**Fix (optional):** Reword to "…is a superset of the on-screen columns, drawn from
the same `room_breakdown` rows so no cell can disagree."

---

_Reviewed: 2026-07-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
