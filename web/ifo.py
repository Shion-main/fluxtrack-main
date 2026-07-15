"""IFO Admin surfaces: rooms list, per-room schedule (IFO-11), QR poster (IFO-01),
and a live 'today' view (IFO-07, htmx-polled)."""
import io
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Floor, Room
from ops.models import AuditLog, WeeklyReport
from ops.policy import get_policy
from scheduling.models import (AcademicTerm, Modality, ScheduleStatus, Session,
                                SessionStatus)
from scheduling.report_render import build_csv
from scheduling.reporting import (dept_summary, faculty_attendance,
                                  faculty_scorecard, safe_card)
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 DutyRole)
from verification.services import assign_online_sessions
from web.reporting_common import reporting_range as _reporting_range


def ifo_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.IFO_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _today_sessions():
    return (Session.objects.filter(date=timezone.localdate())
            .select_related("room", "schedule", "faculty").order_by("scheduled_start"))


@ifo_required
def rooms_list(request):
    rooms = list(Room.objects.select_related("floor__building")
                 .order_by("floor__building__code", "floor__number", "code"))
    today_counts = {}
    for s in _today_sessions():
        today_counts[s.room_id] = today_counts.get(s.room_id, 0) + 1
    # group by "Building N" for display
    groups = {}
    for r in rooms:
        key = f"{r.floor.building.name} · Floor {r.floor.number}"
        groups.setdefault(key, []).append((r, today_counts.get(r.id, 0)))
    return render(request, "ifo/rooms.html", {"groups": groups, "total": len(rooms)})


@ifo_required
def room_detail(request, code):
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    term = AcademicTerm.objects.filter(is_active=True).first()
    schedules = (room.schedules.filter(status=ScheduleStatus.ACTIVE, term=term)
                 .select_related("faculty").order_by("day_of_week", "start_time")
                 if term else room.schedules.none())
    upcoming = (room.sessions.filter(date__gte=timezone.localdate())
                .select_related("schedule", "faculty").order_by("date", "scheduled_start")[:10])
    return render(request, "ifo/room_detail.html",
                  {"room": room, "schedules": schedules, "upcoming": upcoming, "term": term})


@ifo_required
def live(request):
    return render(request, "ifo/live.html",
                  {"poll_ms": settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000})


@ifo_required
def live_rows(request):
    return render(request, "ifo/_live_rows.html",
                  {"sessions": _today_sessions(), "now": timezone.localtime()})


# --- QR poster (IFO-01) ---
def _deep_link(request, room):
    # A real URL (SCAN-07): the phone camera opens the scan flow, which
    # signs the user in if needed and auto-resolves the token.
    return request.build_absolute_uri(f"/scan?t={room.qr_token}")


@ifo_required
def room_qr(request, code):
    import qrcode
    room = get_object_or_404(Room, code=code)
    img = qrcode.make(_deep_link(request, room))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@ifo_required
def room_poster(request, code):
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    return render(request, "ifo/poster.html", {"room": room})


# --- Duty assignments (IFO-06) ---------------------------------------------
def _assignment_form_ctx():
    """Choice data for the assignment create form (Checkers/Guards + floors)."""
    duty_users = (get_user_model().objects
                  .filter(role__in=[Role.CHECKER, Role.GUARD], is_active=True)
                  .order_by("role", "last_name", "username"))
    floors = (Floor.objects.select_related("building")
              .order_by("building__code", "number"))
    return {"duty_users": duty_users, "floors": floors,
            "roles": DutyRole.choices, "types": AssignmentType.choices,
            "scopes": AssignmentScope.choices}


def _active_assignments():
    return (Assignment.objects.filter(status="active")
            .select_related("user").prefetch_related("floors__building")
            .order_by("role", "scope", "user__last_name"))


@ifo_required
def assignments_list(request):
    """IFO-06: active duty roster + the create form (non-admin UI)."""
    ctx = {"assignments": _active_assignments(), **_assignment_form_ctx()}
    return render(request, "ifo/assignments.html", ctx)


