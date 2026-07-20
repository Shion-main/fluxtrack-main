"""Pure reporting aggregates (RPT-01 / RPT-04 / RPT-05).

The single shared, side-effect-free aggregate layer every Phase-6 surface (the
weekly consolidated report, the faculty scorecard, IFO-09, the Dean dashboard,
and the HR views) computes from. It mirrors the ``scheduling/resolver.py`` purity
discipline: read-only, deterministic given inputs + DB state, NO writes, NO
``notify()``, NO ``timezone.now()`` baked in (the date range and ``as_of`` are
passed as arguments). "Pure" here means side-effect-free -- these functions DO
touch the ORM because attendance is fundamentally a DB count.

Truth reuse (RPT-01, the milestone's central rule): held/absent are read from the
existing ``Session.status`` truth (ABSENT set by the JOB-02 sweep / scan,
ACTIVE/COMPLETED = held) and never re-derived from timestamps. The checker-verified
count is computed by a SEPARATE grouped query over the ``validations`` reverse
relation so a same-query multi-join can never inflate the status counts; a
merge-filled MERGED sibling has NO CheckerValidation (04.2 D-09) and so stays held
but unverified.

MSSQL discipline: DB-side conditional aggregation (``Count(filter=Q(...))`` in one
``GROUP BY``), never a Python loop over a large queryset; filtering on the local
``Session.date`` DateField (never the UTC ``scheduled_start``) so weekly boundaries
carry no Asia/Manila drift; never a large primary-key ``IN`` list (the 2100-param
limit that broke ``reset_term``).
"""
import datetime
import logging
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Case, CharField, Count, F, Q, When

