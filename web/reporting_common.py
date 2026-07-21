"""Shared reporting helpers for the role surfaces (web.ifo / web.dean / web.hr /
web.faculty).

The reporting-range parser was originally duplicated verbatim in ``web/ifo.py`` and
``web/dean.py`` (plus a third copy of ``_WEEKDAY_INDEX``). The logic is pure and
role-agnostic -- it reads only GET params + the ``reporting_week_start`` policy and
returns dates -- so there is no role-coupling reason to keep two copies in sync by
hand (code-review LO-03). This module owns the single implementation both role
views import. ``status_label`` was lifted here from ``web/hr.py`` for the same
reason when FAC-11 needed it: a second copy of the label map would let the faculty
history page and the HR payroll export describe the SAME session differently,
which is exactly the failure this module exists to prevent.
ASCII-only by convention (Windows cp1252).
"""
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Callable, Mapping
from urllib.parse import urlencode

from django.utils import timezone
from django.utils.dateparse import parse_date

from ops.policy import get_policy
from scheduling.models import AcademicTerm, SessionStatus
from scheduling.term_scope import get_active_term

# reporting_week_start policy value -> Python weekday() index (Mon=0 .. Sun=6).
_WEEKDAY_INDEX = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                  "friday": 4, "saturday": 5, "sunday": 6}


@dataclass(frozen=True)
class ReportScope:
    """One immutable, explicit management-report scope (D-09..D-12).

    ``term`` is deliberately optional only for the two named empty/error states.
    A valid scope always has a term, bounded dates, and normalized query values.
    ``term_choices`` is materialized as a tuple so templates cannot accidentally
    re-run or mutate a lazy queryset while rendering.
    """

    term: AcademicTerm | None
    term_choices: tuple[AcademicTerm, ...]
    start: date | None
    end: date | None
    as_of: date | None
    note: str | None
    error: str | None
    error_code: str | None
    query_params: Mapping[str, str]
    scope_query: str

    @property
    def is_valid(self):
        return self.error_code is None and self.term is not None


def _report_term_choices():
    """Return ACTIVE first, then every other term newest-first."""
    terms = list(AcademicTerm.objects.all())
    terms.sort(key=lambda term: (
        term.status != AcademicTerm.Status.ACTIVE,
        -term.start_date.toordinal(),
        -term.pk,
    ))
    return tuple(terms)


def _empty_report_scope(*, choices, code, message):
    return ReportScope(
        term=None, term_choices=choices, start=None, end=None, as_of=None,
        note=None, error=message, error_code=code,
        query_params=MappingProxyType({}), scope_query="",
    )


def _clamp(value, lower, upper):
    return min(max(value, lower), upper)


