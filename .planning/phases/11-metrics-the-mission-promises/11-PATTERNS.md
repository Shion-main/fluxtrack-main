# Phase 11: Metrics the Mission Promises - Pattern Map

**Mapped:** 2026-07-20
**Files analyzed:** 6 (1 aggregate module heavily extended, 4 thin surface edits, 1 new CSV view + route)
**Analogs found:** 8 / 8 — every new symbol has an in-file sibling to mirror. No greenfield.

> This is an aggregate-layer + surface phase. Almost nothing is a "new file"; it is
> new functions/dataclass-fields slotted next to an existing sibling in
> `scheduling/reporting.py`, plus thin edits to HR CSV, the weekly-report renderer,
> and the IFO dashboard/utilization views, plus one new per-room CSV view.
> **Rule for the planner:** point each executor at the exact sibling below and say
> "mirror this," never "follow the pattern."

## File Classification

| New/Modified symbol | File | Role | Data Flow | Closest Analog (same file unless noted) | Match |
|---|---|---|---|---|---|
| `session_minutes_late()` helper | `scheduling/reporting.py` | utility (pure formula) | transform | `_session_contribution` (line 512) | exact |
| `_lateness_map()` per-faculty fold | `scheduling/reporting.py` | service (aggregate fold) | batch/transform | `_verified_map` (369) / `_absence_map` (384) | exact |
| `minutes_late_avg` / `late_sessions` / `chronic_late` fields | `scheduling/reporting.py` `FacultyRow` (60) + `Scorecard` (83) | model (dataclass) | CRUD | `early_ends` field + `RoomLoad.*_seconds` defaulted fields (980-983) | exact |
| `coverage_by_building_day()` | `scheduling/reporting.py` | service (aggregate) | batch | `_verified_map` (369) + `faculty_scorecard` conditional aggregate (474-479) | role-match |
| `zero_coverage_floors()` | `scheduling/reporting.py` | service (aggregate) | batch | `_absence_map` (384) list-builder | role-match |
| `ghost_rooms()` | `scheduling/reporting.py` | service (pure reduction) | transform | `room_breakdown` (1005) consumer; reads `RoomLoad.*_seconds` (980-983) | exact |
| lateness columns | `scheduling/report_render.py` `HEADER` (29) + `build_csv` (55) + `build_pdf` (91) | render/config | request-response | existing `HEADER` constant flow | exact |
| derived lateness cell | `web/hr.py` `CSV_HEADER` (51) + `attendance_csv` row gen (226-241) | render (view) | streaming | existing `attendance_csv` streamed row | exact |
| coverage cards | `web/ifo.py` `dashboard` (1336) | controller (view) | request-response | `safe_card` wiring at 1359-1364 | exact |
| ghost-room section | `web/ifo.py` `utilization` (1453) | controller (view) | request-response | `safe_card` wiring at 1477-1481 | exact |
| `utilization_csv()` + route | `web/ifo.py` (new) + `web/urls.py` (~140) | controller (view) | request-response / file-I/O | `scorecard_csv` (1522) in-memory + `attendance_csv` (207) streaming | exact |

## Pattern Assignments

### `session_minutes_late()` — utility, transform (`scheduling/reporting.py`)

**Analog:** `_session_contribution` (line 512) — THE single definition of "used." Mirror its
"one pure function, every caller imports it, no re-derivation" contract for lateness.

Analog signature/docstring discipline to copy (512-518):
```python
def _session_contribution(status, scheduled_start, scheduled_end,
                          actual_start, actual_end):
    """One session's ``(booked_seconds, used_seconds, in_flight)`` (D-03/D-09).

    THE single definition of "used" for this phase. Every room aggregate calls it
    rather than re-deriving the rules, because two implementations of "used" would
    eventually disagree and the whole point of the phase is one honest number.
```
New helper: `max(0, (actual_start - scheduled_start).total_seconds())`, returns 0 when
`actual_start is None`, returns **seconds** internally (caller renders minutes). D-01:
grace-independent. Note null-handling explicitly (the module answers a NULL, never folds it
to a silent zero — see 528-531).

### `_lateness_map(qs)` — aggregate fold, batch (`scheduling/reporting.py`)

**Analog:** `_verified_map` (369) — the sanctioned "separate grouped query / Python fold so a
reverse-join never inflates status counts" pattern. Also `_absence_map` (384) for the
`.values(...)` → dict accumulation shape.

