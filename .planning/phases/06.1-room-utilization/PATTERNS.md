# Phase 06.1: Room Utilization & IFO-09 Closure - Pattern Map

**Mapped:** 2026-07-19
**Files analyzed:** 8 new/modified
**Analogs found:** 8 / 8 (all exact or role-match; this phase is net-new analysis
over an established layer, not a new architecture)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scheduling/reporting.py` (extend) | service/aggregate | batch + transform | itself, `dept_summary` / `faculty_attendance` | exact (in-file) |
| `web/room_state.py` (extend or reuse) | service | transform | `room_timetable()` L92-136 | exact (in-file) |
| `templates/ifo/_cards.html` (modify) | component | request-response | itself, the Attendance % card L28-36 | exact (in-file) |
| `web/ifo.py` utilization view (new or extend `dashboard`) | controller | request-response | `dashboard` L1297-1315 | exact |
| `templates/ifo/utilization.html` (new, if own page) | component | request-response | `templates/ifo/dashboard.html` + `room_detail.html` L53-90 | exact |
| `templates/ifo/_heatgrid.html` (new) | component | transform | `room_detail.html` timetable table L53-90 + `static/css/timetable.css` | exact |
| `static/css/timetable.css` (extend) or `heatgrid.css` (new) | config/style | n/a | `timetable.css` L16-50 | exact |
| `scheduling/tests_reporting_rooms.py` (new) | test | n/a | `scheduling/tests_reporting.py` L1-46 | exact |

---

## Verification of D-02 (no migration) — field-by-field, with refs

D-02's claim **holds**. Every field it names exists. Verified:

| Metric need | Field | Ref |
|---|---|---|
| Booked hours | `Session.scheduled_start` / `scheduled_end` | `scheduling/models.py:100-101` |
| Used hours | `Session.actual_start` / `actual_end` (both `null=True`) | `scheduling/models.py:105-106` |
| Booked-but-empty | `Session.status` (`SessionStatus`) | `scheduling/models.py:70` |
| Early end | `Session.ended_early` (BooleanField, default False) | `scheduling/models.py:125` |
| Reclaimed instant | `Session.room_released_at` (nullable DateTimeField) | `scheduling/models.py:127` |
| Local-date filter key | `Session.date` | used at `scheduling/reporting.py:113-114` |
| Seat capacity (T3, deferred) | `Room.capacity` | `campus/models.py:30` |
| Enrolled (T3, deferred) | `Schedule.enrolled_count` | `scheduling/models.py:53` |
| Building rollup | `Room.floor -> Floor.building` | `campus/models.py:14-15, 27` |
| Floor rollup | `Floor.number`, `unique_together (building, number)` | `campus/models.py:16-19` |

**No migration is needed.** Two caveats the planner must carry:

1. `actual_start` and `actual_end` are **nullable**. A COMPLETED session with a
   null `actual_end` is real in this data (`seed_term` sets `actual_start` on
   in-flight ACTIVE sessions at `scheduling/management/commands/seed_term.py:391`
   but not `actual_end`). Used-hours arithmetic must define its null policy
   explicitly — an ACTIVE session with no `actual_end` is running, not zero-hours.
2. `Session.date` is the local DateField; `scheduled_start`/`actual_start` are UTC
   `DateTimeField`s. **Filter on `date`, compute durations on the datetimes.**
   Mixing these is the exact bug `scheduling/reporting.py:20-23` was written to
   prevent.

---

## `Room.is_virtual` is a PROPERTY, not a field — this is load-bearing

`campus/models.py:44-54`:

```python
@property
def is_virtual(self):
    """True for a virtual (online-only) room. ... the code IS the flag
    and no second column has to be kept in sync with it."""
    return self.code.upper().startswith("V")
