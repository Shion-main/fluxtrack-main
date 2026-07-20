# Phase 11: Metrics the Mission Promises - Research

**Researched:** 2026-07-20
**Domain:** Django reporting-aggregate extension + IFO/HR/report surfaces (pure Python + ORM; no new dependencies)
**Confidence:** HIGH — every claim below is `[VERIFIED: codebase]` from direct source reads of the exact files being extended. No external packages are introduced, so no web/registry research was required.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Minutes-late is continuous, grace-independent.** Per-session minutes late = `max(0, actual_start − scheduled_start)`, computed in the aggregate layer (`scheduling/reporting.py`), matching audit A3 verbatim. **NOT** gated on `grace_minutes`. Only sessions with a non-null `actual_start` (actually held) contribute; ABSENT / CANCELLED have no start and are excluded.
- **D-02 — Chronic-late flag = frequency ≥30%, reported next to magnitude.** Flagged chronically late when late (`minutes_late > 0`) in **≥ 30% of held sessions** over the range, floor of **≥ 5 held sessions** to qualify. Always shown alongside **average minutes late over held sessions**. A raw count threshold was rejected.
- **D-03 — Lateness surfaced in all three places A3 names:** faculty **scorecard**, **weekly report**, and **HR CSV export**. HR keeps the raw `actual_start` timestamp AND adds a derived lateness column.
- **D-04 — Verification coverage = verified ÷ held, by building & day.** Denominator is **held** (not scheduled); numerator is checker-verified. Grouped by **building & day**. **Zero-coverage floors listed explicitly.** Surfaced on the **IFO dashboard**. Distinct from the live per-floor board.
- **D-05 — Ghost-room list = booked-but-never-used.** Physical rooms with `booked_hours > 0` AND `used_hours = 0` over the range. Derived from the `RoomLoad` aggregate.
- **D-06 — Per-room utilization CSV export.** Finish 06.1-07: per-room CSV of the `room_breakdown` / `RoomLoad` rows.

### Claude's Discretion

- Exact placement/labels of new scorecard and dashboard columns/cards, as long as they honour the existing IFO/faculty shell and token system.
- Whether to carry a per-session `past_grace` boolean for drill-down context. A display nicety only — it is NOT the definition of "late" (D-01 governs) and must never gate the minutes-late number.
- CSV column set/order, filename, and streaming vs in-memory, as long as it matches the on-screen breakdown and scopes to the same range/term.
- Whether chronic-late lives as a computed property on the scorecard dataclass or a helper — implementation detail, as long as D-02's definition holds.

### Deferred Ideas (OUT OF SCOPE — do NOT research or plan)

- **Capacity-vs-enrollment "fit" (A8).** DESCOPED. Reopening reverses the documented T3 deferral at `scheduling/reporting.py:947`: `Schedule.enrolled_count` trustworthiness is unproven and `seed_term` leaves it 0. Do NOT add a seat/enrolment field to `RoomLoad` or anywhere. Reopen only after `enrolled_count` is validated on a real imported term, as its own follow-up.
- **Week-over-week utilization trend (A8).** Out of scope.
- The two 06.1 open questions (physical vs physical-teaching denominator; a utilization target band) remain deliberately open and are NOT decided here.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| A3 | Lateness captured but never surfaced — compute `max(0, actual_start − scheduled_start)` in the aggregate layer; surface on scorecard + weekly report + HR export | New fields on `FacultyRow` + `Scorecard`; a single `session_minutes_late()` helper reused by the aggregate fold AND the HR per-session CSV; `report_render.py` HEADER/build_csv/build_pdf gain columns; `web/hr.py` CSV_HEADER gains a column. See Architecture Pattern 1 & 2. |
| A6 | No verification-coverage metric — build verified/held by building/day, list zero-coverage floors, on IFO dashboard | New `coverage_by_building_day()` + `zero_coverage_floors()` aggregates following the `_verified_map` separate-query discipline; wired as new `safe_card` sections in `web.ifo.dashboard`. See Pattern 3. |
| A8 (partial) | Utilization depth — ghost-room list + CSV (capacity-fit & trend DEFERRED) | `ghost_rooms()` derived from `room_breakdown()` using the unrounded `*_seconds` fields; new `web.ifo.utilization_csv` view + route. See Pattern 4 & 5. |
| IFO-09 / 06.1-07 | Finish the deliberately-dropped per-room CSV export | Streaming or in-memory CSV over `room_breakdown()` rows, `csv_safe`-neutralized, scoped by `_reporting_range`. See Pattern 5. |
</phase_requirements>

## Summary

Phase 11 is a **pure extension of one mature, heavily-conventioned module** (`scheduling/reporting.py`) plus **four thin surface edits** (scorecard template, weekly-report render layer, HR CSV, IFO dashboard) and **one new CSV view**. There are no new libraries, no schema changes, no migrations, and no changes to attendance capture, session resolution, or the room-hours definitions. Every input the new metrics need already exists on `Session` (`actual_start`, `scheduled_start`, `status`), on the `validations` reverse relation (checker verification), and on `RoomLoad` (`booked_seconds` / `used_seconds`).

