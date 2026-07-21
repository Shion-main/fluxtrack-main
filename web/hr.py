"""HR Admin attendance surface (HR-01/HR-02/HR-03).

HR consumes attendance at the SESSION grain (not the aggregate grain the Dean/IFO
dashboards use): every session with its actual times, check-in method, and
checker-verification status, filterable by faculty, department, date range, and
term, and exportable as CSV for external payroll.

Access is gated by ``hr_required`` (login + Role.HR_ADMIN, superuser bypass,
T-06-14). HR is cross-department BY DESIGN (it sees all departments), so department
is a FILTER here, not a security boundary (unlike the Dean surface). The surface is
strictly READ-ONLY -- every view is GET-only (T-06-07) so a POST is 405; there is
no write/mutation endpoint.

The CSV export (HR-03) is the one surface whose download can hit full-term scale,
so it STREAMS (``StreamingHttpResponse`` + ``queryset.iterator()``) to bound memory
and REUSES ``scheduling.report_render.csv_safe`` -- the single phase-wide
CSV-injection neutralizer (T-06-02) -- so a user-controlled faculty name can never
become an executable Excel formula. NO database write is performed inside the
streaming generator (MSSQL HY010/cursor-open trap avoided). ASCII-only by
convention (Windows cp1252).
"""
import csv
from functools import wraps
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Department, Role
from scheduling.models import Session
from scheduling.report_render import csv_safe
from scheduling.reporting import session_minutes_late
from verification.models import CheckerValidation, ValidationAction
from web.pagination import paginate
from web.reporting_common import selected_report_scope, status_label

# The on-screen list is PAGED, not capped. The old behaviour sliced to 200 rows
# and said "showing up to 200" -- which never told the reader whether they were
# seeing everything, the wrong property for a payroll source of truth. The CSV
# export still streams the full filtered set (HR-03); paging bounds the screen,
# not the data.
HR_PAGE_SIZE = 50

# CSV column contract (HR-03 payroll export). One constant so the header row and
# every streamed data row can never drift.
# "Minutes late" is a DERIVED column added immediately after the raw "Actual start"
# timestamp (A3 / D-03: ADD the derived figure, do NOT remove the timestamp). It is
# computed per session via the shared scheduling.reporting.session_minutes_late
# helper so the payroll export can never disagree with the faculty aggregate that
# reads the same helper (Pitfall 5 -- this is a SEPARATE contract from the weekly
# report's report_render.HEADER).
CSV_HEADER = [
    "Faculty", "Department", "Course", "Section", "Date", "Scheduled start",
    "Actual start", "Minutes late", "Status", "Method", "Checker-verified",
]


def hr_required(view):
    """Gate a view to Role.HR_ADMIN (superuser bypass), else 403 (T-06-14).

    Mirrors ``web.ifo.ifo_required`` / ``web.dean.dean_required``: login is
    required first, then the role is checked server-side. A non-HR authenticated
    user (e.g. a faculty member) is refused with ``PermissionDenied`` (403), never
    merely hidden.
    """
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.HR_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _hr_default_window(term):
    """Preserve HR's established whole-term payroll window for ACTIVE."""
    return term.start_date, term.end_date


def _report_scope(request):
    return selected_report_scope(request, default_window=_hr_default_window)


def _filtered_sessions(request, scope):
    """Parse the HR GET filter bar and return ``(queryset, filters)`` (HR-02).

    Builds the session-level base queryset -- ``select_related`` for the faculty /
    schedule / room / term / department it reads (no N+1), and ``is_verified``
    ANNOTATED via ``Exists`` so the checker-verification status costs no per-row
    query (crucial for the streaming CSV: the annotation is resolved in the main
    query, so no subquery runs inside the ``.iterator()`` generator).

    Term/date scope is normalized before this function. Faculty, department, and
    search remain independent, authorization-neutral filters. The same parser
    feeds list and CSV so they always agree on scope.
    """
    faculty_raw = (request.GET.get("faculty") or "").strip()
    dept_raw = (request.GET.get("department") or "").strip()
    q = (request.GET.get("q") or "").strip()

    filters = {
        "faculty": faculty_raw,
        "department": dept_raw,
        "term": str(scope.term.pk) if scope.term else "",
        "date_from": scope.start.isoformat() if scope.start else "",
        "date_to": scope.end.isoformat() if scope.end else "",
        "q": q,
        "note": scope.note,
        "any_applied": bool(
            faculty_raw or dept_raw or q
            or any(name in request.GET for name in ("term", "from", "to", "as_of"))
        ),
    }
    if not scope.is_valid:
        return Session.objects.none(), filters

    verified_sq = CheckerValidation.objects.filter(
        session=OuterRef("pk"), action=ValidationAction.VERIFIED)
    qs = (Session.objects
          .filter(schedule__term=scope.term,
                  date__range=(scope.start, scope.end))
          .select_related("schedule", "schedule__term", "faculty",
                          "faculty__department", "room")
          .annotate(is_verified=Exists(verified_sq))
          .order_by("-date", "-scheduled_start"))

    # FK-id filters: applied only when the value is a clean integer id. A forged or
    # garbage value is ignored (never fed to the ORM as a raw non-numeric lookup).
    if faculty_raw.isdigit():
        qs = qs.filter(faculty_id=int(faculty_raw))
    if dept_raw.isdigit():
        qs = qs.filter(faculty__department_id=int(dept_raw))
    # Free-text search over the faculty display name + course code.
    if q:
        qs = qs.filter(
            Q(faculty__first_name__icontains=q)
            | Q(faculty__last_name__icontains=q)
            | Q(schedule__course_code__icontains=q))

    return qs, filters