@ifo_required
@require_http_methods(["POST"])
def assignment_create(request):
    """IFO-06: create a floor or online-duty assignment from validated POST fields.

    The Assignment is built server-side from the choice fields (never trusting a
    forged scope/floor); every create writes an AuditLog (T-03-08/09). Creating
    ONLINE duty immediately round-robins that date's unowned online sessions so a
    newly-online-duty Checker picks them up. Invalid input renders a friendly
    error partial (status 400), never a 500.
    """
    User = get_user_model()
    user = User.objects.filter(pk=request.POST.get("user"),
                               role__in=[Role.CHECKER, Role.GUARD]).first()
    role = request.POST.get("role")
    type_ = request.POST.get("type")
    scope = request.POST.get("scope")
    floor_ids = request.POST.getlist("floors")
    date_raw = (request.POST.get("date") or "").strip()
    start_raw = (request.POST.get("start_time") or "").strip()
    end_raw = (request.POST.get("end_time") or "").strip()

    error = None
    if user is None:
        error = "Select a Checker or Guard."
    elif role not in DutyRole.values:
        error = "Select a valid duty role."
    elif type_ not in AssignmentType.values:
        error = "Select shift or standing."
    elif scope not in AssignmentScope.values:
        error = "Select floor or online scope."
    elif scope == AssignmentScope.FLOOR and not floor_ids:
        error = "A floor posting needs at least one floor."
    # Validate date/time FORMAT and floor-id numericness BEFORE the ORM write —
    # DateField/TimeField.to_python() and a non-numeric pk__in both raise an
    # unhandled ValidationError (500) at INSERT/.set() time otherwise (CR-04).
    elif date_raw and parse_date(date_raw) is None:
        error = "Enter a valid date."
    elif start_raw and parse_time(start_raw) is None:
        error = "Enter a valid start time."
    elif end_raw and parse_time(end_raw) is None:
        error = "Enter a valid end time."
    elif floor_ids and not all(f.isdigit() for f in floor_ids):
        error = "Invalid floor selection."

    if error:
        ctx = {"assignments": _active_assignments(), "error": error,
               **_assignment_form_ctx()}
        return render(request, "ifo/_assignment_form.html", ctx, status=400)

    term = AcademicTerm.objects.filter(is_active=True).first()
    a = Assignment.objects.create(
        user=user, role=role, type=type_, scope=scope,
        date=date_raw or None,
        start_time=start_raw or None,
        end_time=end_raw or None,
        term=term, status="active")
    if scope == AssignmentScope.FLOOR:
        # Only real floor pks land on the M2M; ONLINE ignores floors entirely.
        a.floors.set(Floor.objects.filter(pk__in=floor_ids))

    AuditLog.objects.create(
        actor=request.user, event_type="assignment.created",
        target_type="assignment", target_id=str(a.pk),
        payload={"user": user.pk, "role": role, "scope": scope, "type": type_,
                 "floors": list(a.floors.values_list("pk", flat=True))})

    # Granting online duty immediately pre-assigns unowned online sessions so the
    # new online-duty Checker picks them up (a dated posting -> that date only; a
    # standing posting -> today..+horizon).
    if scope == AssignmentScope.ONLINE:
        start = a.date or timezone.localdate()
        horizon = 0 if a.date else get_policy("materialization_horizon_days")
        d = start
        for _ in range(horizon + 1):
            assign_online_sessions(d)
            d += timedelta(days=1)

    ctx = {"assignments": _active_assignments(), "created": a,
           **_assignment_form_ctx()}
    return render(request, "ifo/_assignment_form.html", ctx)


# --- IFO-09 reporting dashboard + scorecard drill-down (RPT-04/RPT-05) -------
# The (start, end, as_of, note) window parser is the single shared implementation
# in web.reporting_common (imported as _reporting_range above), mirrored by the Dean
# surface -- no per-role copy is kept in sync by hand (code-review LO-03).


@ifo_required
def dashboard(request):
    """IFO-09: an unscoped reporting dashboard of summary cards over a selectable
    range. Each section is wrapped in ``safe_card`` so one raising aggregate shows
    its own inline error card while the rest of the page renders (RPT-05). The
    dashboard is read-only and point-in-time -- it refreshes on filter Apply, it
    is NOT continuously polled (assumption A-POLL).
    """
    start, end, as_of, note = _reporting_range(request)
    summary = safe_card(
        dept_summary, start=start, end=end, department=None, as_of=as_of)
    rows = safe_card(
        faculty_attendance, start=start, end=end, department=None, as_of=as_of)
    return render(request, "ifo/dashboard.html", {
        "summary": summary, "rows": rows,
        "date_from": start, "date_to": end, "range_note": note,
    })