def selected_report_scope(
        request, *,
        default_window: Callable[[AcademicTerm], tuple[date, date]],
):
    """Resolve one selected term and a normalized, term-bounded report window.

    A missing ``term`` parameter selects the authoritative ACTIVE term. Once a
    caller supplies ``term``, however, a malformed or missing id is an explicit
    friendly error -- it never falls back to ACTIVE and never produces an
    all-term queryset (T-12-06). Archived terms default to their complete span;
    ACTIVE uses the controller's established useful-window callback.

    The returned query mapping/string is built only from normalized server-side
    values. This function never reads or writes ``request.session`` (D-10).
    """
    choices = _report_term_choices()
    term_was_supplied = "term" in request.GET
    term_raw = (request.GET.get("term") or "").strip()

    if term_was_supplied:
        if not term_raw.isdigit():
            return _empty_report_scope(
                choices=choices, code="invalid-term",
                message=("That academic term is not available. Choose a term "
                         "from the report filter."),
            )
        try:
            term = AcademicTerm.objects.get(pk=int(term_raw))
        except AcademicTerm.DoesNotExist:
            return _empty_report_scope(
                choices=choices, code="invalid-term",
                message=("That academic term is not available. Choose a term "
                         "from the report filter."),
            )
    else:
        term = get_active_term()
        if term is None:
            return _empty_report_scope(
                choices=choices, code="no-active-term",
                message=("No active academic term is available. Select a term "
                         "explicitly to view historical reports."),
            )

    today = timezone.localdate()
    if term.status == AcademicTerm.Status.ACTIVE:
        default_start, default_end = default_window(term)
    else:
        default_start, default_end = term.start_date, term.end_date
    default_start = _clamp(default_start, term.start_date, term.end_date)
    default_end = _clamp(default_end, term.start_date, term.end_date)
    if default_start > default_end:
        default_start, default_end = term.start_date, term.end_date

    from_raw = (request.GET.get("from") or "").strip()
    to_raw = (request.GET.get("to") or "").strip()
    as_of_raw = (request.GET.get("as_of") or "").strip()
    parsed_start = parse_date(from_raw) if from_raw else None
    parsed_end = parse_date(to_raw) if to_raw else None
    parsed_as_of = parse_date(as_of_raw) if as_of_raw else None

    invalid_date = (
        (from_raw and parsed_start is None)
        or (to_raw and parsed_end is None)
        or (as_of_raw and parsed_as_of is None)
    )
    note = None
    if invalid_date:
        note = ("That date wasn't valid, so the date filter was ignored and "
                "the selected term's safe default was used.")

    start = parsed_start if parsed_start is not None else default_start
    end = parsed_end if parsed_end is not None else default_end
    start = _clamp(start, term.start_date, term.end_date)
    end = _clamp(end, term.start_date, term.end_date)
    if start > end:
        start, end = default_start, default_end
        note = ("The start date was after the end date, so the report used "
                "the selected term's default range.")

    as_of_cap = min(end, today)
    as_of = parsed_as_of if parsed_as_of is not None else as_of_cap
    # A future term can begin after today; the upper as-of boundary still wins
    # because report denominators must never include future sessions.
    if as_of_cap >= term.start_date:
        as_of = _clamp(as_of, term.start_date, as_of_cap)
    else:
        as_of = as_of_cap

    normalized = {
        "term": str(term.pk),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "as_of": as_of.isoformat(),
    }
    return ReportScope(
        term=term, term_choices=choices, start=start, end=end, as_of=as_of,
        note=note, error=None, error_code=None,
        query_params=MappingProxyType(normalized),
        scope_query=urlencode(normalized),
    )


def status_label(status):
    """Map a Session status to the present/absent payroll label (HR-01, FAC-11).

    ACTIVE/COMPLETED are the two "held" states -> Present; ABSENT -> Absent;
    anything else (SCHEDULED, future) -> Scheduled (not yet a payroll fact).
    """
    if status in (SessionStatus.ACTIVE, SessionStatus.COMPLETED):
        return "Present"
    if status == SessionStatus.ABSENT:
        return "Absent"
    return "Scheduled"


def reporting_range(request):
    """Resolve the (start, end, as_of, note) reporting window from GET params.

    Optional ``from``/``to`` (ISO dates) select the window; absent or invalid input
    falls back to the current reporting week (the configured ``reporting_week_start``
    weekday through today) with a friendly note rather than raising a 500 (mirrors
    ``assignment_create`` validation; T-06-11). ``as_of`` is always today so a future
    not-yet-missed session never lowers attendance % (RESEARCH A5).

    Pure and role-agnostic: the IFO (unscoped) and Dean (department-scoped) surfaces
    both call this identically -- scoping is applied by the caller, never here.
    """
    today = timezone.localdate()
    start_day = _WEEKDAY_INDEX.get(
        str(get_policy("reporting_week_start")).lower(), 0)
    default_start = today - timedelta(days=(today.weekday() - start_day) % 7)

    from_raw = (request.GET.get("from") or "").strip()
    to_raw = (request.GET.get("to") or "").strip()
    start = parse_date(from_raw) if from_raw else None
    end = parse_date(to_raw) if to_raw else None

    note = None
    if (from_raw and start is None) or (to_raw and end is None):
        note = ("That date range wasn't valid, so we're showing the "
                "current week.")
        start = end = None
    if start is None:
        start = default_start
    if end is None:
        end = today
    if start > end:
        note = ("The start date was after the end date, so we're showing "
                "the current week.")
        start, end = default_start, today
    return start, end, today, note