`_verified_map` verbatim (369-381):
```python
def _verified_map(qs):
    """Per-faculty count of DISTINCT sessions with a 'verified' validation.

    A SEPARATE grouped query (not a same-query multi-join) so the reverse-join row
    multiplication can never inflate the status counts. ...
    """
    verified = (
        qs.filter(validations__action=ValidationAction.VERIFIED)
        .values("faculty_id")
        .annotate(n=Count("id", distinct=True))
    )
    return {r["faculty_id"]: r["n"] for r in verified}
```
`_lateness_map` differs: it CANNOT use `Count(filter=Q)` (max/subtraction), so it folds over
`.values_list("faculty_id","scheduled_start","actual_start").iterator()` and calls
`session_minutes_late` per row. Filter `status__in=HELD_STATUSES, actual_start__isnull=False`.
**Pitfall 1 (do NOT copy from `_session_contribution`):** an in-flight ACTIVE session with no
`actual_end` DOES contribute here (lateness needs only the start), unlike `_session_contribution`
which excludes it. Return `{fid: (total_late_seconds, late_count, held_with_start)}`.
Row builder: `chronic = held >= 5 and late/held >= 0.30` (D-02); `avg = total/held/60`.

### `FacultyRow` / `Scorecard` new fields — dataclass (`scheduling/reporting.py`)

**Analog:** existing `early_ends: int` field on both (69, 92) for a plain int, and
`RoomLoad.*_seconds: int = 0` (980-983) for defaulted additive fields. Add
`minutes_late_avg`, `late_sessions`, `chronic_late` mirroring the existing field style.
`Scorecard` is built by `faculty_scorecard` (464); `FacultyRow` by `faculty_attendance`.
`faculty_scorecard`'s conditional-aggregate block (474-479) is the sibling for any held-count
already computed — reuse `held`, feed `_lateness_map(qs).get(faculty.id, ...)`.

### `coverage_by_building_day()` / `zero_coverage_floors()` — aggregate, batch

**Analog:** `_verified_map` (369) for the SEPARATE verified query (never a same-query join with
the held count — D-04), and `faculty_scorecard`'s `Count("id", filter=Q(status__in=HELD_STATUSES))`
(476) for the HELD denominator. `_absence_map` (384-399) is the sibling for the explicit-list
output shape (`zero_coverage_floors` = the coverage analogue of the itemized absence list).
Physical-only via `_exclude_virtual(qs)` (157) — see Shared Patterns. Percent via `_pct`.
**Open (A2/A3, planner to lock):** `day` axis = weekday vs calendar date; virtual rooms excluded
(recommended). Grouping: `(building, weekday)` for the rate, `(building_code, floor_number)` for
the zero list.

### `ghost_rooms()` — pure reduction, transform (`scheduling/reporting.py`)

**Analog:** `room_breakdown` (1005) as the source; `RoomLoad.*_seconds` (980-983) as the fields.
```python
used_seconds: int = 0
booked_seconds: int = 0
wasted_seconds: int = 0
```
`ghost_rooms(...) = [r for r in room_breakdown(...) if r.booked_seconds > 0 and r.used_seconds == 0]`.
**CRITICAL (Pitfall 2):** predicate on the unrounded `*_seconds`, NEVER the quantized `_hours`
Decimals — a room with 0.04h of real use rounds to `used_hours == 0.0` but is genuinely used;
flagging it would be a lie. Do NOT re-query — `room_breakdown` already walks the whole physical
room universe room-side (never-used rooms present) and excludes virtual rooms. The RoomLoad
docstring (961-964) states the `*_seconds` fields are "the unrounded truth the rollup reduces."
**Do NOT add a seat/enrolment field to `RoomLoad`** (reopens the T3 deferral, docstring 945-950).

### Weekly-report lateness columns — render/config (`scheduling/report_render.py`)

**Analog:** the single `HEADER` constant (line 29), shared by `build_csv` (55) and `build_pdf` (91).
```python
HEADER = ["Faculty", "Scheduled", "Held", "Absent", "Attendance %", "Checker-verified"]
```
Append the lateness columns here once; `FacultyRow`'s new fields flow into both renderers
automatically. **Pitfall 4:** keep chronic terse ("Yes"/"") so the landscape-A4 PDF table
(now 8 short numeric cols) does not overflow. **Pitfall 5:** this `HEADER` is a DISTINCT contract
from `web.hr.CSV_HEADER` — editing one does NOT cover the other.

### HR derived-lateness cell — view (`web/hr.py`)