```

It is a Python property over `Room.code`. It **cannot** appear in `.filter()`,
`Q()`, `values()`, `order_by()`, or a `Count(filter=...)`. Any queryset reaching
for `is_virtual=False` raises `FieldError`.

**How to express "physical rooms only" in a queryset.** The established, already-
in-production idiom is a `code__startswith` exclusion. `seed_term` does exactly
this, both directions, at `scheduling/management/commands/seed_term.py:253-255`:

```python
physical = list(Room.objects.exclude(code__startswith="V")...)
virtual  = list(Room.objects.filter(code__startswith="V").order_by("code"))
```

For the aggregates, spanning the Session FK:

```python
# denominator: physical rooms only
Room.objects.exclude(code__startswith="V")
# session-side: exclude sessions in virtual rooms
qs.exclude(room__code__startswith="V")
```

Note `Room.code` is stored under the DB-wide **case-insensitive** collation (only
`qr_token` and `manual_code` are CS_AS — `campus/models.py:32-36`), so
`startswith="V"` already matches a lowercase `v` prefix on MSSQL, matching the
property's `.upper()`. Do not add `istartswith`; it would diverge from the two
existing call sites for no behavioural gain.

**Recommendation for the planner:** add ONE shared helper to
`scheduling/reporting.py` (e.g. `_physical_rooms()` / `_exclude_virtual(qs)`) and
route every room aggregate through it, so the `"V"` literal appears once in the
reporting layer rather than in six aggregate bodies.

---

## How many blocks the campus ladder actually has

**The ladder is DATA-DERIVED, not a constant. There is no hardcoded 11 anywhere
in the code.** `web/room_state.py:110-113`:

```python
slots = sorted(set(
    Schedule.objects
    .filter(term=term, status=ScheduleStatus.ACTIVE)
    .values_list("start_time", flat=True)))
```

The ladder is *every distinct `Schedule.start_time` in the active term*. Its
length changes when the imported timetable changes, and it is `None`/absent when
there is no active term or no active schedules (`room_state.py:108-115` returns
`None` in both cases).

The context doc's "11" is a correct **observation of the current dataset**, not a
constant: `room_detail.html:50-51` renders `{{ timetable.capacity }}` and the
observed "77 slots" is `capacity = len(rows) * len(DayOfWeek.choices)`
(`room_state.py:136`) = 11 rows x **7** days. `DayOfWeek` has seven members
including SAT and SUN (`scheduling/models.py:12-19`).

**Consequences for the plan:**
- Never write `11` into the denominator. Compute `len(slots)` at query time.
- The denominator must handle the `None` ladder (no active term) — that is a
  legitimate zero-denominator, and `_pct` already guards it
  (`reporting.py:98-99`).
- "Teaching days" in D-01 is 7 by the ladder's own definition, not 5. If the plan
  wants 5, that is a *new* decision and must be stated, not assumed — the printed
  timetable renders all 7 and D-01's stated goal is that the dashboard and the
  timetable "cannot disagree about what a slot is."

---

## Pattern Assignments

### `scheduling/reporting.py` — room aggregates (service, batch/transform)

**Analog:** itself. Room aggregates join this module and must be
indistinguishable in shape from `dept_summary` / `faculty_attendance`.

**Module contract** (docstring L1-24) — the rules the new code inherits verbatim:
read-only, no `notify()`, no baked-in `timezone.now()` (range + `as_of` are
arguments), DB-side conditional aggregation, filter on local `Session.date`,
never a large PK `IN` list.

**Dataclass-return pattern** (L64-72) — every aggregate returns a dataclass, not
a dict. Room aggregates should add e.g. `RoomUtilization`, `BuildingRow`,
`HeatCell` in the same block:

```python
@dataclass
class DeptSummary:
    """Department-wide totals over a range (RPT-01 / DEAN-04 / IFO-09 cards)."""
    faculty_count: int
    scheduled: int
    held: int
    absent: int
    attendance_pct: int
```

**Shared-queryset pattern** (L104-122) — `_scoped_sessions` is the single slice
every aggregate starts from. The room aggregates should call it, then add the
virtual-room exclusion, rather than rebuilding the filter:

```python
def _scoped_sessions(*, start, end, department=None, as_of=None, faculty=None):
    qs = Session.objects.filter(
        date__range=(start, end), schedule__status=ScheduleStatus.ACTIVE,
    )
    ...
    if as_of is not None:
        qs = qs.filter(date__lte=as_of)
    return qs