@ifo_required
def scorecard(request, faculty_id):
    """RPT-04 drill-down: one faculty's full-page attendance scorecard (early-ends
    + effective-modality breakdown + itemized absences) over the same selectable
    range, reusing the shared ``faculty_scorecard`` aggregate. IFO is unscoped, so
    any faculty is reachable (A-DRILL: a full page, not a modal). Wrapped in
    ``safe_card`` so an aggregate failure renders the shared error card, not a 500.
    """
    faculty = get_object_or_404(get_user_model(), pk=faculty_id)
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
        "export_csv_url": f"/ifo/scorecard/{faculty.id}/export.csv",
    })


@ifo_required
@require_http_methods(["GET"])
def scorecard_csv(request, faculty_id):
    """RPT-04: export ONE faculty's attendance row for the current range as CSV.

    The scorecard's declared primary CTA (UI-SPEC). Reuses the shared aggregate +
    ``build_csv`` (csv_safe-neutralized name cells, T-06-02) rather than
    re-implementing either: runs the unscoped ``faculty_attendance`` and keeps only
    this faculty's row (IFO is unscoped, so any faculty is reachable). An
    out-of-range faculty simply yields a header-only CSV. Read-only (GET-only).
    """
    faculty = get_object_or_404(get_user_model(), pk=faculty_id)
    start, end, as_of, _note = _reporting_range(request)
    rows = [r for r in faculty_attendance(start=start, end=end, as_of=as_of)
            if r.faculty_id == faculty.id]
    resp = HttpResponse(build_csv(rows), content_type="text/csv")
    resp["Content-Disposition"] = (
        f'attachment; filename="scorecard-{faculty.id}-{start}.csv"')
    return resp


# --- Weekly Consolidated Report surface (RPT-01/03) -------------------------
# The IFO-facing deliverable: an index of the STORED weekly reports (every
# department PLUS the org-wide department=None roll-up) for a selected/most-recent
# week, each downloadable as the stored PDF/CSV bytes. IFO is the institution-wide
# role, so this surface is intentionally UNSCOPED -- unlike the department-scoped
# Dean surface (web.dean.weekly_download), there is NO department filter and the
# None roll-up is reachable. Every view is GET-only (read-only, T-06-07).


@ifo_required
@require_http_methods(["GET"])
def weekly_reports(request):
    """RPT-01/03: IFO-wide index of the stored weekly consolidated reports.

    Lists every ``WeeklyReport`` stored for the most-recent week (or a ``?week=``
    ISO date if supplied) -- one row per department PLUS the org-wide
    ``department=None`` roll-up -- each offering a primary ``Download PDF`` and a
    secondary ``Export CSV`` of the stored bytes. UNSCOPED by design: IFO sees all
    departments and the consolidated roll-up. Read-only (GET-only). An institution
    with no generated reports yet gets a calm Pattern-F empty state, never a crash.
    """
    week_raw = (request.GET.get("week") or "").strip()
    week = parse_date(week_raw) if week_raw else None
    if week is None:
        latest = WeeklyReport.objects.order_by("-week_start").first()
        week = latest.week_start if latest else None

    weeks = list(
        WeeklyReport.objects.order_by("-week_start")
        .values_list("week_start", flat=True).distinct())

    if week is not None:
        # NULLs sort first in ASC on both SQLite and MSSQL, so the department=None
        # roll-up leads the list; the template labels it "All departments".
        reports = list(
            WeeklyReport.objects.filter(week_start=week)
            .select_related("department")
            .order_by("department__code"))
    else:
        reports = []

    return render(request, "ifo/weekly_reports.html", {
        "reports": reports, "week": week, "weeks": weeks,
    })


@ifo_required
@require_http_methods(["GET"])
def weekly_download(request, pk, fmt):
    """RPT-03: stream a STORED WeeklyReport's csv/pdf for IFO -- UNSCOPED.

    Mirrors ``web.dean.weekly_download``'s storage-safety guard (server-built stored
    path, a missing file/path 404s -- never a 500) but WITHOUT the department
    scoping: IFO is institution-wide, so any report pk -- INCLUDING the org-wide
    ``department=None`` roll-up -- resolves. Read-only (GET-only).
    """
    report = get_object_or_404(WeeklyReport, pk=pk)
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
