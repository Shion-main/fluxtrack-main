"""Dean approval surface (MOD-02, D-12): a department-scoped pending-approval
queue with approve/reject POST actions wired to the 04-05 apply/reject services.

The queue is scoped strictly to the Dean's OWN department (D-09/D-12): a request
routed to another department is never listed here. Every decision is POST-only
and re-gated server-side INSIDE the service transaction -- ``apply_approval`` and
``reject_modality_shift`` each re-check Role.DEAN + request.department ==
dean.department + status == PENDING before any write (Pitfall 6 / 03-02 re-gate,
T-04-01/T-04-03). The view NEVER mutates state directly: the service owns the
transaction, the availability re-check, the audit, and the notifications. A
no-room ->F2F approval is surfaced by the service as a terminal DENIED (D-07
REVISED); the view simply re-renders the queue with the returned outcome message.

Clones the established web/ifo.py role-gate + validated-POST shape and mirrors the
04-07 faculty surface (web/faculty.py) for consistency. ASCII-only by convention
(Windows cp1252).
"""
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from ops.models import WeeklyReport
from scheduling.models import Modality, ModalityShiftRequest, ModalityShiftStatus
from scheduling.report_render import build_csv, build_pdf
from scheduling.reporting import (
    DeptSummary,
    dept_summary,
    faculty_attendance,
    faculty_scorecard,
    safe_card,
)
from scheduling.services import (
    ModalityShiftError,
    apply_approval,
    reject_modality_shift,
)
from web.reporting_common import reporting_range as _reporting_range


def dean_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.DEAN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _queue_ctx(user, *, error=None, message=None):
    """Context for the department-scoped pending-approval queue (D-12).

    Scoped strictly to PENDING requests of the Dean's OWN department -- a request
    routed to another department is NEVER listed (MOD-02/D-09). Each row carries
    the requester, target modality, window, affected schedules (with any bundled
    time-move) and the faculty's preferred room, prefetched so the template makes
    no per-row queries.
    """
    requests = (
        ModalityShiftRequest.objects
        .filter(status=ModalityShiftStatus.PENDING, department=user.department)
        .select_related("requester", "department")
        .prefetch_related("items__schedule__room", "items__preferred_room")
        .order_by("created_at")
    )
    return {"requests": requests, "error": error, "message": message}


@dean_required
def queue(request):
    """The Dean's department-scoped pending-approval queue (MOD-02/D-12).

    Read-only list behind the dean_required gate; the decision actions are the
    separate POST-only approve/reject views. Requests from any other department
    are excluded server-side (never merely hidden)."""
    return render(request, "dean/queue.html", _queue_ctx(request.user))


@dean_required
@require_http_methods(["POST"])
def approve(request, pk):
    """Approve a PENDING request, applying the room release/assign consequence.

    POST-only; the guard is DELEGATED to ``apply_approval`` which re-fetches the
    request inside ``transaction.atomic()`` and re-checks Dean role + same
    department + PENDING before any write (never an earlier snapshot -- the IDOR /
    TOCTOU re-gate, T-04-01/T-04-03). A cross-department or non-pending approve
    raises ``ModalityShiftError`` and re-renders the queue at 400 with nothing
    changed. A ->F2F approval with no free room returns a terminal DENIED request
    (D-07 REVISED): the queue re-renders with the denial reason and the session is
    provably unchanged -- never surfaced as success (T-04-07). The view NEVER
    mutates state itself: the service owns the transaction, audit, and notifies."""
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    error = None
    message = None
    try:
        result = apply_approval(req, request.user)
    except ModalityShiftError as exc:
        error = str(exc)
    else:
        if result.status == ModalityShiftStatus.DENIED:
            message = (result.decision_reason
                       or "No room available that day - request denied.")
        else:
            message = "Request approved."
    ctx = _queue_ctx(request.user, error=error, message=message)
    return render(request, "dean/_queue.html", ctx,
                  status=400 if error else 200)


@dean_required
@require_http_methods(["POST"])
def reject(request, pk):
    """Reject a PENDING request with a required reason (MOD-02/D-10/D-11).

    POST-only; a non-empty reason is required (rendered at 400 otherwise -- the
    T-04-05v input-validation guard, mirroring ifo.assignment_create). The guard is
    delegated to ``reject_modality_shift`` which re-checks Dean role + same
    department + PENDING inside its transaction and notifies the requester once;
    the view never mutates state itself."""
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    reason = (request.POST.get("reason") or "").strip()
    error = None
    message = None
    if not reason:
        error = "A reason is required to reject a request."
    else:
        try:
            reject_modality_shift(req, request.user, reason)
        except ModalityShiftError as exc:
            error = str(exc)
        else:
            message = "Request rejected."
    ctx = _queue_ctx(request.user, error=error, message=message)
    return render(request, "dean/_queue.html", ctx,
                  status=400 if error else 200)


# --- DEAN reporting surface (DEAN-01..04, RPT-03) ---------------------------
# The read-only, department-scoped consumer of the same shared aggregate/render
# layers IFO-09 uses. EVERY queryset below is scoped to request.user.department
# server-side; a crafted faculty_id / report pk / department param NEVER crosses
# the boundary (T-06-01 IDOR/BOLA). Every view is GET-only (T-06-07 read-only).
# The (start, end, as_of, note) window parser is the single shared implementation
# in web.reporting_common (imported as _reporting_range above); the IFO surface uses
# the same one -- the pure range logic has no role-coupling to keep apart (LO-03).