from campus.models import Room
from scheduling.models import (
    DayOfWeek,
    Schedule,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from verification.models import ValidationAction

logger = logging.getLogger(__name__)

# Phase-2/3 truth: a session is "held" when it is checked-in (ACTIVE) or finished
# (COMPLETED). ABSENT is the sweep/scan's authoritative no-show. Reference this
# constant everywhere -- never a bare status string (CONVENTIONS #Types).
HELD_STATUSES = (SessionStatus.ACTIVE, SessionStatus.COMPLETED)


@dataclass
class AbsenceItem:
    """One itemized ABSENT session for a faculty row (RPT-01)."""
    course_code: str
    section: str
    date: object  # datetime.date


@dataclass
class FacultyRow:
    """One faculty's consolidated attendance over a range (RPT-01)."""
    faculty_id: int
    name: str
    scheduled: int
    held: int
    absent: int
    verified: int
    attendance_pct: int
    early_ends: int
    absences: list = field(default_factory=list)


@dataclass
class DeptSummary:
    """Department-wide totals over a range (RPT-01 / DEAN-04 / IFO-09 cards)."""
    faculty_count: int
    scheduled: int
    held: int
    absent: int
    attendance_pct: int


@dataclass
class Scorecard:
    """One faculty's scorecard slice with early-ends + modality breakdown (RPT-04)."""
    faculty_id: int
    name: str
    scheduled: int
    held: int
    absent: int
    attendance_pct: int
    early_ends: int
    absences: list = field(default_factory=list)
    modality_breakdown: dict = field(default_factory=dict)


@dataclass
class RoomUtilization:
    """Campus-wide room-hours over a range (IFO-09, tier T1).

    The metric FluxTrack's "and Facility Utilization" half was missing. BOOKED is
    what the timetable promised; USED is what the check-in/out timestamps prove
    (D-03); the difference is reclaimable capacity a facilities office can act on,
    not a scolding statistic. Hours are ``Decimal`` quantized to one decimal place
    so a room-hours figure never renders as a binary-float artifact.

    Three shape fields describe the derived denominator (D-10):

    * ``physical_rooms`` -- the non-virtual room count.
    * ``blocks_per_day`` -- the CAMPUS ladder height (``len(campus_block_ladder)``),
      i.e. how many distinct start times the whole term uses. It is the grid's
      height, NOT a per-day block count: under D-10 the number of blocks actually
      timetabled varies by day, which is the entire point of the cell sum.
    * ``teaching_days`` -- calendar days in the range carrying at least one
      timetabled cell (the honest "days with teaching on them").
    * ``timetabled_cells`` -- (day, block) cells summed across the range, the true
      unit of the denominator. Under the old cross-product this was always
      ``teaching_days * blocks_per_day``; under D-10 it is <= that.
    """
    physical_rooms: int
    blocks_per_day: int
    teaching_days: int
    timetabled_cells: int
    available_hours: Decimal
    booked_hours: Decimal
    used_hours: Decimal
    wasted_hours: Decimal
    absent_hours: Decimal
    unused_held_hours: Decimal
    utilization_pct: int
    booking_pct: int
    in_flight: int
    early_end_sessions: int
    absent_sessions: int
    overrun_sessions: int
    early_arrival_sessions: int


def _physical_rooms():
    """Physical rooms only (D-04/D-08): the utilization denominator's population.

    ``Room.is_virtual`` is a PROPERTY over ``Room.code`` (``campus/models.py:44-54``),
    not a column, so it cannot appear in ``filter()``/``Q()``/``Count(filter=...)``.
    The in-production idiom is the code-prefix exclusion (``seed_term.py:253-255``).
    ``Room.code`` carries the DB-wide case-INSENSITIVE collation (only ``qr_token``
    and ``manual_code`` are CS_AS), so the uppercase prefix already matches a
    lowercase ``v``; do NOT reach for ``istartswith``, which would diverge from the
    two existing call sites for no behavioural gain.

    Out-of-service rooms (Phase 10, A7) are excluded too: a room closed for
    renovation has no capacity to use, so leaving it in the denominator would
    render the campus permanently under-utilized for a reason that is not waste.
    """
    return Room.objects.exclude(code__startswith="V").filter(out_of_service=False)


def _exclude_virtual(qs):
    """Drop sessions held in a virtual room from a Session queryset (D-04/D-08).

    Same reasoning as :func:`_physical_rooms`, spanning the ``Session.room`` FK: an
    online class in a V-room occupies no physical capacity, so counting it would
    dilute the rate with rooms that do not exist.
    """
    return qs.exclude(room__code__startswith="V")


def _pct(held, scheduled):
    """Attendance percentage, guarded against a zero denominator (pure arithmetic).

    Computed in Python from the returned ints to avoid MSSQL integer-division
    surprises. Uses explicit ROUND_HALF_UP (Decimal) rather than Python's built-in
    round-half-to-even so an exact .5 tie rounds the conventionally-expected way
    (e.g. 12.5 -> 13, not 12): a stakeholder computing the % by hand never sees an
    off-by-one at a tie (code-review LO-02). Decimal division of the two ints is
    exact input to quantize, avoiding binary-float artifacts.
    """
    if not scheduled:
        return 0
    return int((Decimal(100 * held) / Decimal(scheduled)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def _hours_pct(used_seconds, available_seconds):
    """Utilization percentage over two second-counts, zero-denominator guarded.

    The room-hours sibling of :func:`_pct`; the Decimal / ROUND_HALF_UP reasoning in
    that docstring applies verbatim and is not restated here. Returns 0 (never
    raises) for a zero or negative denominator -- a term with no ACTIVE schedules
    has no capacity, which is a legitimate answer and not an error.
    """
    if not available_seconds or available_seconds <= 0:
        return 0
    return int((Decimal(100 * used_seconds) / Decimal(available_seconds)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def _hours(seconds):
    """Seconds as Decimal hours, quantized to one decimal place (ROUND_HALF_UP)."""
    return (Decimal(seconds) / Decimal(3600)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CampusBlock:
    """One rung of the campus-wide block ladder (D-06).

    The ladder is DATA-DERIVED: one block per distinct ACTIVE ``Schedule.start_time``
    in the term, so its length is whatever the imported timetable contains and
    changes with the data. Nothing in this module may hardcode a block count.

    ``start`` is a wall-clock ``datetime.time`` (a TimeField, not an instant);
    ``duration_seconds`` is the block's representative length in seconds.
    """
    start: datetime.time
    duration_seconds: int


@dataclass(frozen=True)
class TimetabledCell:
    """One (day, block) cell the term actually timetables (D-10).

    The unit of the available-capacity denominator: each cell contributes
    ``physical_rooms x duration_seconds`` once per calendar occurrence of its day.

    ``day`` is a ``DayOfWeek`` value (MON=0..SUN=6, byte-identical to
    ``datetime.date.weekday()``); ``start`` is the ladder rung's wall-clock start;
    ``duration_seconds`` is that rung's ladder duration, so a cell can never
    disagree with the block ladder about how long a slot is.
    """
    day: int
    start: datetime.time
    duration_seconds: int


# An arbitrary fixed date used only to subtract two wall-clock TimeFields. These
# are not instants, so no timezone is involved and the date choice is irrelevant.
_SPAN_EPOCH = datetime.date(2000, 1, 1)


def _span_seconds(start_time, end_time):
    """Whole seconds between two wall-clock ``datetime.time`` values.

    Combines both against a fixed arbitrary date so the subtraction is pure
    wall-clock arithmetic with no timezone semantics. Floored at 0: a campus block
    never crosses midnight, so a negative span is bad data and must not subtract
    capacity from the denominator.
    """
    delta = (datetime.datetime.combine(_SPAN_EPOCH, end_time)
             - datetime.datetime.combine(_SPAN_EPOCH, start_time))
    return max(0, int(delta.total_seconds()))


def _block_duration_seconds(spans):
    """Pick one representative duration for a block from its (start, end) spans.

    The modal span wins, so one mis-imported outlier cannot stretch or shrink a
    block. A frequency tie resolves to the LONGEST span, so a block is never
    undercounted -- an understated block would understate available_hours and
    silently inflate the utilization rate.
    """
    durations = [_span_seconds(s, e) for s, e in spans]
    if not durations:
        return 0
    counts = Counter(durations)
    top = max(counts.values())
    return max(d for d, n in counts.items() if n == top)


def _active_schedules(term):
    """The term's ACTIVE schedules -- the one population the ladder is derived from."""
    return Schedule.objects.filter(term=term, status=ScheduleStatus.ACTIVE)


def campus_block_ladder(term):
    """The campus-wide block ladder for ``term``, or None (D-06).

    Returns ``None`` for a None term and ``None`` when the term has no ACTIVE
    schedules, mirroring ``web.room_state.room_timetable``'s two None-returns --
    both callers already handle that and a None ladder is a legitimate
    zero-denominator, not an error.

    Otherwise returns a list of :class:`CampusBlock` ordered by start time, one
    entry per distinct ACTIVE ``Schedule.start_time`` in the term. This is the
    SINGLE derivation: the printed room timetable and every room aggregate in this
    phase read it, so the dashboard and the paper grid cannot disagree about what
    a slot is.
    """
    if term is None:
        return None
    spans_by_start = {}
    for start_time, end_time in _active_schedules(term).values_list(
            "start_time", "end_time").iterator():
        spans_by_start.setdefault(start_time, []).append((start_time, end_time))
    if not spans_by_start:
        return None
    return [
        CampusBlock(start=start, duration_seconds=_block_duration_seconds(spans))
        for start, spans in sorted(spans_by_start.items())
    ]


def timetabled_cells(term):
    """The (day, block) cells the term actually timetables, campus-wide (D-10).

    Returns ``[]`` for a None term or a term with no ACTIVE schedules. Otherwise a
    list of :class:`TimetabledCell` ordered by (day, start): one entry per distinct
    ``(day_of_week, start_time)`` pair among the term's ACTIVE schedules, campus-wide,
    carrying that block's ladder duration.

    This REPLACES the former ``teaching_weekdays`` day-list, and with it the
    ``days x blocks`` cross-product denominator. The cross-product let a single
    outlier row buy a full day of capacity across every block: the seeded term's
    lone Sunday class promoted Sunday to a whole teaching day and moved campus
    utilization by four points. Summing the cells that are really timetabled is
    D-01's own rationale one level finer -- a block nobody schedules is not waste,
    and neither is a (day, block) cell nobody schedules -- and stays entirely
    derived, with no threshold and no hardcoded day list to decide the question.

    A cell is claimed by the block a schedule STARTS in, matching how the ladder
    itself is derived (one rung per distinct start time). A long class therefore
    claims one cell, not every rung its window crosses; the campus-wide union
    across all rooms is what makes the cell a real teaching slot.

    ``DayOfWeek`` is MON=0..SUN=6 (``scheduling/models.py:12-19``), byte-identical
    to ``datetime.date.weekday()``, so ``cell.day`` compares directly against a
    date's weekday with no translation table (asserted in ``WeekdayMappingTests``,
    not merely assumed here).

    Shaped as a cell SET rather than a day list because the plan-04 heat grid wants
    exactly this: which (day, block) cells exist, and how long each one is.
    """
    blocks = campus_block_ladder(term)
    if not blocks:
        return []
    duration_by_start = {b.start: b.duration_seconds for b in blocks}
    pairs = set(_active_schedules(term).values_list("day_of_week", "start_time"))
    return [
        TimetabledCell(day=day, start=start,
                       duration_seconds=duration_by_start.get(start, 0))
        for day, start in sorted(pairs)
    ]


def _scoped_sessions(*, start, end, department=None, as_of=None, faculty=None):
    """The shared session queryset every aggregate slices.

    Filters on the local ``Session.date`` DateField (no UTC ``scheduled_start``
    drift), restricts to ACTIVE schedules (archived-schedule sessions are not real
    obligations, assumption A5), optionally scopes to a Department or a single
    faculty, and optionally clamps the denominator to ``date <= as_of`` so a future
    not-yet-missed session does not lower attendance %.
    """
    qs = Session.objects.filter(
        date__range=(start, end), schedule__status=ScheduleStatus.ACTIVE,
    )
    if department is not None:
        qs = qs.filter(faculty__department=department)
    if faculty is not None:
        qs = qs.filter(faculty=faculty)
    if as_of is not None:
        qs = qs.filter(date__lte=as_of)
    return qs


def _name(first, last):
    return f"{first} {last}".strip()


def _verified_map(qs):
    """Per-faculty count of DISTINCT sessions with a 'verified' validation.

    A SEPARATE grouped query (not a same-query multi-join) so the reverse-join row
    multiplication can never inflate the status counts. Merge-filled MERGED siblings
    have no CheckerValidation, so they are absent here (honest verified count).
    """
    verified = (
        qs.filter(validations__action=ValidationAction.VERIFIED)
        .values("faculty_id")
        .annotate(n=Count("id", distinct=True))
    )
    return {r["faculty_id"]: r["n"] for r in verified}


def _absence_map(qs):
    """Per-faculty list of itemized AbsenceItem for ABSENT sessions in range."""
    out = {}
    absent = (
        qs.filter(status=SessionStatus.ABSENT)
        .values("faculty_id", "schedule__course_code", "schedule__section", "date")
        .order_by("date")
    )
    for r in absent:
        out.setdefault(r["faculty_id"], []).append(
            AbsenceItem(
                course_code=r["schedule__course_code"],
                section=r["schedule__section"],
                date=r["date"],
            )
        )
    return out


def faculty_attendance(*, start, end, department=None, as_of=None):
    """RPT-01: one FacultyRow per faculty over [start, end] on ``Session.date``.

    ``department=None`` aggregates all departments (IFO-09); a Department scopes to
    ``faculty__department`` (DEAN / RPT). Reads the ``Session.status`` truth via one
    grouped conditional-aggregation query; the verified count comes from a separate
    grouped query (``_verified_map``) so it never inflates the status counts.
    """
    qs = _scoped_sessions(start=start, end=end, department=department, as_of=as_of)

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

    verified_by_faculty = _verified_map(qs)
    absences_by_faculty = _absence_map(qs)

    rows = []
    for r in status_rows:
        fid = r["faculty_id"]
        rows.append(
            FacultyRow(
                faculty_id=fid,
                name=_name(r["faculty__first_name"], r["faculty__last_name"]),
                scheduled=r["scheduled"],
                held=r["held"],
                absent=r["absent"],
                verified=verified_by_faculty.get(fid, 0),
                attendance_pct=_pct(r["held"], r["scheduled"]),
                early_ends=r["early_ends"],
                absences=absences_by_faculty.get(fid, []),
            )
        )
    return rows


def dept_summary(*, start, end, department=None, as_of=None):
    """RPT-01 / DEAN-04: department-wide totals + distinct faculty_count."""
    qs = _scoped_sessions(start=start, end=end, department=department, as_of=as_of)
    agg = qs.aggregate(
        scheduled=Count("id"),
        held=Count("id", filter=Q(status__in=HELD_STATUSES)),
        absent=Count("id", filter=Q(status=SessionStatus.ABSENT)),
        faculty_count=Count("faculty_id", distinct=True),
    )
    return DeptSummary(
        faculty_count=agg["faculty_count"] or 0,
        scheduled=agg["scheduled"] or 0,
        held=agg["held"] or 0,
        absent=agg["absent"] or 0,
        attendance_pct=_pct(agg["held"] or 0, agg["scheduled"] or 0),
    )


def faculty_scorecard(*, faculty, start, end, as_of=None):
    """RPT-04: a single faculty's scorecard slice of the same aggregate.

    Adds ``early_ends`` (count of ``ended_early`` sessions) and a
    ``modality_breakdown`` mapping the EFFECTIVE modality (declared_modality wins
    over schedule.modality -- honors approved shifts, Pitfall 5) to a held count.
    A faculty with no sessions in range returns a zeroed Scorecard (no crash).
    """
    qs = _scoped_sessions(start=start, end=end, as_of=as_of, faculty=faculty)

    agg = qs.aggregate(
        scheduled=Count("id"),
        held=Count("id", filter=Q(status__in=HELD_STATUSES)),
        absent=Count("id", filter=Q(status=SessionStatus.ABSENT)),
        early_ends=Count("id", filter=Q(ended_early=True)),
    )

    # Effective-modality breakdown over HELD sessions only: declared_modality
    # overrides the schedule default (a Dean-approved shift to Online counts Online).
    breakdown_rows = (
        qs.filter(status__in=HELD_STATUSES)
        .annotate(
            effective_modality=Case(
                When(declared_modality="", then=F("schedule__modality")),
                default=F("declared_modality"),
                output_field=CharField(),
            )
        )
        .values("effective_modality")
        .annotate(n=Count("id"))
    )
    modality_breakdown = {r["effective_modality"]: r["n"] for r in breakdown_rows}

    absences = _absence_map(qs).get(faculty.id, [])

    return Scorecard(
        faculty_id=faculty.id,
        name=_name(faculty.first_name, faculty.last_name),
        scheduled=agg["scheduled"] or 0,
        held=agg["held"] or 0,
        absent=agg["absent"] or 0,
        attendance_pct=_pct(agg["held"] or 0, agg["scheduled"] or 0),
        early_ends=agg["early_ends"] or 0,
        absences=absences,
        modality_breakdown=modality_breakdown,
    )


def _session_contribution(status, scheduled_start, scheduled_end,
                          actual_start, actual_end):
    """One session's ``(booked_seconds, used_seconds, in_flight)`` (D-03/D-09).

    THE single definition of "used" for this phase. Every room aggregate calls it
    rather than re-deriving the rules, because two implementations of "used" would
    eventually disagree and the whole point of the phase is one honest number.

    The rules, in evaluation order:

    * ``actual_start`` set, ``actual_end`` NULL, status ACTIVE -- the class is still
      running. EXCLUDED from booked AND used, reported as ``in_flight`` (D-09).
      Counting its booked hours against an incomplete numerator would fabricate
      waste that has not happened yet, and clamping to ``now`` is forbidden by this
      module's no-baked-in-``timezone.now()`` contract.
    * ``status = ABSENT`` -- booked, 0 used. This zero IS the waste signal (D-03).
    * ``actual_start`` NULL -- 0 used. Nobody ever checked in. A NULL is answered
      explicitly here, never folded into a silent zero.
    * ``actual_end`` NULL on a non-ACTIVE session -- 0 used. A finished session with
      no end stamp is not evidence of use.
    * otherwise -- ``min(actual_end, scheduled_end) - max(actual_start, scheduled_start)``,
      floored at 0.

    The used interval is CLAMPED to the scheduled window. D-03's early-end case is
    preserved exactly (``actual_end < scheduled_end`` there, so the clamp is a
    no-op); the clamp only bites on overrun or early arrival, which D-03 does not
    address. It is required because check-in can stamp ``actual_start`` before
    ``scheduled_start`` -- unclamped, a room could report more used hours than it
    had booked and the rate could exceed 100%, which is meaningless for a capacity
    metric. Where the clamp bites, ``room_utilization`` counts it
    (``overrun_sessions`` / ``early_arrival_sessions``) so the discarded time stays
    visible rather than silently vanishing.
    """
    # Phase 9 (A1): a CANCELLED (suspended/holiday) session never booked the room
    # in reality -- the class did not meet because classes were called off. Counting
    # its scheduled window as booked-but-unused would fabricate exactly the "wasted
    # hours" a suspension day did NOT cause, tanking the utilization rate on the
    # worst possible day. It contributes nothing: 0 booked, 0 used, not in-flight.
    if status == SessionStatus.CANCELLED:
        return 0, 0, False

    if actual_start is not None and actual_end is None \
            and status == SessionStatus.ACTIVE:
        return 0, 0, True

    booked = max(0, int((scheduled_end - scheduled_start).total_seconds()))

    if status == SessionStatus.ABSENT:
        return booked, 0, False
    if actual_start is None or actual_end is None:
        return booked, 0, False

    used_start = max(actual_start, scheduled_start)
    used_end = min(actual_end, scheduled_end)
    used = max(0, int((used_end - used_start).total_seconds()))
    return booked, used, False


@dataclass(frozen=True)
class RangeCellShape:
    """The D-10 denominator shape of one reporting window, per PHYSICAL ROOM.

    ``cell_seconds`` is the capacity ONE physical room has over the range -- the
    campus figure is this times the physical room count, and a floor's is this
    times that floor's room count. Every level of the phase's arithmetic is that
    one number scaled by a room count, which is what makes room, floor, building
    and campus reconcile by construction rather than by luck.
    """
    teaching_days: int
    cell_count: int
    cell_seconds: int


def _range_cell_shape(term, start, end, as_of=None):
    """Walk the calendar range and sum the (day, block) cells it really contains.

    D-10: a SUM over the cells the term actually timetables, NOT a days x blocks
    cross-product. Seconds are accumulated per weekday first and then multiplied
    out over the calendar days in range, so the arithmetic stays integral and a
    weekday appearing twice in a long range counts twice.

    THE single derivation of the denominator. ``room_utilization``,
    ``room_breakdown`` and ``building_floor_rollup`` all read it; two walks over
    the same calendar would eventually disagree about a range boundary.
    """
    seconds_by_weekday = {}
    cells_by_weekday = {}
    for cell in timetabled_cells(term):
        seconds_by_weekday[cell.day] = (
            seconds_by_weekday.get(cell.day, 0) + cell.duration_seconds)
        cells_by_weekday[cell.day] = cells_by_weekday.get(cell.day, 0) + 1

    last_day = min(end, as_of) if as_of is not None else end
    teaching_days = cell_count = cell_seconds = 0
    day = start
    while day <= last_day:
        weekday = day.weekday()
        if weekday in cells_by_weekday:
            teaching_days += 1
            cell_count += cells_by_weekday[weekday]
            cell_seconds += seconds_by_weekday[weekday]
        day += datetime.timedelta(days=1)
    return RangeCellShape(teaching_days=teaching_days, cell_count=cell_count,
                          cell_seconds=cell_seconds)


def room_utilization(*, start, end, term, as_of=None):
    """IFO-09 / T1: campus room-hours booked vs used vs available over a range.

    ``used`` comes from the ACTUAL check-in/out timestamps, never from the
    schedule: an ABSENT session contributes booked hours and ZERO used hours and
    that difference IS the reclaimable-capacity metric (D-03). The denominator is
    derived at query time from the term's own data as a SUM over the (day, block)
    cells the term actually timetables (D-10)::

        available = SUM over timetabled (day, block) cells in range of
                    (physical_rooms x block_duration)

    so no block count, day count or day list is ever hardcoded (D-06). The earlier
    ``days x blocks`` cross-product is deliberately gone: it let one outlier
    schedule row buy a whole day's worth of capacity across every block, which moved
    the headline rate by four points on the seeded term (D-10). In-flight sessions (running, no
    ``actual_end``) are excluded from both sides and surfaced in ``in_flight``
    rather than being folded into a silent zero (D-09).

    Filters on the LOCAL ``Session.date`` via ``_scoped_sessions`` (inheriting the
    ACTIVE-schedule restriction and the ``as_of`` clamp) and computes durations on
    the UTC datetimes. Virtual rooms are excluded from both sides (D-04).

    Never raises on an empty range or a term with no ACTIVE schedules: the
    denominator is simply zero and the rates read 0.
    """
    # --- Denominator: every factor derived, no literal block or day count. ---
    blocks = campus_block_ladder(term) or []
    physical_rooms = _physical_rooms().count()
    shape = _range_cell_shape(term, start, end, as_of=as_of)
    teaching_days = shape.teaching_days
    cell_count = shape.cell_count
    available_seconds = physical_rooms * shape.cell_seconds

    # --- Numerator: a streamed Python fold, deliberately, not DB-side. ---
    # This deviates from the module's DB-side-aggregation rule, so: the per-session
    # contribution is a conditional clamp over four NULLable datetimes, which
    # Count(filter=Q) cannot express and which Sum(F("actual_end") - F("actual_start"))
    # cannot clamp; DurationField subtraction is additionally unverified on
    # mssql-django and this module has no precedent for it. The hazards the rule
    # exists to prevent are all absent here -- .values_list() pulls six scalar
    # columns and instantiates no model, the row set is bounded by the reporting
    # window, and there is no per-row query and no primary-key IN list.
    qs = _exclude_virtual(_scoped_sessions(start=start, end=end, as_of=as_of))

    booked_seconds = used_seconds = absent_seconds = unused_held_seconds = 0
    in_flight = absent_sessions = early_end_sessions = 0
    overrun_sessions = early_arrival_sessions = 0

    rows = qs.values_list(
        "status", "scheduled_start", "scheduled_end",
        "actual_start", "actual_end", "ended_early",
    ).iterator()
    for status, sched_start, sched_end, act_start, act_end, ended_early in rows:
        booked, used, running = _session_contribution(
            status, sched_start, sched_end, act_start, act_end)
        if running:
            in_flight += 1
            continue
        booked_seconds += booked
        used_seconds += used
        if status == SessionStatus.ABSENT:
            absent_seconds += booked
            absent_sessions += 1
        elif status in HELD_STATUSES:
            unused_held_seconds += max(0, booked - used)
        if ended_early:
            early_end_sessions += 1
        # Make the clamp visible: a room routinely used past its booking is a
        # scheduling-conflict signal a facilities office wants, and silently
        # discarding it is the same class of mistake this phase exists to correct.
        if act_end is not None and act_end > sched_end:
            overrun_sessions += 1
        if act_start is not None and act_start < sched_start:
            early_arrival_sessions += 1

    wasted_seconds = absent_seconds + unused_held_seconds

    return RoomUtilization(
        physical_rooms=physical_rooms,
        blocks_per_day=len(blocks),
        teaching_days=teaching_days,
        timetabled_cells=cell_count,
        available_hours=_hours(available_seconds),
        booked_hours=_hours(booked_seconds),
        used_hours=_hours(used_seconds),
        wasted_hours=_hours(wasted_seconds),
        absent_hours=_hours(absent_seconds),
        unused_held_hours=_hours(unused_held_seconds),
        utilization_pct=_hours_pct(used_seconds, available_seconds),
        booking_pct=_hours_pct(booked_seconds, available_seconds),
        in_flight=in_flight,
        early_end_sessions=early_end_sessions,
        absent_sessions=absent_sessions,
        overrun_sessions=overrun_sessions,
        early_arrival_sessions=early_arrival_sessions,
    )


@dataclass
class HeatCell:
    """One (day, block) cell of the campus utilization grid (IFO-09, tier T2).

    ``timetabled`` is the D-10 distinction and is NOT cosmetic: a cell the term
    never timetables has NO capacity, which is a different fact from a cell that
    has capacity and went unused. Conflating the two is the exact mistake D-10
    exists to correct, so the renderer must show a "not timetabled" state for
    ``timetabled=False`` rather than a misleading 0%.

    ``room_count`` is the number of DISTINCT physical rooms that actually hosted a
    session in this cell -- the occupancy width of the slot, against the
    ``physical_rooms`` denominator.
    """
    day: int
    used_hours: Decimal
    booked_hours: Decimal
    available_hours: Decimal
    utilization_pct: int
    session_count: int
    room_count: int
    timetabled: bool


@dataclass
class HeatRow:
    """One ladder rung of the heat grid: a block and its cells, one per DayOfWeek."""
    block: CampusBlock
    cells: list = field(default_factory=list)


@dataclass
class BlockLoad:
    """One block's campus-wide load over the range, for the saturation ranking."""
    block: CampusBlock
    used_hours: Decimal
    booked_hours: Decimal
    available_hours: Decimal
    utilization_pct: int
    session_count: int
    peak_day: object = None      # DayOfWeek value, or None when wholly unused


def _weekday_occurrences(start, end, as_of=None):
    """{weekday: how many times it falls in the range}, by walking the dates.

    Walked rather than divided: an arbitrary range does NOT contain equal numbers
    of each weekday, so ``span // 7`` would silently misprice every cell whose
    weekday happens to fall on the ragged edge of the window.
    """
    last_day = min(end, as_of) if as_of is not None else end
    counts = {}
    day = start
    while day <= last_day:
        counts[day.weekday()] = counts.get(day.weekday(), 0) + 1
        day += datetime.timedelta(days=1)
    return counts


def _distribute(total, weights):
    """Split ``total`` across ``weights`` proportionally, losing nothing.

    Integer floor per part with the remainder handed to the last part, so the
    parts sum EXACTLY to ``total``. That exactness is what makes the grid
    reconcile with :func:`room_utilization` instead of drifting by a few seconds
    per multi-block session.
    """
    n = len(weights)
    if n == 0:
        return []
    if n == 1:
        return [total]
    span = sum(weights) or 1
    parts = [total * w // span for w in weights]
    parts[-1] += total - sum(parts)
    return parts


def room_heat_grid(*, start, end, term, as_of=None):
    """IFO-09 / T2: a day-by-block grid of campus room utilization.

    Answers WHERE and WHEN capacity is idle, which is what makes T1's single
    percentage actionable: a facilities office cannot reclaim "142 room-hours", it
    can reclaim "Tuesday 4:00 PM, which runs at 18%".

    Cells aggregate **Sessions**, never Schedules (D-03). ``web.room_state.room_timetable``
    was deliberately NOT reused: it is per-room and Schedule-based, so its cells are
    BOOKINGS, and a booking count is precisely the mistake this phase exists to
    correct. What IS shared with the printed timetable is the derived ladder
    (:func:`campus_block_ladder`), so the two grids can never disagree about what a
    slot is. Do not "simplify" this onto ``room_timetable``.

    Returns ``None`` when the ladder is None (no term, or a term with no ACTIVE
    schedules), matching the ladder's own contract and ``room_timetable``'s -- every
    caller already handles a None ladder, so this adds no new burden.

    Otherwise: one :class:`HeatRow` per ladder rung, each carrying one
    :class:`HeatCell` per ``DayOfWeek`` in ``DayOfWeek.choices`` order.

    **Reconciliation property.** A session spanning two blocks is distributed
    across them PROPORTIONALLY to block duration, not replicated into each, so the
    grid's summed used hours equal ``room_utilization(...).used_hours`` over the
    same window (up to per-cell Decimal quantization). Plan 06 renders the T1 card
    and this grid on one page; without that property the two would visibly
    disagree and a reader would have no way to tell which was lying.

    **Denominator (D-10).** A cell has capacity only if the term actually
    timetables that (day, block) pair. A cell that is not timetabled carries zero
    available hours and ``timetabled=False``; it is NOT the same thing as an idle
    slot and must not render as 0%.
    """
    blocks = campus_block_ladder(term)
    if not blocks:
        return None

    cells = timetabled_cells(term)
    timetabled_pairs = {(c.day, c.start) for c in cells}
    occurrences = _weekday_occurrences(start, end, as_of=as_of)
    physical_rooms = _physical_rooms().count()
    days = [int(value) for value, _label in DayOfWeek.choices]
    block_index = {b.start: i for i, b in enumerate(blocks)}

    # Accumulators keyed (block_index, day). Room ids are held in a set bounded by
    # the physical room count -- never turned into a pk__in query (MSSQL 2100).
    used = {}
    booked = {}
    sessions = {}
    rooms_seen = {}

    qs = _exclude_virtual(_scoped_sessions(start=start, end=end, as_of=as_of))
    rows = qs.values_list(
        "schedule__day_of_week", "schedule__start_time", "schedule__end_time",
        "room_id", "status", "scheduled_start", "scheduled_end",
        "actual_start", "actual_end",
    ).iterator()
    for (day, sched_start_t, sched_end_t, room_id, status,
         sched_start, sched_end, act_start, act_end) in rows:
        booked_s, used_s, running = _session_contribution(
            status, sched_start, sched_end, act_start, act_end)
        if running:
            continue
        # Half-open occupancy, mirroring web/room_state.py:131: a session occupies
        # every rung whose start falls inside its wall-clock window. That is what
        # makes a double-length class fill two rows with no rowspan bookkeeping.
        occupied = [
            b for b in blocks
            if sched_start_t <= b.start < sched_end_t
        ]
        if not occupied:
            continue
        weights = [b.duration_seconds or 1 for b in occupied]
        for b, part_booked, part_used in zip(
                occupied, _distribute(booked_s, weights),
                _distribute(used_s, weights)):
            key = (block_index[b.start], day)
            booked[key] = booked.get(key, 0) + part_booked
            used[key] = used.get(key, 0) + part_used
            sessions[key] = sessions.get(key, 0) + 1
            rooms_seen.setdefault(key, set()).add(room_id)

    grid = []
    for i, block in enumerate(blocks):
        row_cells = []
        for day in days:
            key = (i, day)
            is_timetabled = (day, block.start) in timetabled_pairs
            available_s = (
                physical_rooms * occurrences.get(day, 0) * block.duration_seconds
                if is_timetabled else 0
            )
            used_s = used.get(key, 0)
            row_cells.append(HeatCell(
                day=day,
                used_hours=_hours(used_s),
                booked_hours=_hours(booked.get(key, 0)),
                available_hours=_hours(available_s),
                utilization_pct=_hours_pct(used_s, available_s),
                session_count=sessions.get(key, 0),
                room_count=len(rooms_seen.get(key, ())),
                timetabled=is_timetabled,
            ))
        grid.append(HeatRow(block=block, cells=row_cells))
    return grid


def block_saturation(*, start, end, term, as_of=None):
    """IFO-09 / T2: the ladder ranked by utilization, most-saturated first.

    The same data as :func:`room_heat_grid`, reduced along the day axis. It is
    derived FROM that grid rather than re-queried, deliberately: two independent
    queries computing the same figure will drift, and the grid's reconciliation
    property is what lets one page show a grid and a ranking that agree.

    Returns ``[]`` -- not None -- when the ladder is None. Plan 06 renders this as
    a table, and an empty table is a truthful empty state, whereas a None forces
    every caller into a branch that has nothing useful to say.

    Ordered by ``utilization_pct`` DESCENDING, then by block start ascending, so
    ties are stable: a table whose row order changes between two identical
    requests reads as a bug.
    """
    grid = room_heat_grid(start=start, end=end, term=term, as_of=as_of)
    if not grid:
        return []

    loads = []
    for row in grid:
        used = sum((c.used_hours for c in row.cells), Decimal("0"))
        booked = sum((c.booked_hours for c in row.cells), Decimal("0"))
        available = sum((c.available_hours for c in row.cells), Decimal("0"))
        busiest = max(row.cells, key=lambda c: c.used_hours)
        loads.append(BlockLoad(
            block=row.block,
            used_hours=used,
            booked_hours=booked,
            available_hours=available,
            utilization_pct=_hours_pct(used, available),
            session_count=sum(c.session_count for c in row.cells),
            peak_day=busiest.day if busiest.used_hours > 0 else None,
        ))
    loads.sort(key=lambda l: (-l.utilization_pct, l.block.start))
    return loads


@dataclass
class RoomLoad:
    """One physical room's utilization over the range (IFO-09, tier T2).

    ``capacity`` is carried because it is already on the model and costs nothing
    to render. NOTHING is computed from it: seat utilization (enrolled/capacity)
    is T3 and explicitly deferred, because ``Schedule.enrolled_count``
    trustworthiness across the imported term is unproven and a seat figure nobody
    can check is worse than no figure. Do not add a seat or enrolment field here
    without reopening that deferral.

    ``utilization_pct`` is deliberately NOT clamped at 100. A single room CAN
    exceed its own denominator, and when it does that is real information, not an
    arithmetic fault: it means the room is genuinely double-booked. The live term
    contains such rows -- ``R116`` hosts ``ECE121L 07:00-10:45`` straddling two
    lecture slots the same morning -- and clamping would silently hide exactly the
    scheduling conflict a facilities office most wants to see. Same reasoning as
    ``room_utilization``'s ``overrun_sessions``. The campus and scope levels stay
    below 100% because the conflicts are local; a SCOPE above 100% would be a bug.

    The three ``*_seconds`` fields are the unrounded truth the rollup reduces.
    Summing the ``Decimal`` hours across 125 rooms would accumulate up to 0.05 h
    of quantization error per room, and the building/floor/campus levels are
    supposed to reconcile EXACTLY.
    """
    room_id: int
    code: str
    name: str
    building_code: str
    building_name: str
    floor_number: int
    capacity: int
    used_hours: Decimal
    booked_hours: Decimal
    available_hours: Decimal
    wasted_hours: Decimal
    utilization_pct: int
    session_count: int
    absent_sessions: int
    used_seconds: int = 0
    booked_seconds: int = 0
    wasted_seconds: int = 0


@dataclass
class ScopeLoad:
    """One building or floor row of the rollup.

    A FLAT list with a ``level`` marker rather than a nested structure: the IFO
    table stack is a plain ``.tbl`` and nesting fights it, so the template walks
    one list and applies a single indent class where ``level == "floor"``.
    """
    level: str                 # "building" or "floor"
    label: str
    building_code: str
    floor_number: object       # None on a building row
    room_count: int
    used_hours: Decimal
    booked_hours: Decimal
    available_hours: Decimal
    wasted_hours: Decimal
    utilization_pct: int


def room_breakdown(*, start, end, term, as_of=None):
    """IFO-09 / T2: per-room utilization over the WHOLE physical room universe.

    Where the heat grid answers when capacity is idle, this answers where.

    Built from the ROOM side, not the session side (``_physical_rooms()`` first,
    session totals looked up onto it). Grouping the sessions would drop every room
    that hosted nothing -- and a never-used room is precisely the most useful row
    in a least-used ranking. Virtual rooms appear nowhere (D-04/D-08).

    Every physical room shares one denominator under D-01/D-10: the per-room cell
    seconds of the range, from :func:`_range_cell_shape`. It is one figure reused,
    never a per-room query.

    Used-hours come from :func:`_session_contribution`, the phase's single
    definition, so this cannot drift from the campus card or the heat grid.

    Ordered by ``utilization_pct`` ASCENDING then room code ascending, so the head
    of the list IS the least-used-rooms answer and two identical requests always
    produce the same order. The FULL set is returned; a caller wanting a top-N view
    takes a slice. An aggregate that truncated could not also serve a page that
    wants every row.
    """
    rooms = list(
        _physical_rooms()
        .select_related("floor__building")
        .order_by("floor__building__code", "floor__number", "code")
    )
    available_seconds = _range_cell_shape(
        term, start, end, as_of=as_of).cell_seconds

    used = {}
    booked = {}
    wasted = {}
    sessions = {}
    absents = {}

    qs = _exclude_virtual(_scoped_sessions(start=start, end=end, as_of=as_of))
    rows = qs.values_list(
        "room_id", "status", "scheduled_start", "scheduled_end",
        "actual_start", "actual_end",
    ).iterator()
    for room_id, status, sched_start, sched_end, act_start, act_end in rows:
        booked_s, used_s, running = _session_contribution(
            status, sched_start, sched_end, act_start, act_end)
        if running:
            continue
        booked[room_id] = booked.get(room_id, 0) + booked_s
        used[room_id] = used.get(room_id, 0) + used_s
        sessions[room_id] = sessions.get(room_id, 0) + 1
        if status == SessionStatus.ABSENT:
            absents[room_id] = absents.get(room_id, 0) + 1
            wasted[room_id] = wasted.get(room_id, 0) + booked_s
        elif status in HELD_STATUSES:
            wasted[room_id] = wasted.get(room_id, 0) + max(0, booked_s - used_s)

    loads = []
    for room in rooms:
        used_s = used.get(room.id, 0)
        booked_s = booked.get(room.id, 0)
        wasted_s = wasted.get(room.id, 0)
        loads.append(RoomLoad(
            room_id=room.id,
            code=room.code,
            name=room.name,
            building_code=room.floor.building.code,
            building_name=room.floor.building.name,
            floor_number=room.floor.number,
            capacity=room.capacity,
            used_hours=_hours(used_s),
            booked_hours=_hours(booked_s),
            available_hours=_hours(available_seconds),
            wasted_hours=_hours(wasted_s),
            utilization_pct=_hours_pct(used_s, available_seconds),
            session_count=sessions.get(room.id, 0),
            absent_sessions=absents.get(room.id, 0),
            used_seconds=used_s,
            booked_seconds=booked_s,
            wasted_seconds=wasted_s,
        ))
    loads.sort(key=lambda r: (r.utilization_pct, r.code))
    return loads


def building_floor_rollup(*, start, end, term, as_of=None):
    """IFO-09 / T2: the same rooms rolled up to floor and building level.

    Derived ENTIRELY by reducing :func:`room_breakdown`'s output. It is not
    re-queried, for two reasons: the module's separate-query rule exists because a
    multi-level reverse join multiplies rows, and reducing one derivation makes
    room, floor, building and campus reconcile by construction instead of by luck.

    Floor rows are keyed on the ``(building_code, floor_number)`` PAIR, matching
    ``Floor``'s own ``unique_together``. Keying on the number alone would merge
    every building's third floor into one row. Each floor row's label names its
    building, so a flat table reads correctly with no grouping header.

    A scope's available hours are its OWN room count times the shared per-room
    denominator -- not the campus denominator -- so a two-room floor is not judged
    against campus-wide capacity.

    Returns a FLAT list with a ``level`` marker: buildings by code ascending, each
    immediately followed by its floors by number ascending.
    """
    rooms = room_breakdown(start=start, end=end, term=term, as_of=as_of)
    per_room_seconds = (
        _range_cell_shape(term, start, end, as_of=as_of).cell_seconds)

    buildings = {}
    for room in rooms:
        b = buildings.setdefault(room.building_code, {
            "name": room.building_name, "rooms": 0,
            "used": 0, "booked": 0, "wasted": 0, "floors": {},
        })
        f = b["floors"].setdefault(room.floor_number, {
            "rooms": 0, "used": 0, "booked": 0, "wasted": 0,
        })
        for scope in (b, f):
            scope["rooms"] += 1
            scope["used"] += room.used_seconds
            scope["booked"] += room.booked_seconds
            scope["wasted"] += room.wasted_seconds

    def _row(level, label, code, floor_number, scope):
        available = scope["rooms"] * per_room_seconds
        return ScopeLoad(
            level=level,
            label=label,
            building_code=code,
            floor_number=floor_number,
            room_count=scope["rooms"],
            used_hours=_hours(scope["used"]),
            booked_hours=_hours(scope["booked"]),
            available_hours=_hours(available),
            wasted_hours=_hours(scope["wasted"]),
            utilization_pct=_hours_pct(scope["used"], available),
        )

    out = []
    for code in sorted(buildings):
        b = buildings[code]
        out.append(_row("building", b["name"] or code, code, None, b))
        for number in sorted(b["floors"]):
            out.append(_row(
                "floor", f"{code} floor {number}", code, number,
                b["floors"][number]))
    return out


def safe_card(fn, *args, **kwargs):
    """RPT-05 / T-06-04: per-card isolation wrapper.

    Returns ``(value, None)`` on success and ``(None, generic_message)`` on ANY
    exception, so one raising aggregate errors in its own card while the rest of the
    page renders. The real exception is logged server-side; the raw exception string
    NEVER reaches the template (information-disclosure V7, assumption A2 -- a read
    failure is not a domain state change, so no AuditLog).
    """
    try:
        return fn(*args, **kwargs), None
    except Exception:  # deliberately broad: per-card isolation is the point
        logger.exception(
            "Reporting card failed: %s", getattr(fn, "__name__", repr(fn))
        )
        return None, "This section could not be loaded."
