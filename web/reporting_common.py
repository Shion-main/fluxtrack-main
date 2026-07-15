"""Shared reporting helpers for the Phase-6 role surfaces (web.ifo / web.dean).

The reporting-range parser was originally duplicated verbatim in ``web/ifo.py`` and
``web/dean.py`` (plus a third copy of ``_WEEKDAY_INDEX``). The logic is pure and
role-agnostic -- it reads only GET params + the ``reporting_week_start`` policy and
returns dates -- so there is no role-coupling reason to keep two copies in sync by
hand (code-review LO-03). This module owns the single implementation both role
views import. ASCII-only by convention (Windows cp1252).
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date

from ops.policy import get_policy

# reporting_week_start policy value -> Python weekday() index (Mon=0 .. Sun=6).
_WEEKDAY_INDEX = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                  "friday": 4, "saturday": 5, "sunday": 6}


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