```

Note the two filters that come free and MUST be preserved: `date__range` (local
date, no Manila drift) and `schedule__status=ScheduleStatus.ACTIVE` (archived
schedules are not real obligations). A room aggregate that bypasses this helper
will silently count archived bookings into the denominator.

**Keyword-only signature convention** — every public aggregate is `*,`-prefixed
(L163, L206, L224). New room aggregates must match: `def room_utilization(*,
start, end, as_of=None)`.

**DB-side `Count(filter=Q)` pattern** (L173-182) — the canonical shape:

```python
status_rows = (
    qs.values("faculty_id", "faculty__first_name", "faculty__last_name")
    .annotate(
        scheduled=Count("id"),
        held=Count("id", filter=Q(status__in=HELD_STATUSES)),
        absent=Count("id", filter=Q(status=SessionStatus.ABSENT)),
        early_ends=Count("id", filter=Q(ended_early=True)),
    )
    .order_by("faculty__last_name", "faculty__first_name")
)
```

For rooms this becomes `.values("room_id", "room__code",
"room__floor__number", "room__floor__building__code")` with the same
`Count(filter=Q(...))` block. **`Sum`/`F` duration arithmetic is new** — this
module has no precedent for it, so it is the one genuinely novel construct in the
phase. Keep it DB-side (`Sum(F("actual_end") - F("actual_start"))`) and verify on
MSSQL; if it does not translate cleanly, the fallback is the module's own stated
preference for a single grouped query over a Python loop, so aggregate the raw
components in SQL and do the division in Python — see `_pct` below.

**Separate-query rule** (L129-141) — when a second relation is needed, use a
SECOND grouped query and merge in Python, never a same-query multi-join, because
reverse-join row multiplication inflates counts:

```python
verified = (
    qs.filter(validations__action=ValidationAction.VERIFIED)
    .values("faculty_id")
    .annotate(n=Count("id", distinct=True))
)
return {r["faculty_id"]: r["n"] for r in verified}
```

This applies directly to the heat grid: derive the ladder separately, derive the
per-cell counts separately, merge by `(day, block)` key in Python.

**Zero-denominator + rounding pattern** (L88-101) — utilization % must reuse
`_pct`, not reimplement rounding:

```python
def _pct(held, scheduled):
    if not scheduled:
        return 0
    return int((Decimal(100 * held) / Decimal(scheduled)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
```

`_pct` is int-typed. Room-hours are fractional, so either round hours to a
consistent unit before calling `_pct`, or add a sibling `_hours_pct` in the same
Decimal/ROUND_HALF_UP idiom. Do NOT introduce float division — L94-96 explains
why binary-float artifacts are excluded here.

**`safe_card` — mandatory per D-05** (L272-287). It is a *wrapper called by the
view*, not a decorator on the aggregate:

```python
def safe_card(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except Exception:  # deliberately broad: per-card isolation is the point
        logger.exception(
            "Reporting card failed: %s", getattr(fn, "__name__", repr(fn)))
        return None, "This section could not be loaded."
```

Contract the templates depend on: it returns a **2-tuple `(value, error)`**.
Templates index it positionally as `card.0` / `card.1` (see `_cards.html:8`,
`:41`). Every new utilization card must be wrapped the same way and every new
template must check `.1` first.

**Zero-safety idiom** — `.aggregate()` returns `None` for empty sets, so every
read is `agg["x"] or 0` (L216-220). Room aggregates over an empty range must do
the same or they will `TypeError` on the arithmetic.

---

### `web/room_state.py` `room_timetable()` — the block ladder (service, transform)

**Exact signature:** `room_timetable(room, term)` — positional, two args
(`room_state.py:92`).

**Exact return shape** (`room_state.py:134-136`), or `None`:

```python
return {"days": DayOfWeek.choices, "rows": rows,
        "used": sum(1 for r in rows for c in r["cells"] if c is not None),
        "capacity": len(rows) * len(DayOfWeek.choices)}
```

where each row is `{"time": <datetime.time>, "cells": [<Schedule|None>, ...]}`
with `cells` in `DayOfWeek.choices` order (7 entries, Mon..Sun).

Returns `None` when `term is None` (L108-109) **or** when the term has no active
schedules (L114-115). Both callers must handle `None`.

**What the heat grid CAN reuse:** the ladder derivation itself (L110-113) and the
half-open slot-occupancy rule (L131) — `s.start_time <= slot < s.end_time`, which
is why a double-length class fills two rows with no rowspan bookkeeping. The
`DayOfWeek.choices` day axis is also directly reusable as the grid's columns.

**What the heat grid must BUILD:** `room_timetable` is **per-room** and
**Schedule-based**, not campus-wide and not Session-based. Three mismatches:

1. It takes a single `room` and reads `room.schedules` (L117-119). The heat grid
   is campus-wide across all physical rooms.
2. Its cells are `Schedule` objects — **bookings**. D-03 is explicit that this is
   the booking count and "is exactly the mistake this phase exists to correct."
   The heat grid's cells must be aggregated over `Session`.
3. Its per-room virtual handling (L123-124) filters *schedules by modality within
   one room*; the grid needs *rooms excluded from the population* (D-04).

**Recommended split for the planner:** extract the ladder derivation (L110-113)
into a small shared function — e.g. `campus_block_ladder(term) -> list[time] |
None` — in `web/room_state.py`, have `room_timetable` call it (behaviour-preserving,
no change to its return shape), and have the new Session-based grid aggregate call
it too. That satisfies "reuse it, do not re-derive the ladder" without forcing the
grid through a per-room, Schedule-shaped function that cannot answer its question.

Caution: the ladder derivation is a query on `Schedule`, so putting it in the
aggregate path means the reporting layer gains a `Schedule`-table read. That is
consistent with `_scoped_sessions` already joining `schedule__status`.

---

### `templates/ifo/_cards.html` — the IFO-09 card set (component, request-response)

**Analog:** itself.

**Which card to replace — precisely.** The grid at L11 is
`lg:grid-cols-4` and holds exactly four cards:

| Position | Card | Lines | SRS status |
|---|---|---|---|
| 1 | Faculty (`users` icon) | 12-16 | keep — SRS card 1 |
| 2 | Sessions, held/scheduled (`layers`) | 17-22 | keep — SRS card 3 |
| 3 | Absences (`calendar-x`) | 23-27 | keep — SRS card 4 |
| 4 | **Attendance % (`percent`)** | **28-36** | **the intruder — occupies the slot the SRS assigns to Room Occupancy** |

**Card 4 is the one to replace** with "Room Occupancy in session-hours". Its full
current body:

```html
<div class="uk-card uk-card-body">
  <div class="uk-text-small uk-text-muted flex items-center gap-1">
    <uk-icon icon="percent" class="size-4"></uk-icon> Attendance %</div>
  {% with pct=summary.0.attendance_pct %}
  <div class="mt-1">
    <span class="uk-label" style="{% if pct >= 90 %}background:var(--green-tint);color:var(--green){% elif pct >= 75 %}background:var(--amber-tint);color:var(--amber){% else %}background:var(--red-tint);color:var(--red){% endif %};font-size:1.4rem;padding:2px 10px">{{ pct }}%</span>
  </div>
  {% endwith %}
</div>
```

Judgement call the planner should surface rather than silently make: Attendance %
is a *useful* metric that stakeholders may now expect. Two honest options — (a)
straight swap to four SRS cards, closing IFO-09 exactly as written; (b) go to five
cards (`lg:grid-cols-5` or a 2x3), keeping Attendance % alongside Room Occupancy.
(a) is the literal IFO-09 closure and the safer default; (b) needs an owner
decision because it deviates from the SRS wording IFO-09 is verified against.

**Simple-KPI card pattern to copy** for the new Room Occupancy card — the Sessions
card (L17-22), because it has the same "value / total" shape that session-hours
used/booked needs:

```html
<div class="uk-card uk-card-body">
  <div class="uk-text-small uk-text-muted flex items-center gap-1">
    <uk-icon icon="layers" class="size-4"></uk-icon> Sessions</div>
  <div class="uk-h2 mt-1">{{ summary.0.held }}<span class="uk-text-muted uk-text-small"> / {{ summary.0.scheduled }}</span></div>
  <div class="uk-text-small uk-text-muted">held / scheduled</div>
</div>
```

**Per-section error pattern** (L8-10, L41-43) — every independent section opens
with its own `.1` check:

```html
{% if summary.1 %}
  {% include "reports/_error_card.html" %}
{% else %}
  ...
{% endif %}
```

A new utilization section is a THIRD independent section and needs its own
`(value, error)` pair and its own guard — not a shared one, or a utilization
failure takes the attendance cards down with it.

**Threshold-colour pattern** (L66) — the `.pill` vocabulary, which pairs colour
with a **text value**, satisfying the never-colour-alone rule the heat grid must
also satisfy:

```html
<span class="pill {% if row.attendance_pct >= 90 %}pill--ok{% elif row.attendance_pct >= 75 %}pill--warn{% else %}pill--bad{% endif %}">{{ row.attendance_pct }}%</span>
```

**Empty state pattern** (L70) — say what is empty and what to do, in one cell:

```html
<tr><td colspan="5" class="uk-text-muted">No attendance in this range. No sessions were scheduled for the selected dates. Adjust the range above.</td></tr>
```

---

### `web/ifo.py` `dashboard` — card-set assembly (controller, request-response)

**Analog:** `web/ifo.py:1297-1315`.

**Full assembly pattern:**

```python
@ifo_required
def dashboard(request):
    start, end, as_of, note = _reporting_range(request)
    summary = safe_card(
        dept_summary, start=start, end=end, department=None, as_of=as_of)
    rows = safe_card(
        faculty_attendance, start=start, end=end, department=None, as_of=as_of)
    pager = paginate(request, rows[0])
    return render(request, "ifo/dashboard.html", {
        "summary": summary, "rows": rows,
        "date_from": start, "date_to": end, "range_note": note, **pager,
    })
```

Five conventions to copy exactly:
1. `@ifo_required` (defined `web/ifo.py:47`) on every IFO view.
2. `_reporting_range(request)` first, unpacked as a **4-tuple**.
3. Each aggregate wrapped in `safe_card`, passed as `fn` + kwargs — not called.
4. The raw `(value, error)` tuple goes into the context unwrapped; the template
   indexes `.0`/`.1`.
5. `date_from` / `date_to` / `range_note` always in context, because the shared
   range filter partial re-renders the applied window and the note.

**Live bug to inherit-around:** `pager = paginate(request, rows[0])` at L1311
passes `rows[0]`, which is `None` when the card errored. `paginate` accepts a list
or queryset (`web/pagination.py:24-31`) and `Paginator(None, ...)` will raise —
so a `faculty_attendance` failure defeats the very isolation `safe_card` provides.
Any new paged utilization table must guard: `paginate(request, rows[0] or [])`.
Worth flagging to the planner as a one-line fix to the existing line too.

**Import alias convention** (`web/ifo.py:44`) — the range parser is imported under
its old private name so the call sites read unchanged:

```python
from web.reporting_common import reporting_range as _reporting_range
```

**`_reporting_range` — parse + degrade** (`web/reporting_common.py`, `reporting_range`):

Returns `(start, end, as_of, note)`. Behaviour the planner can rely on without
re-implementing:
- Default window = configured `reporting_week_start` policy weekday through today.
- `?from=` / `?to=` ISO dates via `parse_date`.
- **Bad input never 500s.** An unparseable date sets both bounds to `None`, falls
  back to the current week, and returns a user-facing `note`:
  `"That date range wasn't valid, so we're showing the current week."`
- Inverted range (`start > end`) also degrades to the current week with its own
  note.
- `as_of` is **always today**, so a future not-yet-missed session never lowers a
  rate. Room utilization must pass `as_of` through for the same reason: a
  not-yet-happened booking is not wasted room-hours.

---

### Heat grid rendering — visual rhyme with the printed timetable

**Analog:** `templates/ifo/room_detail.html:53-90` + `static/css/timetable.css`.

**Table skeleton to mirror** (`room_detail.html:57-67`) — the time column is a
`<th scope="row">`, the days come off `timetable.days`:

```html
<th scope="col" class="tt__time">Time</th>
{% for value, label in timetable.days %}
...
{% for row in timetable.rows %}
  <th scope="row" class="tt__time">{{ row.time|time:"g:i A" }}</th>
```

**Free-cell pattern** (`room_detail.html:89`) — the established never-colour-alone
implementation, and the exact idiom the heat grid's zero cell should reuse:

```html
<td class="tt__off"><span aria-hidden="true">&ndash;</span><span class="sr-only">free</span></td>
```

**CSS vocabulary to extend** (`static/css/timetable.css:16-39`):

```css
.tt { width: 100%; border-collapse: collapse; font-size: .8rem; table-layout: fixed; }
.tt th, .tt td { border: 1px solid var(--line); padding: 6px 7px; vertical-align: top; text-align: left; }
.tt__time { width: 84px; white-space: nowrap; text-align: right !important;
  font-variant-numeric: tabular-nums; background: var(--panel-2); color: var(--ft-muted); }
.tt__on { background: var(--navy-tint); }
```

The heat scale should be added as intensity modifiers in this same file and
vocabulary (e.g. `.tt__heat--1` .. `.tt__heat--5` over `--navy-tint`), so one
stylesheet governs both grids and they cannot visually diverge. Every heat cell
must carry the numeric value as text, per the `pill` and `tt__off` precedent.

`timetable.css` is loaded per-page, not globally (`room_detail.html:12`):

```html
<link rel="stylesheet" href="{% static 'css/timetable.css' %}"/>
```

**After ANY CSS edit run `py -3.12 manage.py collectstatic --noinput`** — per
CONTEXT, a missed collectstatic has shipped an unstyled surface here twice.

---

### A new IFO console page (if utilization gets its own surface)

**Nav — `templates/ifo/_console.html`.** Add under the existing `Reporting`
section (the `cns__sec` divider), between Dashboard and Weekly reports. Copy the
Dashboard link exactly; note `is-active` is driven by `un` (the resolved URL name)
and `aria-current="page"` is repeated in the same condition:

```html
<div class="cns__sec">Reporting</div>
<a href="/ifo/dashboard" class="cns__link {% if un == 'ifo_dashboard' %}is-active{% endif %}"
   {% if un == 'ifo_dashboard' %}aria-current="page"{% endif %}>
  <uk-icon icon="bar-chart-3"></uk-icon> Dashboard</a>
```

hrefs here are **hardcoded literal paths**, not `{% url %}`. Follow the local
convention. Leaf pages extend `ifo/_console.html` and fill
`console_title` / `page_actions` / `console`.

**URL — `web/urls.py`.** FLAT named patterns, no namespace, no trailing slash,
grouped by area. Add beside the reporting group (`web/urls.py:106-113`):

```python
path("ifo/dashboard", ifo.dashboard, name="ifo_dashboard"),
path("ifo/scorecard/<int:faculty_id>", ifo.scorecard, name="ifo_scorecard"),
```

Name it `ifo_utilization` at `ifo/utilization` to match the `ifo_<noun>` pattern.

**Table stack.** `.table-wrap` wrapping `.tbl`, with `p-0` on the card, then the
shared pager (`_cards.html:44-45`, `:75`):

```html
<div class="uk-card uk-card-body p-0 table-wrap">
  <table class="tbl">
    ...
    <th scope="col" class="tbl__num">Scheduled</th>
```

```html
{% include "_pager.html" %}
```

`web/pagination.py:24` — `paginate(request, object_list, per_page=DEFAULT_PER_PAGE,
param="page")` returns a context dict spread with `**pager`. It accepts a plain
list (the reporting surfaces build lists of dataclasses, not querysets), clamps
out-of-range pages instead of raising, and preserves every other GET param so a
page link keeps the active `from`/`to` filter (L43-44). Numeric cells use
`tbl__num`; identifier cells use `tbl__id`.

Per CONTEXT: Franken `uk-*` only on IFO surfaces. The navy `.ft-*` vocabulary is
Faculty/Guard. No border-left accent stripes.

**Discretion note (D-05 leaves this open):** the per-building/floor table,
least-used rooms and saturated blocks are three tables plus a grid — more than the
dashboard's current two sections. A dedicated `ifo/utilization` page is the better
fit; the Room Occupancy KPI card still lands on the dashboard, and should link to
the new page the way `_cards.html:59` links a faculty row to its scorecard,
forwarding the range:

```html
href="{% url 'ifo_scorecard' row.faculty_id %}?from={{ date_from|date:'Y-m-d' }}&to={{ date_to|date:'Y-m-d' }}"
```

---

### Tests — `scheduling/tests_reporting_rooms.py` (new)

**Analog:** `scheduling/tests_reporting.py:1-46`.

**Which module room-aggregate tests should join.** A NEW sibling module,
`scheduling/tests_reporting_rooms.py`, not an addition to `tests_reporting.py`.
Precedent: this app already splits reporting tests by concern
(`tests_reporting.py`, `tests_report_render.py`, `tests_room_master.py`). Room
utilization is a distinct aggregate family with its own fixture needs.

**Docstring + import conventions** (L1-26) — the module docstring names each test
class and its contract, imports are alphabetized from `scheduling.reporting`, and
private helpers under test (`_pct`) are imported explicitly:

```python
from django.test import SimpleTestCase, TestCase

from scheduling.models import Modality, SessionStatus
from scheduling.reporting import (
    HELD_STATUSES, AbsenceItem, DeptSummary, FacultyRow, Scorecard,
    _pct, dept_summary, faculty_attendance, faculty_scorecard, safe_card,
)
from scheduling.test_support import make_reporting_fixture
```

Rules stated in that docstring and binding here: **Django `TestCase`, not
pytest**; **reference module constants** (`SessionStatus`, `HELD_STATUSES`,
`Modality`) and never a bare status string. Pure-arithmetic tests use
`SimpleTestCase` (no DB) — the utilization-rate maths should follow
`PctRoundingTests` (L29-45) and test rounding/zero-denominator without touching
the DB.

**Runner:** `py -3.12 manage.py test` (full interpreter path; bare `python` lacks
Django). Baseline 790 tests, 3 pre-existing dev-login/home-redirect failures, 0
errors.

**THE TRAP — `scheduling.tests.make_session` cannot be called twice in one test.**
`scheduling/tests.py:180-201`. Every identifier is hardcoded, so a second call in
the same transaction violates four UNIQUE constraints:

```python
fac  = User.objects.create(username="fac_dt", email="fac_dt@mcm.edu.ph", ...)
bldg = Building.objects.create(name="R", code="R")          # Building.code unique
floor= Floor.objects.create(building=bldg, number=3)         # unique (building, number)
room = Room.objects.create(floor=floor, code="R399",
                           qr_token="tok-dt-399", manual_code="900399")
```

Collides on `username`, `Building.code="R"`, `Room.code`, `qr_token`,
`manual_code`. It also mints its own `AcademicTerm` marked `is_active=True`, so
two calls give you two "active" terms — which would corrupt any ladder derivation
under test. **Do not use `make_session` for room-aggregate tests.**

**Use the prefix-namespaced fixture instead** —
`scheduling/test_support.py:264` `make_reporting_fixture(prefix="rpt")`, whose
docstring (L266-268) states it "mirrors make_shift_fixture's `_aware` +
prefix-namespacing idiom so two calls in one test never collide on a UNIQUE
constraint." It seeds one active term, two departments, and one session of every
reporting-relevant shape (`s_absent`, `s_early`, `s_online`, `s_completed`, ...)
inside the known Mon-Sun week beginning `IN_WINDOW_DATE` (2026-07-06, a Monday),
with a documented totals contract (scheduled 8, held 6, absent 1, early_ends 1,
pct 75) and an `add_session(faculty, date, status, **kwargs)` escape hatch.

**Gap the planner must close:** `make_reporting_fixture` is faculty-shaped. It has
no virtual (`V`-prefixed) room, no multi-building/multi-floor spread, and no
`actual_start`/`actual_end` variety. Room-utilization tests need those, so the
plan should either extend the fixture (prefix-namespaced, additively — do not
change its documented faculty totals, `tests_reporting.py` asserts them) or add a
`make_room_utilization_fixture(prefix=...)` beside it in the same idiom. Follow
its `_aware` + prefix pattern either way.

**Assertions the tests must carry, from the decisions:**
- ABSENT contributes booked hours and ZERO used hours (D-03).
- `ended_early` contributes `actual_end - actual_start`, remainder reclaimed (D-03).
- A V-prefixed room never appears in a denominator or a grid cell (D-04).
- The ladder length is derived, not 11 — assert against the fixture's own slot count.
- `safe_card` isolation: a raising utilization aggregate returns
  `(None, message)` and the sibling cards still render (mirror `CardIsolationTests`).

---

## Shared Patterns

### Per-card isolation (mandatory, D-05)
**Source:** `scheduling/reporting.py:272-287`
**Apply to:** every new aggregate call in `web/ifo.py`, every new template section.
Wrapper returns `(value, error)`; view passes the tuple through; template checks
`.1` before `.0`. Guard `paginate(request, x[0] or [])`.

### Local-date filtering, never UTC scheduled_start
**Source:** `scheduling/reporting.py:20-23` (rule), `:113-114` (implementation)
**Apply to:** every room aggregate. Filter on `Session.date`; compute durations on
the UTC datetimes. Never filter on `scheduled_start`.

### DB-side conditional aggregation
**Source:** `scheduling/reporting.py:173-182`
**Apply to:** every room aggregate. One `GROUP BY` with `Count(filter=Q(...))`,
never a Python loop over a large queryset. Second relation -> second grouped
query, merged by key in Python.

### MSSQL discipline
**Source:** `scheduling/reporting.py:22-23` + CONTEXT
**Apply to:** all aggregate code. Never a large PK `IN` list (2100-param limit,
broke `reset_term`); materialize with `list()` before follow-up queries inside
`.iterator()` (HY010).

### Physical-rooms-only expression
**Source:** `scheduling/management/commands/seed_term.py:253-255`
**Apply to:** every denominator, every grid population, every rollup.
`exclude(code__startswith="V")` / `exclude(room__code__startswith="V")`.
`is_virtual` is a property and is unusable in a queryset.

### Never colour alone
**Source:** `templates/ifo/room_detail.html:89`, `templates/ifo/_cards.html:66`
**Apply to:** every heat cell and every KPI pill. Pair colour with a visible value
or an `sr-only` label. Heat scale must be WCAG-AA.

### Range parse + graceful degradation
**Source:** `web/reporting_common.py` `reporting_range`
**Apply to:** every new utilization view. 4-tuple unpack; always put
`date_from`/`date_to`/`range_note` in context; pass `as_of` to every aggregate.

---

## No Analog Found

| Concern | Role | Data Flow | Reason |
|---|---|---|---|
| Duration/`Sum(F(...) - F(...))` arithmetic in an aggregate | service | transform | `scheduling/reporting.py` is entirely `Count`-based; there is no precedent for summing a `DateTimeField` difference on MSSQL. This is the phase's one genuinely novel construct — the plan should verify the SQL Server translation early and keep the Python-side fallback (sum components in SQL, divide in Python, per the `_pct` precedent). |
| A campus-wide, Session-based day x block grid | service | transform | `room_timetable` is per-room and Schedule-based (bookings). The ladder is reusable; the aggregation is net-new. |
| Heat-intensity colour scale | config/style | n/a | `timetable.css` has one binary on/off state (`.tt__on`). No multi-step scale exists; extend that vocabulary rather than inventing a second one. |

## Metadata

**Analog search scope:** `scheduling/`, `web/`, `campus/`, `templates/ifo/`,
`static/css/`
**Files read:** 14
**Pattern extraction date:** 2026-07-19
