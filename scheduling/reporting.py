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
from scheduling.models import Schedule, ScheduleStatus, Session, SessionStatus
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
    """
    physical_rooms: int
    blocks_per_day: int
    teaching_days: int
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
    """
    return Room.objects.exclude(code__startswith="V")


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


def teaching_weekdays(term):
    """Sorted distinct ``day_of_week`` values of the term's ACTIVE schedules (D-06).

    Returns ``[]`` for a None term. ``DayOfWeek`` is MON=0..SUN=6
    (``scheduling/models.py:12-19``), byte-identical to ``datetime.date.weekday()``,
    so these values compare directly with no translation table (asserted in
    ``WeekdayMappingTests``, not merely assumed here).

    Deriving days from the data is what picks up MMCM's real Saturday classes and
    drops Sunday without anyone hardcoding a 5 or a 7: a day nobody schedules is
    not wasted capacity, it is simply not a teaching day.
    """
    if term is None:
        return []
    return sorted(set(
        _active_schedules(term).values_list("day_of_week", flat=True)))


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


def room_utilization(*, start, end, term, as_of=None):
    """IFO-09 / T1: campus room-hours booked vs used vs available over a range.

    ``used`` comes from the ACTUAL check-in/out timestamps, never from the
    schedule: an ABSENT session contributes booked hours and ZERO used hours and
    that difference IS the reclaimable-capacity metric (D-03). The denominator is
    derived at query time from the term's own data -- physical rooms x derived
    teaching days x the derived campus block ladder -- so no block count or
    teaching-day count is ever hardcoded (D-06). In-flight sessions (running, no
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
    weekdays = set(teaching_weekdays(term))
    block_seconds_per_day = sum(b.duration_seconds for b in blocks)
    physical_rooms = _physical_rooms().count()

    last_day = min(end, as_of) if as_of is not None else end
    teaching_days = 0
    day = start
    while day <= last_day:
        if day.weekday() in weekdays:
            teaching_days += 1
        day += datetime.timedelta(days=1)

    available_seconds = physical_rooms * teaching_days * block_seconds_per_day

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
