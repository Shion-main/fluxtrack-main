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
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from accounts.models import Department, Role
from scheduling.models import AcademicTerm, Session, SessionStatus
from verification.models import CheckerValidation, ValidationAction

# The on-screen list is capped -- the full (uncapped) set is what the CSV export
# streams. This keeps the HTML page bounded while payroll still gets everything.
HR_PAGE_SIZE = 200


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


def _status_label(status):
    """Map a Session status to the HR present/absent payroll label (HR-01).

    ACTIVE/COMPLETED are the two "held" states -> Present; ABSENT -> Absent;
    anything else (SCHEDULED, future) -> Scheduled (not yet a payroll fact).
    """
    if status in (SessionStatus.ACTIVE, SessionStatus.COMPLETED):
        return "Present"
    if status == SessionStatus.ABSENT:
        return "Absent"
    return "Scheduled"


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
          .order_by("date", "scheduled_start"))

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

    Read-only (GET-only). Renders the page-capped, filtered session list with the
    Pattern-A filter bar (faculty / department / date range / term / search) and the
    Pattern-F empty + no-results states. The full (uncapped) filtered set is what the
    CSV export streams; here the list is sliced to ``HR_PAGE_SIZE`` so the HTML page
    stays bounded. Invalid filter input degrades to a friendly note, never a 500.
    """
    qs, filters = _filtered_sessions(request)
    sessions = list(qs[:HR_PAGE_SIZE])
    for s in sessions:
        s.present_label = _status_label(s.status)
    ctx = {"sessions": sessions, "filters": filters,
           "page_size": HR_PAGE_SIZE, **_filter_choices()}
    return render(request, "hr/attendance.html", ctx)