The single most important discipline to replicate: this module computes held/absent/verified **from `Session.status` truth**, never re-derived from timestamps, and it isolates status counts from reverse-join inflation by using **separate grouped queries** (`_verified_map`, `_absence_map`) rather than a same-query multi-join. Lateness and coverage must obey the same rule — a `HELD_STATUSES` numerator, a separate verified query, and a Python fold (the established precedent for anything `Count(filter=Q)` cannot express, e.g. `room_utilization`'s streamed contribution loop).

**Primary recommendation:** Add lateness via one shared pure helper `session_minutes_late(scheduled_start, actual_start)` in `reporting.py` (the "single definition" sibling of `_session_contribution`), consumed by both a per-faculty aggregate fold and the per-session HR CSV so the two can never drift. Add coverage as two new separate-query aggregates. Derive ghost-rooms and the per-room CSV from the *existing* `room_breakdown()` output using the unrounded `*_seconds` fields (never the quantized `_hours`). Wire every new aggregate through `safe_card` exactly like the current dashboard/utilization views.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Minutes-late & chronic-late computation | Aggregate layer (`scheduling/reporting.py`) | — | D-01 mandates the aggregate layer; the formula must live once and be reused. |
| Per-session lateness for HR payroll CSV | Aggregate layer (helper) → HR view (`web/hr.py`) | — | HR is session-grain, not aggregate-grain; it imports the shared formula helper and applies it per row. |
| Verification coverage (verified/held by building/day + zero-coverage floors) | Aggregate layer | IFO view (`web/ifo.py` dashboard) | Historical/management rollup; distinct from the operational live board in `web/checker.py`. |
| Ghost-room list | Aggregate layer (derived from `room_breakdown`) | IFO utilization view/template | Pure reduction of an existing aggregate — no new query. |
| Per-room utilization CSV | Render/response tier (`web/ifo.py` new view) | Aggregate layer (`room_breakdown`) | Response building is the view's job; the aggregate stays side-effect-free. |
| Weekly report lateness columns | Render layer (`scheduling/report_render.py`) | `ops/reports.py` (unchanged orchestration) | `FacultyRow` fields flow automatically into `build_csv`/`build_pdf`. |

## Standard Stack

No new packages. The phase uses only what is already imported and in use.

### Core (already present — do not add versions)
| Library | Purpose | Why standard here |
|---------|---------|--------------------|
| Django ORM (`Count`, `Q`, `Case`, `When`, `F`, `.values_list().iterator()`) | Conditional aggregation + streamed folds | The module's established idiom for both DB-side counts and the room-hours Python fold. |
| stdlib `csv` + `scheduling.report_render.csv_safe` | Injection-safe CSV | The single phase-wide CSV-injection neutralizer (T-06-02), already reused by weekly + HR CSV. |
| `reportlab` (Platypus) | Weekly-report PDF | Already the PDF renderer in `report_render.build_pdf`. |
| `decimal.Decimal` + `ROUND_HALF_UP` | Rounding discipline | `_pct` / `_hours_pct` / `_hours` establish the exact-tie rounding contract to mirror. |

**Installation:** none. `pip index versions` / `npm view` not applicable — this phase installs nothing.

## Package Legitimacy Audit

Not applicable — this phase installs **zero** external packages. All code is added to existing first-party modules using already-imported stdlib and Django APIs. No registry verification required.

## Architecture Patterns

### System Architecture Diagram

```
                    Session.status truth (ACTIVE/COMPLETED=held, ABSENT, CANCELLED)
                    Session.actual_start / scheduled_start
                    validations reverse relation (CheckerValidation action=VERIFIED)
                              │
                              ▼
   ┌──────────────────────  scheduling/reporting.py  (PURE aggregate layer) ──────────────────────┐
   │                                                                                                │
   │  session_minutes_late(sched_start, actual)  ── NEW single formula (max(0, actual−sched))       │
   │        │                     │                                                                 │
   │        ▼                     ▼                                                                 │
   │  _lateness_map(qs)     coverage_by_building_day(start,end,as_of)   ghost_rooms(...)            │
   │  (per-faculty fold)    zero_coverage_floors(start,end,as_of)       └── reduces room_breakdown()│
   │        │                     │                        (separate grouped queries, no join       │
   │        ▼                     │                         inflation — mirror _verified_map)        │
   │  faculty_attendance ──► FacultyRow (+minutes_late_avg, +late_sessions, +chronic_late)          │
   │  faculty_scorecard  ──► Scorecard (+ same fields)                                               │
   └────────┬─────────────────────┬────────────────────┬────────────────────┬─────────────────────┘
            │                     │                    │                    │
            ▼                     ▼                    ▼                    ▼
   report_render.build_csv    web.ifo.dashboard    web.ifo.utilization   web.ifo.utilization_csv (NEW)
   report_render.build_pdf    (+coverage safe_card)  (+ghost-room section)  stream/in-memory CSV
   (weekly report bytes)      dashboard.html         utilization.html       + web/urls.py route
   web.hr.attendance_csv                                                    csv_safe on text cells
   (+ derived lateness col,
    per-session, uses helper)
```

Everything flows from `Session.status` truth through the pure aggregate layer into surfaces. The new code never touches capture/resolution/room-hours definitions.

### Pattern 1: The single-definition pure helper (mirror `_session_contribution`)

**What:** One pure function owns the lateness formula so the faculty aggregate and the HR per-session CSV cannot drift — exactly as `_session_contribution` is THE single definition of "used" for every room aggregate.

**When to use:** Any figure computed in more than one place.

```python
# Source: scheduling/reporting.py — proposed, modelled on _session_contribution (line 512)
def session_minutes_late(scheduled_start, actual_start):
    """Whole (or fractional) minutes late for ONE held session (A3 / D-01).

    max(0, actual_start - scheduled_start), grace-INDEPENDENT. Returns 0 when
    actual_start is None (never held). THE single definition; the faculty
    aggregate fold and the HR per-session CSV both import it so they cannot drift.
    """
    if actual_start is None:
        return 0
    delta = int((actual_start - scheduled_start).total_seconds())
    return max(0, delta)  # seconds internally; caller renders minutes
```

> **Decision the planner must pin (see Assumptions Log A1):** whether "late" for the chronic test is `delta_seconds > 0` (any positive delta, so a 40-second-late start counts) or floored whole-minutes `> 0` (sub-minute lateness reads as on-time). D-01 says "continuous, grace-independent," which argues for `seconds > 0`. Recommend: compute and store seconds internally; a session is *late* iff `seconds > 0`; render **average minutes late** as a `Decimal` quantized to one place (mirroring `_hours`) or a rounded int. This edge is a first-class VALIDATION case.

### Pattern 2: Per-faculty Python fold for lateness (mirror `_verified_map` / `_absence_map`)

**What:** `Count(filter=Q)` cannot express `max(0, actual_start − scheduled_start)`, and DurationField subtraction is explicitly noted as *unverified on mssql-django* with no module precedent (`reporting.py:655-660`). The sanctioned escape hatch is a bounded Python fold over `.values_list(...).iterator()` — the exact deviation `room_utilization` already documents and justifies.

**When to use:** Adding `minutes_late_avg`, `late_sessions`, `chronic_late` to `FacultyRow` (in `faculty_attendance`) and `Scorecard` (in `faculty_scorecard`).

```python
# Source: scheduling/reporting.py — proposed, modelled on _verified_map (line 369)
def _lateness_map(qs):
    """{faculty_id: (total_late_seconds, late_count, held_with_start)} over HELD sessions.

    A SEPARATE fold (like _verified_map) so it never inflates the status counts.
    Only HELD_STATUSES rows with a non-null actual_start contribute (D-01).
    Note: an in-flight ACTIVE session (no actual_end) DOES contribute here —
    lateness needs only the START, unlike room_utilization which excludes it.
    """
    out = {}
    rows = (qs.filter(status__in=HELD_STATUSES, actual_start__isnull=False)
              .values_list("faculty_id", "scheduled_start", "actual_start")
              .iterator())
    for fid, sched, actual in rows:
        secs = session_minutes_late(sched, actual)
        tot, late, held = out.get(fid, (0, 0, 0))
        out[fid] = (tot + secs, late + (1 if secs > 0 else 0), held + 1)
    return out
```

Then in the row builder: `chronic = held_with_start >= 5 and late_count / held_with_start >= 0.30` (D-02); `avg = total_late_seconds / held_with_start / 60` rendered to one decimal.

**Key subtlety (VERIFIED):** the denominator for both the average and the chronic ratio is **held sessions that have an `actual_start`** — which for `HELD_STATUSES` is effectively all of them, since a class is only ACTIVE/COMPLETED after check-in stamps `actual_start`. Keep the `actual_start__isnull=False` guard anyway (defensive; a MERGED-filled sibling is held and receives a stamped start, but never assume).

### Pattern 3: Coverage aggregates (separate grouped queries; HELD denominator)

**What:** Two aggregates. (a) `coverage_by_building_day` — for each `(building, weekday)`, `held` (conditional count over `HELD_STATUSES`) and `verified` (a *separate* distinct-session count filtered to `validations__action=VERIFIED`), then `pct = _pct(verified, held)`. (b) `zero_coverage_floors` — the explicit list of `(building_code, floor_number)` where `held > 0 AND verified == 0` (the coverage analogue of the ghost-room list).

**When to use:** New `safe_card`(s) on `web.ifo.dashboard`.

Conventions to honour:
- **Denominator is HELD**, never scheduled (D-04, and consistent with every rate in the module).
- **Separate verified query** — never a same-query join with the held count, or the reverse-join multiplies rows and inflates held (the reason `_verified_map` exists).
- **MERGED siblings** are held but have no `CheckerValidation` → correctly counted as held-but-unverified, lowering coverage. This is the honest behaviour; do not "fix" it.
- **`day`** should be the day-of-week (`Session.date.weekday()` / `schedule__day_of_week`) to match the heat-grid day axis, OR the calendar `Session.date`. **Flag (A2):** D-04 says "by building & day" but audit A6 asks "which floors/buildings had zero coverage" — the grouping granularity (building×weekday for the rate vs. floor for the zero-list) is a deliberate two-view design; confirm the `day` axis with the planner. Recommend weekday to align with the existing heat grid.
- **Virtual-room handling (A3 in Assumptions):** grouping by building/floor only makes sense for **physical** rooms. Online sessions are verified by an `online_checker` and also produce a `VERIFIED` `CheckerValidation` (ValidationScope gates FLOOR vs ONLINE, but the *action* is the same `VERIFIED`). Recommend **exclude virtual rooms** (`_exclude_virtual` / physical-only) so coverage measures physical floor coverage as A6/D-04 intend; online verification coverage is a separate concern and out of scope. Confirm with planner.

### Pattern 4: Ghost-room list — reduce an existing aggregate, use unrounded seconds

**What:** `ghost_rooms(*, start, end, term, as_of=None)` = `[r for r in room_breakdown(...) if r.booked_seconds > 0 and r.used_seconds == 0]`.

**CRITICAL (VERIFIED):** filter on the **unrounded `*_seconds` fields on `RoomLoad`** (lines 980-983), NOT the quantized `_hours` Decimals. A room with 0.04 h of real use rounds to `used_hours == 0.0` but is genuinely *used* — flagging it as a ghost would be a lie. `booked_hours > 0 AND used_hours == 0` in rounded hours is a mutation trap; `booked_seconds > 0 AND used_seconds == 0` is the honest predicate. This is the stricter-than-"wasted hours > 0" definition D-05/`<specifics>` demand: the heat grid already shows partial waste; ghost = *zero* occupancy.

Do not re-query — `room_breakdown` already walks every physical room (room-side, so never-used rooms are present) and excludes virtual rooms (D-04/D-08). One reduction keeps ghost-rooms reconciled with the breakdown table on the same page.

### Pattern 5: Per-room CSV export (finish 06.1-07)

**What:** New `@ifo_required @require_http_methods(["GET"])` view `utilization_csv(request)` + route `path("ifo/utilization.csv", ...)`. Scope with `_reporting_range(request)` and the active term (identical to `web.ifo.utilization`). Emit one row per `room_breakdown()` `RoomLoad`, columns matching the on-screen breakdown (code, name, building, floor, session_count, absent_sessions, used/booked/available/wasted hours, utilization %). Run text cells (`code`, `name`, `building_name`) through `csv_safe`.

**Streaming vs in-memory (discretion, D-06):** the physical-room universe is bounded (~125 rooms), so **in-memory is acceptable** here (cf. `report_render.build_pdf`'s "bounded → in-memory" precedent), unlike the unbounded HR full-term export which *must* stream. Either is fine per D-06; recommend in-memory `HttpResponse` for simplicity, or reuse the `_Echo` + `StreamingHttpResponse` idiom from `web/hr.py:187-246` if the planner prefers symmetry. Do NOT perform any DB write inside a streaming generator (MSSQL HY010 cursor-open trap — see `web/hr.py:221`).

### Anti-Patterns to Avoid

- **Re-deriving held/absent from timestamps.** Read `Session.status` truth (`HELD_STATUSES`). RPT-01's central rule.
- **Same-query multi-join for verified/lateness alongside status counts.** Reverse-join row multiplication inflates counts. Use separate grouped queries / folds (`_verified_map` pattern).
- **DurationField subtraction in the ORM for lateness.** Unverified on mssql-django, no module precedent (`reporting.py:655-660`). Use the Python fold.
- **Ghost-room predicate on rounded `_hours`.** Use `*_seconds`. (Pattern 4.)
- **Gating minutes-late on `grace_minutes` or `past_grace`.** D-01: grace-independent. `past_grace` is display-only nicety, never the definition.
- **Adding a seat/enrolment/capacity-fit field to `RoomLoad`.** Reopens the T3 deferral (`reporting.py:947`). Explicitly OUT of scope.
- **`pk__in` id lists.** MSSQL 2100-param trap; keep room-id sets bounded (the module's rule).
- **Filtering on `scheduled_start` for date windows.** Use the local `Session.date` DateField (Asia/Manila; no UTC drift) — `_scoped_sessions` already does this.
- **`Room.is_virtual` in a `filter()`/`Q()`.** It is a *property*, not a column. Physical-only is `exclude(code__startswith="V")` (`_physical_rooms` / `_exclude_virtual`).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Date-window / `as_of` parsing | A new range parser | `web.reporting_common.reporting_range` (imported as `_reporting_range`) | One role-agnostic parser already feeds IFO/Dean/HR. |
| CSV injection safety | Manual quoting | `scheduling.report_render.csv_safe` | The single phase-wide neutralizer (T-06-02). |
| Per-card fault isolation | try/except in the view | `safe_card(fn, **kwargs)` → `(value, error)` | Established RPT-05 pattern; template guards `card.1`. |
| Percent rounding | `round()` / int division | `_pct` / `_hours_pct` (Decimal, ROUND_HALF_UP) | Python `round()` is banker's rounding; stakeholders recompute by hand. |
| Physical-room population | `Room.objects.all()` | `_physical_rooms()` / `_exclude_virtual()` | Excludes V-rooms AND out-of-service rooms (A7) correctly. |
| Used-hours definition | New "used" logic | `_session_contribution` (already consumed by `room_breakdown`) | Two definitions of "used" would eventually disagree. |
| Pagination of a card list | Manual slicing | `web.pagination.paginate` (+ the load-bearing `or []`) | `Paginator(None)` dies on `len()`; `safe_card` returns `None` on failure. |

**Key insight:** Nearly every "new" thing this phase needs already has a single blessed implementation. The work is *composition*, not construction.

## Common Pitfalls

### Pitfall 1: In-flight ACTIVE sessions treated the same for lateness as for utilization
**What goes wrong:** Copying `room_utilization`'s "exclude in-flight" rule into the lateness fold would drop a running class that started late.
**Why:** `_session_contribution` excludes ACTIVE-no-`actual_end` because *used hours* are unknowable without an end. Lateness needs only `actual_start`, which exists.
**How to avoid:** Lateness fold filters `status__in=HELD_STATUSES, actual_start__isnull=False` and does NOT exclude missing `actual_end`.
**Warning sign:** A currently-running-but-late class shows 0 minutes late.

### Pitfall 2: Ghost-room false positives from Decimal rounding
**What goes wrong:** A room with a few minutes of real use rounds to `used_hours 0.0` and is wrongly listed as a ghost.
**How to avoid:** Predicate on `used_seconds == 0` (Pattern 4).
**Warning sign:** A room appears in both the ghost list and the heat grid with non-zero cells.

### Pitfall 3: CANCELLED / ABSENT leaking into numerators
**What goes wrong:** ABSENT contributes to lateness or to the coverage numerator; CANCELLED counts as held.
**Why:** ABSENT has no `actual_start`; CANCELLED (Phase 9, A1) is neither held nor absent nor booked.
**How to avoid:** Lateness filters `HELD_STATUSES` + `actual_start__isnull=False` (excludes both). Coverage held-count uses `HELD_STATUSES` (excludes ABSENT and CANCELLED). Verified count is intrinsically only on verified sessions.
**Warning sign:** An all-absent faculty row shows a non-zero average-minutes-late; a suspension-day floor drags coverage.

### Pitfall 4: Weekly-report PDF column overflow
**What goes wrong:** Adding avg-minutes-late + chronic to the 6-column landscape-A4 table pushes to 8 columns and wraps ugly.
**How to avoid:** Landscape A4 accommodates 8 short numeric columns; keep the chronic flag terse (e.g. "Yes"/"") and confirm the `HEADER` list stays in sync across `build_csv` and `build_pdf` (they share the one `HEADER` constant — good).
**Warning sign:** ReportLab table overruns the frame.

### Pitfall 5: Two CSV header contracts drift
**What goes wrong:** `report_render.HEADER` (weekly/Dean/scorecard CSV) and `web.hr.CSV_HEADER` (payroll) are **separate constants**. Adding lateness to one but not the other, or expecting one edit to cover both.
**How to avoid:** Treat them as two deliberate contracts. Weekly/scorecard lateness = aggregate fields on `FacultyRow` → `report_render.HEADER` + `build_csv`/`build_pdf`. HR payroll lateness = per-session, computed inline via `session_minutes_late` → `web.hr.CSV_HEADER` + the row generator in `attendance_csv`.
**Warning sign:** HR CSV shows lateness but the weekly report doesn't (or vice-versa).

## Runtime State Inventory

Not a rename/refactor/migration phase — this is additive computation over existing data with **no schema change, no migration, no stored-string rename**. Explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no new columns, no data rewrite. New metrics are computed at query time. | None |
| Live service config | None | None |
| OS-registered state | None | None |
| Secrets / env vars | None | None |
| Build artifacts | None — pure Python edits, no packaging change | None |
| **Stored report bytes** | Existing `WeeklyReport` rows hold PDF/CSV bytes with the OLD column set. | On next weekly generation the new columns appear; historical stored reports keep the old shape (acceptable — regeneration is idempotent via `get_or_create`). No back-fill required. |

## Code Examples

### Reading the module's separate-query verified count (the pattern coverage copies)
```python
# Source: scheduling/reporting.py:369-381 (VERIFIED)
def _verified_map(qs):
    verified = (
        qs.filter(validations__action=ValidationAction.VERIFIED)
        .values("faculty_id")
        .annotate(n=Count("id", distinct=True))
    )
    return {r["faculty_id"]: r["n"] for r in verified}
```

### The `safe_card` wiring every new card copies
```python
# Source: web/ifo.py:1359-1364 (VERIFIED)
summary = safe_card(dept_summary, start=start, end=end, department=None, as_of=as_of)
occupancy = safe_card(room_utilization, start=start, end=end, term=term, as_of=as_of)
# NEW: coverage = safe_card(coverage_by_building_day, start=start, end=end, as_of=as_of)
```

### The unrounded seconds fields ghost-rooms must read
```python
# Source: scheduling/reporting.py:980-983 (VERIFIED) — RoomLoad
used_seconds: int = 0
booked_seconds: int = 0
wasted_seconds: int = 0
```

### HR per-session CSV row (where a derived lateness cell is inserted)
```python
# Source: web/hr.py:230-241 (VERIFIED) — add one cell computed via session_minutes_late
yield writer.writerow([
    csv_safe(s.faculty.get_full_name() or s.faculty.username),
    ...,
    _fmt_dt(s.actual_start),          # raw timestamp KEPT (D-03)
    # NEW derived cell, e.g. minutes-late from session_minutes_late(s.scheduled_start, s.actual_start)
    status_label(s.status),
    ...,
])
```

## State of the Art

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| Raw `actual_start` in HR CSV, no lateness anywhere | Derived minutes-late + chronic flag in the aggregate layer, surfaced on 3 places | This phase (A3) | A dean can finally answer "who is habitually late." |
| Verification counted per-faculty only, never rolled up | Coverage rate by building/day + explicit zero-coverage floors | This phase (A6) | A checker-less week is no longer indistinguishable from a covered one. |
| Utilization = heat grid + single snapshot | + actionable ghost-room list + per-room CSV | This phase (A8 partial) | Facilities can act on named booked-but-never-used rooms and export. |

**Deprecated/outdated:** nothing removed. HR keeps its raw timestamp column (D-03).

## Validation Architecture

Nyquist validation is **enabled**. Tests run under **Django's test runner** (not pytest) via the full `Python312` interpreter path for `manage.py`. Dev DB `fluxtrack` is separate from test DB `test_fluxtrack`. The house style is **mutation-resistant, one-assertion-per-rule** DB-free `SimpleTestCase` for pure arithmetic + DB-backed `TestCase` over fixtures (see `scheduling/tests_reporting_rooms.py`, class-per-concern; e.g. `test_unflagged_early_end_still_counts_as_wasted`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django test runner (`unittest`-based `TestCase`/`SimpleTestCase`) |
| Config file | none — Django `settings` + `manage.py test` |
| Quick run command | `<full Python312 path>\python.exe manage.py test scheduling.tests_reporting_rooms -v2` (add new lateness/coverage test modules as siblings) |
| Full suite command | `<full Python312 path>\python.exe manage.py test` |
| Fixtures | `scheduling/test_support.py` — `make_room_utilization_fixture`, `make_reporting_fixture`, `_aware(date, time)`; reuse these, extend with lateness/coverage variants. |

> **Guard (from MEMORY):** a full test run regenerates `FluxTrack_SRS.docx`; `git checkout` it before committing.

### Phase Requirements → Test Map
| Req | Behavior | Test type | Ground truth to assert | File |
|-----|----------|-----------|------------------------|------|
| A3 | `session_minutes_late` formula | unit (`SimpleTestCase`, DB-free) | `max(0, actual−sched)`; None start → 0; early start (actual<sched) → 0 (not negative) | new `tests_reporting_lateness.py` |
| A3 | avg-minutes-late over held | DB `TestCase` | Fixture with known late deltas → exact average over held-with-start | ❌ Wave 0 |
| A3 | chronic threshold boundary | DB `TestCase` | 4-held-with-2-late → NOT chronic (below 5 floor); 5-held-with-2-late (40%) → chronic; 5-held-with-1-late (20%) → NOT chronic | ❌ Wave 0 |
| A3 | HR CSV derived column | DB `TestCase` (existing HR test style) | A late session's row shows the derived minutes; raw `actual_start` cell still present | extend `web/tests_*hr*` |
| A3 | weekly/scorecard render | DB `TestCase` | `build_csv`/`build_pdf` header includes lateness; `FacultyRow`/`Scorecard` carry the fields | `scheduling/tests_reporting.py` + render tests |
| A6 | coverage = verified/held | DB `TestCase` | Fixture: N held on a floor, M verified → pct == `_pct(M,N)`; MERGED sibling held-but-unverified lowers it | ❌ Wave 0 |
| A6 | zero-coverage floor listed | DB `TestCase` | A floor with held>0 and verified==0 **appears** in the list; a fully-covered floor does not | ❌ Wave 0 |
| A8 | ghost-room list | DB `TestCase` | `booked_seconds>0 & used_seconds==0` room appears; a room with tiny use (rounds to 0.0h but seconds>0) does NOT appear | ❌ Wave 0 |
| A8 / 06.1-07 | per-room CSV | DB `TestCase` (view test) | CSV row count == physical rooms; a formula-triggering room name is `csv_safe`-neutralized; scope matches on-screen range | ❌ Wave 0 |
| all | `safe_card` isolation | DB `TestCase` | A raising new aggregate renders the error card, page still 200 (mirror `DashboardCardIsolationTests`) | extend `web/tests_ifo_utilization.py` |

### Mutation-resistant edge cases (must each be a distinct assertion)
- **Within-grace-but-late still counts.** A session late by less than `grace_minutes` (so never ABSENT) must have `minutes_late > 0` and contribute to chronic. This is the whole point of D-01 — pin it.
- **Sub-minute lateness boundary.** A session 40 seconds late: assert the chosen definition (recommend `seconds > 0` → late). Pin whichever the planner locks (Assumption A1).
- **Early arrival is not negative lateness.** `actual_start < scheduled_start` → 0, never a negative that would cancel out a genuinely-late sibling in the average.
- **ABSENT contributes zero** to both lateness (no `actual_start`) and the coverage numerator, and is excluded from the coverage denominator (held-only).
- **CANCELLED contributes nothing** to lateness, coverage, or ghost-rooms (Phase 9 A1 rule).
- **In-flight ACTIVE (no `actual_end`) DOES contribute to lateness** (Pitfall 1) — assert a running late class shows minutes late, in contrast to its exclusion from `room_utilization`.
- **Chronic floor.** ≥5 held required: a light week with 1 late of 3 held is never chronic.
- **MERGED sibling** is held but unverified → lowers coverage; never contributes a phantom verification.
- **Ghost-room rounding guard:** a room with `used_seconds > 0` that rounds to `used_hours == 0.0` must NOT be a ghost.
- **Zero-coverage floor with held sessions** must appear explicitly in the list (not merely as a low percentage).

### Sampling Rate
- **Per task commit:** run the touched test module (`manage.py test scheduling.tests_reporting_lateness` etc.).
- **Per wave merge:** `manage.py test scheduling web` (aggregate + surface suites).
- **Phase gate:** full suite green before `/gsd-verify-work`; `git checkout FluxTrack_SRS.docx` afterward.

### Wave 0 Gaps
- [ ] `scheduling/tests_reporting_lateness.py` — covers A3 (formula unit + aggregate + chronic boundary).
- [ ] `scheduling/tests_reporting_coverage.py` — covers A6 (rate + zero-coverage floors + MERGED).
- [ ] Ghost-room + per-room CSV tests — extend `scheduling/tests_reporting_rooms.py` and a `web` view test for the CSV route.
- [ ] Lateness fixtures in `scheduling/test_support.py` (known deltas, an in-flight late session, an ABSENT, a CANCELLED, a within-grace-late).
- [ ] Framework install: none — existing runner covers all.

## Security Domain

`security_enforcement` is not disabled in config → applicable. Threat surface is **narrow** (read-only aggregates + CSV export; no new writes, no new auth).

### Applicable ASVS Categories
| Category | Applies | Standard control (already present) |
|----------|---------|-----------------------------------|
| V4 Access Control | yes | `@ifo_required` / `@hr_required` role gates on every surface; the new CSV view MUST carry `@ifo_required @require_http_methods(["GET"])`. IFO is unscoped by design. |
| V5 Input Validation | yes | `_reporting_range` degrades bad dates to a friendly note, never a 500 (T-06-11/16). New CSV view reuses it. |
| V7 Info Disclosure | yes | `safe_card` logs the real exception server-side and returns a generic message (never the raw exception to the template). |
| V6 Cryptography | no | none introduced |

### Known Threat Patterns
| Pattern | STRIDE | Mitigation (reuse, do not hand-roll) |
|---------|--------|--------------------------------------|
| CSV/formula injection in export | Tampering | `scheduling.report_render.csv_safe` on every text cell (room name, faculty name, building). |
| Path traversal via export filename | Tampering | Server-built filename only (mirror `web/hr.py:243`); never request-derived. |
| MSSQL cursor-open (HY010) in a streaming CSV | DoS | No DB write inside the generator; resolve verification via annotation in the main query (HR precedent). |
| Unauthorized access to institution-wide metrics | Elevation/Info-disclosure | Role decorators; the per-room CSV and coverage are IFO-only. |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | "Late" for the chronic test means `actual_start − scheduled_start` in **seconds > 0** (any positive delta), with average rendered in minutes. D-01 says "continuous"; but whether sub-minute lateness counts as a "late session" for the 30% frequency is not spelled out. | Pattern 1/2, Validation | If the intended definition is floored whole-minutes, a habitually 30-seconds-late faculty would flip in/out of chronic. Low blast radius, but a definitional edge — confirm in discuss/plan. |
| A2 | The coverage `day` axis is **day-of-week** (aligning with the heat-grid axis), while zero-coverage is listed at **floor** granularity. D-04 says "by building & day"; A6 says "floors/buildings." | Pattern 3 | Wrong granularity means the dashboard groups by calendar date instead of weekday (or vice-versa). Cosmetic-to-moderate; confirm. |
| A3 | Coverage **excludes virtual rooms** (physical floor coverage), so online-checker verifications are out of this metric. Online sessions DO produce a `VERIFIED` validation, so including them would change the denominator. | Pattern 3 | If online sessions should count, coverage numbers and the zero-floor list change materially. Flag for discuss — recommend physical-only. |
| A4 | Per-room CSV in-memory (`HttpResponse`) is acceptable because the physical-room universe is bounded (~125). D-06 leaves streaming-vs-in-memory to discretion. | Pattern 5 | If room count grows unbounded (multi-campus), streaming would be needed. Currently safe. |

**These four are the only unverified points.** Everything else is `[VERIFIED: codebase]` from direct reads.

## Open Questions (RESOLVED)

> A1 (chronic-late granularity), A2 (coverage axis), A3 (virtual-room inclusion)
> are all pinned by CONTEXT.md D-01..D-06 + the planner's locked steers:
> chronic frequency counts ≥1 whole minute (`secs >= 60`); coverage axis =
> weekday, physical-only; held denominator. Traceable across RESEARCH → PLAN.


1. **Chronic-late "late" granularity (A1).** Seconds>0 vs floored minutes>0. *Recommendation:* seconds>0 (matches D-01 "continuous, grace-independent"); render average as one-decimal minutes.
2. **Coverage grouping axis + virtual-room inclusion (A2/A3).** *Recommendation:* group by (building, weekday), list zero-coverage floors, exclude virtual rooms. Confirm in planning.
3. **Chronic display when a faculty has <5 held.** D-02 floors the flag at 5; the surface should show the average-minutes figure but suppress the chronic flag (not show "not chronic" as if evaluated). *Recommendation:* render the flag only when `held >= 5`, else show only the magnitude.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Django + existing app | all | ✓ (in use) | project-pinned | — |
| `reportlab` | weekly-report PDF | ✓ (imported in `report_render.py`) | present | — |
| MSSQL (mssql-django) / dev SQL Server | runtime | ✓ (dev + test DBs exist) | — | — |
| Python312 interpreter (full path) | test runner | ✓ | 3.12 | — |

**No missing dependencies.** This phase adds nothing to install.

## Sources

### Primary (HIGH confidence — direct source reads this session)
- `scheduling/reporting.py` (full) — aggregate layer, all conventions, `FacultyRow`/`Scorecard`/`RoomLoad` dataclasses, `_session_contribution`, `_verified_map`, `room_breakdown`, `safe_card`.
- `scheduling/models.py:99-198` — `Session`/`Schedule`/`SessionStatus` fields, `enrolled_count`, `verified_by_checker`.
- `web/hr.py` (full) — HR session-grain CSV, `CSV_HEADER`, streaming `_Echo` idiom, `csv_safe` reuse.
- `web/ifo.py:1336-1599` — dashboard, utilization, scorecard, weekly-report views + `safe_card` wiring.
- `scheduling/report_render.py` (full) — `HEADER`, `csv_safe`, `build_csv`, `build_pdf`.
- `ops/reports.py` (full) — weekly report generation over `faculty_attendance` → `FacultyRow`.
- `web/reporting_common.py` — `reporting_range`, `status_label`.
- `web/checker.py:670-713` — the live/operational coverage (the metric to NOT duplicate).
- `verification/models.py:18-67` — `ValidationAction.VERIFIED`, scope FLOOR/ONLINE.
- `docs/AUDIT-2026-07-19.md` §A3/A6/A8 — the mission promises being redeemed.
- `scheduling/tests_reporting_rooms.py` + `scheduling/test_support.py` — the mutation-resistant test style + fixtures.
- `web/urls.py:137-143` — IFO route patterns for the new CSV route.

### Secondary / Tertiary
None — no web or registry research was required for this internal-only phase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all APIs already in use.
- Architecture / insertion points: HIGH — read every file and function being extended.
- Pitfalls: HIGH — derived from the module's own documented rules and existing tests.
- The 4 Assumptions (A1-A4): MEDIUM — genuine definitional/granularity choices for discuss/plan to lock.

**Research date:** 2026-07-20
**Valid until:** 2026-08-19 (stable internal module; refresh if `reporting.py` conventions change).