@dean_required
@require_http_methods(["GET"])
def dashboard(request):
    """DEAN-04: a department-scoped reporting dashboard (read-only, DEAN-01).

    Scopes strictly to ``request.user.department`` -- the four KPI cards derive
    from ONE ``safe_card(dept_summary)`` call over the current reporting week, and
    the latest-weekly-report card is the newest ``WeeklyReport`` for THIS department
    only. A Dean with a NULL department (edge case) sees a calm, empty, no-crash
    dashboard -- never an unscoped ALL-departments roll-up. Point-in-time (refresh
    on filter Apply); never continuously polled.
    """
    dept = request.user.department
    start, end, as_of, note = _reporting_range(request)
    if dept is None:
        # NULL-department Dean: nothing is scoped in -> a zeroed, no-crash card.
        # NEVER dept_summary(department=None), which would leak ALL departments.
        summary = (DeptSummary(0, 0, 0, 0, 0), None)
        latest = None
    else:
        summary = safe_card(
            dept_summary, start=start, end=end, department=dept, as_of=as_of)
        latest = WeeklyReport.objects.filter(department=dept).first()
    return render(request, "dean/dashboard.html", {
        "department": dept, "summary": summary, "latest_report": latest,
        "date_from": start, "date_to": end, "range_note": note,
    })


@dean_required
@require_http_methods(["GET"])
def reports(request):
    """DEAN-02: the department-scoped attendance report (read-only, DEAN-01).

    Renders one ``faculty_attendance`` row per faculty in ``request.user.department``
    ONLY (a foreign department's faculty are never in the queryset), with Pattern-C
    CSV/PDF export anchors. A NULL-department Dean sees an empty table (nothing
    scoped in), never an unscoped all-departments result.
    """
    dept = request.user.department
    start, end, as_of, note = _reporting_range(request)
    if dept is None:
        rows = ([], None)
    else:
        rows = safe_card(
            faculty_attendance, start=start, end=end, department=dept, as_of=as_of)
    return render(request, "dean/reports.html", {
        "department": dept, "rows": rows,
        "date_from": start, "date_to": end, "range_note": note,
    })


@dean_required
@require_http_methods(["GET"])
def scorecard(request, faculty_id):
    """DEAN-02 drill-down: one faculty's full-page scorecard, department-scoped.

    The IDOR/BOLA control (T-06-01): ``get_object_or_404(User, pk=faculty_id,
    department=request.user.department)`` -- a faculty in ANOTHER department 404s
    server-side (refused, not merely hidden). Reuses the shared
    reports/scorecard.html; the back link is pointed at the Dean report via
    ``back_url`` so it never sends a Dean to the IFO-only dashboard.
    """
    dept = request.user.department
    if dept is None:
        # NULL-department Dean: nothing is scoped in. Without this guard
        # department=None becomes department__isnull=True and would match
        # NULL-department faculty -- refuse, consistent with dashboard/reports.
        raise Http404("No department.")
    faculty = get_object_or_404(
        get_user_model(), pk=faculty_id, department=dept)
    start, end, as_of, note = _reporting_range(request)
    card = safe_card(
        faculty_scorecard, faculty=faculty, start=start, end=end, as_of=as_of)
    modality_items = None
    if card[0] is not None:
        labels = dict(Modality.choices)
        modality_items = [(labels.get(k, k), n)
                          for k, n in card[0].modality_breakdown.items()]
    return render(request, "reports/scorecard.html", {
        "faculty": faculty, "card": card, "modality_items": modality_items,
        "date_from": start, "date_to": end, "range_note": note,
        "back_url": "/dean/reports",
    })


@dean_required
@require_http_methods(["GET"])
def report_export(request, fmt):
    """DEAN-03/RPT-03: ad-hoc CSV/PDF export of the current department range.

    Builds the department-scoped ``FacultyRow`` list for ``request.user.department``
    and returns ``build_csv``/``build_pdf`` bytes as an attachment (the render layer
    is REUSED, not re-implemented; ``build_csv`` already csv_safe-neutralizes name
    cells, T-06-02). A NULL-department Dean exports an empty (header-only) report.
    An unknown ``fmt`` 404s.
    """
    dept = request.user.department
    start, end, as_of, _note = _reporting_range(request)
    rows = ([] if dept is None
            else faculty_attendance(
                start=start, end=end, department=dept, as_of=as_of))
    code = dept.code if dept is not None else "none"
    if fmt == "csv":
        data, content_type, ext = build_csv(rows), "text/csv", "csv"
    elif fmt == "pdf":
        data = build_pdf(rows, start, dept)
        content_type, ext = "application/pdf", "pdf"
    else:
        raise Http404("Unknown export format.")
    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = (
        f'attachment; filename="attendance-{code}-{start}.{ext}"')
    return resp


@dean_required
@require_http_methods(["GET"])
def weekly_download(request, pk, fmt):
    """DEAN-03: stream a STORED WeeklyReport's csv/pdf, department-scoped.

    The IDOR/BOLA control (T-06-01): ``get_object_or_404(WeeklyReport, pk=pk,
    department=request.user.department)`` -- another department's report pk 404s
    server-side. The stored bytes are served from ``default_storage`` under the
    server-built path; a missing file/path 404s (never a 500).
    """
    dept = request.user.department
    if dept is None:
        # NULL-department Dean: department=None becomes department__isnull=True
        # and would match the org-wide ALL-departments roll-up report (stored
        # with department=None). Refuse -- a Dean never sees the consolidated file.
        raise Http404("No department.")
    report = get_object_or_404(
        WeeklyReport, pk=pk, department=dept)
    if fmt == "csv":
        path, content_type = report.csv_path, "text/csv"
    elif fmt == "pdf":
        path, content_type = report.pdf_path, "application/pdf"
    else:
        raise Http404("Unknown export format.")
    if not path or not default_storage.exists(path):
        raise Http404("Report file not found.")
    with default_storage.open(path, "rb") as fh:
        data = fh.read()
    filename = path.rsplit("/", 1)[-1]
    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
