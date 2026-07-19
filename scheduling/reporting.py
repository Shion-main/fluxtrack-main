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
