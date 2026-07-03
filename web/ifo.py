"""IFO Admin surfaces: rooms list, per-room schedule (IFO-11), QR poster (IFO-01),
and a live 'today' view (IFO-07, htmx-polled)."""
import io
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Floor, Room
from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.models import AcademicTerm, ScheduleStatus, Session, SessionStatus
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 DutyRole)
from verification.services import assign_online_sessions


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

    if error:
        ctx = {"assignments": _active_assignments(), "error": error,
               **_assignment_form_ctx()}
        return render(request, "ifo/_assignment_form.html", ctx, status=400)

    term = AcademicTerm.objects.filter(is_active=True).first()
    a = Assignment.objects.create(
        user=user, role=role, type=type_, scope=scope,
        date=request.POST.get("date") or None,
        start_time=request.POST.get("start_time") or None,
        end_time=request.POST.get("end_time") or None,
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