**Analog:** `attendance_csv` (207) + its `CSV_HEADER` (51). The row generator (226-241) is the
insertion point; add one derived cell computed inline via `session_minutes_late(s.scheduled_start,
s.actual_start)`. Existing row (230-241) keeps the raw `_fmt_dt(s.actual_start)` cell (D-03 — add,
don't remove). `CSV_HEADER` (51-54) gains one column header. This is a SEPARATE contract from
`report_render.HEADER` (Pitfall 5). Text cells already go through `csv_safe`; the derived cell is
numeric (no csv_safe needed). This view STREAMS (`_Echo` + `StreamingHttpResponse`, 187/244) —
**no DB write inside the generator** (MSSQL HY010 trap, documented at 218-221).

### Coverage cards on dashboard / ghost-room on utilization — view (`web/ifo.py`)

**Analog:** `dashboard` `safe_card` wiring (1359-1364) and `utilization` wiring (1477-1481):
```python
summary = safe_card(dept_summary, start=start, end=end, department=None, as_of=as_of)
occupancy = safe_card(room_utilization, start=start, end=end, term=term, as_of=as_of)
```
Add `coverage = safe_card(coverage_by_building_day, start=start, end=end, as_of=as_of)` to
`dashboard`; add `ghosts = safe_card(ghost_rooms, **scope)` to `utilization` (which already builds
`scope = {"start","end","term","as_of"}` at 1475). Pass raw tuples to context unwrapped; template
guards `card.1` per card (RPT-05). Keep `date_from`/`date_to`/`range_note` present.

### `utilization_csv()` + route — new view (`web/ifo.py` + `web/urls.py`)

**Analog (recommended, in-memory):** `scorecard_csv` (1522) — the D-06 discretion note favors
in-memory since the physical-room universe is bounded (~125):
```python
@ifo_required
@require_http_methods(["GET"])
def scorecard_csv(request, faculty_id):
    ...
    start, end, as_of, _note = _reporting_range(request)
    rows = [r for r in faculty_attendance(start=start, end=end, as_of=as_of) ...]
    resp = HttpResponse(build_csv(rows), content_type="text/csv")
    resp["Content-Disposition"] = (
        f'attachment; filename="scorecard-{faculty.id}-{start}.csv"')
    return resp
```
Mirror exactly: `@ifo_required @require_http_methods(["GET"])`, `_reporting_range(request)`,
active-term lookup (`AcademicTerm.objects.filter(is_active=True).first()`, as in `utilization`
1474), one row per `room_breakdown()` `RoomLoad`, server-built filename, `HttpResponse`. Run
text cells (`code`, `name`, `building_name`) through `csv_safe`. **Alternative (streaming symmetry):**
`attendance_csv`'s `_Echo` + `StreamingHttpResponse` idiom (187-246) — either is acceptable per D-06.
Route: add next to the existing IFO CSV route in `web/urls.py` (scorecard_csv at 142-143), e.g.
`path("ifo/utilization.csv", ifo.utilization_csv, name="ifo_utilization_csv")` beside the
`ifo/utilization` route at 140.

## Shared Patterns

### Physical-room / virtual exclusion
**Source:** `scheduling/reporting.py` `_physical_rooms` (139) / `_exclude_virtual` (157).
**Apply to:** `coverage_by_building_day`, `zero_coverage_floors` (ghost_rooms inherits it via
`room_breakdown`).
```python
def _exclude_virtual(qs):
    return qs.exclude(room__code__startswith="V")
```
`Room.is_virtual` is a PROPERTY, not a column — never use it in `filter()`/`Q()`.

### Separate-query discipline (no reverse-join inflation)
**Source:** `_verified_map` (369).
**Apply to:** `_lateness_map`, coverage verified count. Never join verified/lateness in the same
query as the status counts.

### HELD denominator + `_pct` rounding
**Source:** `faculty_scorecard` `Count("id", filter=Q(status__in=HELD_STATUSES))` (476);
`_pct` (used at 460, 505).
**Apply to:** coverage rate, chronic ratio. Denominator is HELD, never scheduled (D-04). Use
`_pct` / Decimal ROUND_HALF_UP, never Python `round()` (banker's rounding).

### `safe_card` fault isolation
**Source:** `web/ifo.py` 1359-1364, 1477-1481. Wrap every new aggregate; template guards `card.1`;
keep the load-bearing `or []` before `paginate` (1372, 1487).

### CSV injection safety
**Source:** `scheduling.report_render.csv_safe` (report_render.py:40), reused in `web/hr.py` (231-239).
**Apply to:** every text cell of the new per-room CSV (room code, name, building_name).

## No Analog Found

None. Every new symbol has a direct in-file sibling.

## Metadata

**Analog search scope:** `scheduling/reporting.py`, `scheduling/report_render.py`, `web/hr.py`,
`web/ifo.py`, `web/urls.py`.
**Files scanned:** 5 (all first-party, already the phase's insertion points per RESEARCH.md).
**Deferred (NOT mapped):** capacity-vs-enrollment fit, week-over-week trend, seat/enrolment fields
on `RoomLoad` (T3 deferral at reporting.py:947).
**Pattern extraction date:** 2026-07-20
