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

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from accounts.models import Department, Role
from scheduling.models import AcademicTerm, Session
from scheduling.report_render import csv_safe
from scheduling.reporting import session_minutes_late
from verification.models import CheckerValidation, ValidationAction
from web.pagination import paginate
from web.reporting_common import status_label

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


def _filtered_sessions(request):
    """Parse the HR GET filter bar and return ``(queryset, filters)`` (HR-02).

    Builds the session-level base queryset -- ``select_related`` for the faculty /
    schedule / room / term / department it reads (no N+1), and ``is_verified``
    ANNOTATED via ``Exists`` so the checker-verification status costs no per-row
    query (crucial for the streaming CSV: the annotation is resolved in the main
    query, so no subquery runs inside the ``.iterator()`` generator).

    Applies four INDEPENDENT filters + a free-text search, each keyed on an FK id or
    ``date__range`` (NEVER a ``pk__in`` id list -> the 2100-param trap): faculty
    (id), department (``faculty__department`` id), term (``schedule__term`` id),
    date range (``from``/``to`` via ``parse_date``), and a search over faculty
    name / course_code. Invalid input degrades to a friendly note and is simply
    ignored -- it never raises a 500 (T-06-16). The SAME parser feeds both the list
    view and the CSV export so they always agree on scope.
    """
    verified_sq = CheckerValidation.objects.filter(
        session=OuterRef("pk"), action=ValidationAction.VERIFIED)
    qs = (Session.objects
          .select_related("schedule", "schedule__term", "faculty",
                          "faculty__department", "room")
          .annotate(is_verified=Exists(verified_sq))
          # Newest-first: the page cap then shows the most RECENT sessions, not
          # the oldest historical rows once volume exceeds one page (code-review
          # HIGH). The CSV export streams the full set in the same order.
          .order_by("-date", "-scheduled_start"))

    faculty_raw = (request.GET.get("faculty") or "").strip()
    dept_raw = (request.GET.get("department") or "").strip()
    term_raw = (request.GET.get("term") or "").strip()
    from_raw = (request.GET.get("from") or "").strip()
    to_raw = (request.GET.get("to") or "").strip()
    q = (request.GET.get("q") or "").strip()

    note = None

    # FK-id filters: applied only when the value is a clean integer id. A forged or
    # garbage value is ignored (never fed to the ORM as a raw non-numeric lookup).
    if faculty_raw.isdigit():
        qs = qs.filter(faculty_id=int(faculty_raw))
    if dept_raw.isdigit():
        qs = qs.filter(faculty__department_id=int(dept_raw))
    if term_raw.isdigit():
        qs = qs.filter(schedule__term_id=int(term_raw))

    # Date-range filter: parse_date-validated. An invalid date leaves a friendly
    # note and drops just that bound -- a 200 with a notice, never a 500 (HR-02).
    d_from = parse_date(from_raw) if from_raw else None
    d_to = parse_date(to_raw) if to_raw else None
    if (from_raw and d_from is None) or (to_raw and d_to is None):
        note = ("That date wasn't valid, so the date filter was ignored. "
                "Enter dates as YYYY-MM-DD.")
    if d_from is not None:
        qs = qs.filter(date__gte=d_from)
    if d_to is not None:
        qs = qs.filter(date__lte=d_to)

    # Free-text search over the faculty display name + course code.
    if q:
        qs = qs.filter(
            Q(faculty__first_name__icontains=q)
            | Q(faculty__last_name__icontains=q)
            | Q(schedule__course_code__icontains=q))

    filters = {
        "faculty": faculty_raw, "department": dept_raw, "term": term_raw,
        "date_from": from_raw, "date_to": to_raw, "q": q, "note": note,
        "any_applied": bool(faculty_raw or dept_raw or term_raw
                            or from_raw or to_raw or q),
    }
    return qs, filters


def _filter_choices():
    """Choice data for the Pattern-A filter bar (faculty / department / term).

    The term list preselects the single active term in the template. Cross-
    department by design: every department and every faculty is a filter option
    (HR is not department-scoped).
    """
    faculty = (get_user_model().objects
               .filter(role=Role.FACULTY, is_active=True)
               .order_by("last_name", "first_name", "username"))
    departments = Department.objects.order_by("code")
    terms = AcademicTerm.objects.order_by("-is_active", "-start_date")
    active_term = AcademicTerm.objects.filter(is_active=True).first()
    return {"faculty_choices": faculty, "department_choices": departments,
            "term_choices": terms, "active_term": active_term}


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
    qs, filters = _filtered_sessions(request)
    pager = paginate(request, qs, per_page=HR_PAGE_SIZE)
    sessions = list(pager["page"].object_list)
    for s in sessions:
        s.present_label = status_label(s.status)
    ctx = {"sessions": sessions, "filters": filters,
           **pager, **_filter_choices()}
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
    qs, _filters = _filtered_sessions(request)
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

    filename = f"hr-attendance-{timezone.localdate().isoformat()}.csv"
    resp = StreamingHttpResponse(rows(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