def _filter_choices():
    """Cross-department faculty/department choices for the HR filter bar."""
    faculty = (get_user_model().objects
               .filter(role=Role.FACULTY, is_active=True)
               .order_by("last_name", "first_name", "username"))
    departments = Department.objects.order_by("code")
    return {"faculty_choices": faculty, "department_choices": departments}


def _surface_filter_params(filters):
    return {
        key: value for key, value in (
            ("faculty", filters["faculty"]),
            ("department", filters["department"]),
            ("q", filters["q"]),
        ) if value
    }


def _scope_url(view_name, scope, filters=None):
    params = dict(scope.query_params)
    if filters:
        params.update(_surface_filter_params(filters))
    query = urlencode(params)
    return f"{reverse(view_name)}?{query}" if query else reverse(view_name)


@hr_required
@require_http_methods(["GET"])
def attendance(request):
    """HR-01/HR-02: the session-level attendance list behind the ``hr_required`` gate.

    Read-only (GET-only). Renders the PAGED, filtered session list with the
    Pattern-A filter bar (faculty / department / date range / term / search) and the
    Pattern-F empty + no-results states. ``paginate`` carries the active filters
    into every page link, so paging never silently widens or drops a filter. The
    full filtered set is still what the CSV export streams. Invalid filter input
    degrades to a friendly note, never a 500.
    """
    scope = _report_scope(request)
    qs, filters = _filtered_sessions(request, scope)
    # A fresh request has no GET term to preserve, so feed pagination a known,
    # normalized query mapping rather than the untrusted raw request mapping.
    normalized_get = request.GET.copy()
    normalized_get.clear()
    normalized_get.update(scope.query_params)
    normalized_get.update(_surface_filter_params(filters))
    if request.GET.get("page"):
        normalized_get["page"] = request.GET["page"]
    pager = paginate(SimpleNamespace(GET=normalized_get), qs,
                     per_page=HR_PAGE_SIZE)
    sessions = list(pager["page"].object_list)
    for s in sessions:
        s.present_label = status_label(s.status)
    ctx = {
        "sessions": sessions,
        "filters": filters,
        "scope": scope,
        "scope_query": scope.scope_query,
        "export_url": (
            _scope_url("hr_attendance_csv", scope, filters)
            if scope.is_valid else ""
        ),
        "reset_url": (
            _scope_url("hr_attendance", scope)
            if scope.is_valid else reverse("hr_attendance")
        ),
        **pager,
        **_filter_choices(),
    }
    return render(request, "hr/attendance.html", ctx)


class _Echo:
    """A write-only file-like object whose ``write`` returns the value written.

    ``csv.writer`` writes each formatted row into this object; because ``write``
    returns the string, the row is what the ``StreamingHttpResponse`` generator
    yields -- no buffer is accumulated, so memory stays bounded at full-term scale
    (the streaming CSV idiom; RESEARCH Pattern 3).
    """

    def write(self, value):
        return value


def _fmt_dt(dt):
    """Render an aware datetime in local time for the payroll CSV, or '' if None."""
    if dt is None:
        return ""
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


@hr_required
@require_http_methods(["GET"])
def attendance_csv(request):
    """HR-03: stream the filtered session list as an injection-safe payroll CSV.

    Applies the SAME ``_filtered_sessions`` parser as ``attendance`` so the export
    scope always matches the on-screen filters, then streams
    (``StreamingHttpResponse`` + ``queryset.iterator()``) so a full-term export
    never buffers in memory (T-06-03). Text cells (faculty name, department, course,
    section, method) are run through the REUSED ``scheduling.report_render.csv_safe``
    so a faculty name beginning with ``= + - @`` can never become an Excel formula
    (T-06-02). NO database write is performed inside the generator -- the
    checker-verified status is the ``is_verified`` ANNOTATION resolved in the main
    query, so no subquery runs while the server-side cursor is open (MSSQL
    HY010/cursor-open trap avoided, T-06-15). Read-only (GET-only).
    """
    scope = _report_scope(request)
    if not scope.is_valid:
        return HttpResponse(scope.error, status=400, content_type="text/plain")
    qs, _filters = _filtered_sessions(request, scope)
    writer = csv.writer(_Echo())

    def rows():
        yield writer.writerow(CSV_HEADER)
        for s in qs.iterator():
            dept = s.faculty.department
            yield writer.writerow([
                csv_safe(s.faculty.get_full_name() or s.faculty.username),
                csv_safe(dept.code if dept else ""),
                csv_safe(s.schedule.course_code),
                csv_safe(s.schedule.section),
                s.date.isoformat(),
                _fmt_dt(s.scheduled_start),
                _fmt_dt(s.actual_start),
                # Derived whole-minutes-late from the SHARED helper (seconds -> min);
                # 0 for on-time/early/ABSENT (NULL start). No DB access here -- the
                # helper reads already-loaded session fields, so the open server-side
                # cursor / HY010 streaming contract holds (T-06-05).
                session_minutes_late(s.scheduled_start, s.actual_start) // 60,
                status_label(s.status),
                csv_safe(s.get_checkin_method_display() if s.checkin_method else ""),
                "yes" if s.is_verified else "no",
            ])

    filename = (f"hr-attendance-term-{scope.term.pk}-"
                f"{timezone.localdate().isoformat()}.csv")
    resp = StreamingHttpResponse(rows(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["X-Report-Term"] = str(scope.term.pk)
    resp["X-Report-From"] = scope.start.isoformat()
    resp["X-Report-To"] = scope.end.isoformat()
    return resp
