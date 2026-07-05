"""Faculty surfaces (mobile-first, §2.5): today/week schedule (FAC-01), check-in,
and the modality-shift request surface (MOD-01/MOD-05/MOD-06, D-12).

MOD-06 / D-13: the modality-shift REQUEST workflow below (modality_new /
modality_mine / modality_withdraw) is the SOLE faculty entry point for changing a
session's modality. It replaces the retired FAC-07 faculty self-declare path --
there is no self-declare form or route here, by design. Same-day changes have no
formal path and fall back to existing scan-time behavior (D-13).
"""
from datetime import timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.availability import available_rooms_for, available_times_for
from scheduling.models import (
    AcademicTerm,
    Modality,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Schedule,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from scheduling.services import (
    ModalityShiftError,
    submit_modality_shift,
    weeks_window,
    withdraw_modality_shift,
)

_OCCUPYING_STATUSES = (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)
_MAX_WEEKS = 16  # a term is ~14-16 weeks; cap the recurring-request span


def faculty_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.FACULTY and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@faculty_required
def schedule(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    sessions = (Session.objects.filter(faculty=request.user,
                                       date__gte=today, date__lt=week_end)
                .select_related("schedule", "room").order_by("date", "scheduled_start"))
    todays, upcoming = [], []
    for s in sessions:
        (todays if s.date == today else upcoming).append(s)
    return render(request, "faculty/schedule.html",
                  {"todays": todays, "upcoming": upcoming, "today": today})


@faculty_required
def scan_page(request):
    return render(request, "faculty/scan.html", {"auto_payload": ""})


# --- Modality-shift request surface (MOD-01/MOD-05, D-12) -------------------
def _modality_new_ctx(user, *, error=None):
    """GET context for the submit form: the faculty's active schedules with an
    availability-first preview (D-05/D-15).

    For each active schedule the next upcoming SCHEDULED/ACTIVE session drives the
    picker data -- ``available_rooms_for`` (rooms free at that slot, original room
    first) and ``available_times_for`` (alternative same-day time-move slots).
    These are only meaningful for a ->F2F/Blended target; a ->Online shift needs no
    room. The concrete choice is finalized at Dean approval (D-06), so this is a
    preview, never a reservation.
    """
    today = timezone.localdate()
    term = AcademicTerm.objects.filter(is_active=True).first()
    schedules = []
    if term:
        schedules = list(
            Schedule.objects.filter(
                faculty=user, status=ScheduleStatus.ACTIVE, term=term)
            .select_related("room__floor__building")
            .order_by("day_of_week", "start_time"))
    rows = []
    for sch in schedules:
        nxt = (Session.objects.filter(
                    schedule=sch, date__gte=today,
                    status__in=_OCCUPYING_STATUSES)
               .select_related("schedule__room__floor__building")
               .order_by("date", "scheduled_start").first())
        rows.append({
            "schedule": sch,
            "next_session": nxt,
            "rooms": available_rooms_for(nxt) if nxt else [],
            "times": available_times_for(nxt) if nxt else [],
        })
    return {"schedule_rows": rows, "modalities": Modality.choices, "error": error}


@faculty_required
def modality_new(request):
    """Submit an availability-first modality-shift request (MOD-01/D-05/D-15).

    GET renders the picker; POST validates FORMAT before any write (parse_date on
    the window, target modality in ``Modality.values``, numeric schedule/room pks)
    exactly like ``ifo.assignment_create`` and, on any bad input, re-renders the
    form partial at status=400 (never a 500). Selected schedules are re-resolved to
    the requester's OWN active schedules server-side; a forged room pk is never
    trusted -- it is passed as a mere preference and the service re-resolves rooms.
    A valid submit calls ``submit_modality_shift`` (lead-time gate + Dean routing);
    any service refusal (too-late, no Dean, double-book) surfaces as a friendly 400.
    """
    if request.method != "POST":
        return render(request, "faculty/modality_new.html",
                      _modality_new_ctx(request.user))

    target = request.POST.get("target_modality")
    mode = (request.POST.get("window_mode") or "weeks").strip()
    weeks_raw = (request.POST.get("weeks") or "").strip()
    on_date_raw = (request.POST.get("on_date") or "").strip()
    schedule_ids = request.POST.getlist("schedules")
    nst_raw = (request.POST.get("new_start_time") or "").strip()
    net_raw = (request.POST.get("new_end_time") or "").strip()

    # Validate FORMAT before any ORM write -- a bad enum/count/date/pk must be a
    # friendly 400, never an unhandled ValidationError (500). The window is derived
    # server-side from either a weeks count (recurring) or a single date (one-off);
    # the client never posts raw start/end dates (D-01/D-15, UAT 2026-07-05).
    error = None
    window_start = window_end = None
    if target not in Modality.values:
        error = "Select a valid target modality."
    elif not schedule_ids:
        error = "Select at least one class."
    elif not all(s.isdigit() for s in schedule_ids):
        error = "Invalid class selection."
    elif mode == "single":
        on_date = parse_date(on_date_raw)
        if on_date is None:
            error = "Pick a valid date for the single session."
        else:
            window_start = window_end = on_date
    elif not weeks_raw.isdigit() or not (1 <= int(weeks_raw) <= _MAX_WEEKS):
        error = f"Choose how many weeks (1 to {_MAX_WEEKS})."
    else:
        window_start, window_end = weeks_window(int(weeks_raw))
    if error is None and (nst_raw or net_raw) and (
            parse_time(nst_raw) is None or parse_time(net_raw) is None):
        error = "Enter a valid alternative start and end time."

    # Re-resolve schedules to the requester's OWN active schedules (never trust the
    # posted pk set for ownership). A mismatch means a forged/foreign schedule.
    schedules = []
    if error is None:
        schedules = list(Schedule.objects.filter(
            pk__in=schedule_ids, faculty=request.user,
            status=ScheduleStatus.ACTIVE))
        if len(schedules) != len(set(schedule_ids)):
            error = "One or more selected classes are not yours."

    # Preferred rooms are a PREFERENCE only (D-05/D-06): the client room pk is never
    # trusted -- the service re-resolves free rooms at approval. Validate numericness
    # here so a bad pk is a 400, not a 500.
    preferred_rooms = {}
    if error is None:
        for sch in schedules:
            rk = (request.POST.get(f"preferred_room_{sch.pk}") or "").strip()
            if not rk:
                continue
            if not rk.isdigit():
                error = "Invalid room selection."
                break
            room = Room.objects.filter(pk=rk).first()
            if room is not None:
                preferred_rooms[sch] = room

    time_move = None
    if error is None and nst_raw and net_raw:
        time_move = (parse_time(nst_raw), parse_time(net_raw))

    if error is None:
        try:
            submit_modality_shift(
                request.user, schedules, target,
                window_start, window_end,
                preferred_rooms=preferred_rooms or None,
                time_move=time_move,
            )
        except ModalityShiftError as exc:
            error = str(exc)

    if error is not None:
        ctx = _modality_new_ctx(request.user, error=error)
        return render(request, "faculty/_modality_form.html", ctx, status=400)

    # Success: PRG to the "my requests" list. htmx uses HX-Redirect so the whole
    # page navigates rather than swapping the list into the form panel.
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = reverse("faculty_modality_mine")
        return resp
    return redirect("faculty_modality_mine")


def _modality_mine_ctx(user, *, error=None):
    """Context for the 'my requests' list: only the requester's tickets (D-12)."""
    requests = (ModalityShiftRequest.objects.filter(requester=user)
                .select_related("dean", "department")
                .prefetch_related("items__schedule")
                .order_by("-created_at"))
    return {"requests": requests, "error": error,
            "PENDING": ModalityShiftStatus.PENDING}


@faculty_required
def modality_mine(request):
    """The faculty's own modality-shift requests with per-status display (MOD-05).

    Scoped strictly to ``requester=request.user`` -- a faculty never sees another's
    tickets. Each row shows target modality, window, affected classes, status
    (pending/approved/rejected/withdrawn/denied) with the decision reason for
    rejected/denied, and a Withdraw control only while PENDING (D-10).
    """
    return render(request, "faculty/modality_mine.html",
                  _modality_mine_ctx(request.user))


@faculty_required
@require_http_methods(["POST"])
def modality_withdraw(request, pk):
    """Withdraw a still-PENDING ticket (MOD-05/D-10). POST-only; guard delegated.

    Re-fetches the request by pk and calls ``withdraw_modality_shift`` which itself
    re-checks requester==user AND status==PENDING inside the transaction (never the
    earlier snapshot / client -- the IDOR re-gate, T-04-01). A foreign or
    non-pending withdraw is refused and the list re-renders with the error at 400;
    on success the updated list renders.
    """
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    error = None
    try:
        withdraw_modality_shift(req, request.user)
    except ModalityShiftError as exc:
        error = str(exc)
    ctx = _modality_mine_ctx(request.user, error=error)
    return render(request, "faculty/modality_mine.html", ctx,
                  status=400 if error else 200)
