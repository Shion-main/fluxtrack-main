"""IFO Admin surfaces: rooms list, per-room schedule (IFO-11), QR poster (IFO-01),
and a live 'today' view (IFO-07, htmx-polled)."""
import io
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.models import Role
from campus.models import Room
from scheduling.models import AcademicTerm, ScheduleStatus, Session, SessionStatus


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
def _deep_link(room):
    return f"fluxtrack://scan?room={room.code}&t={room.qr_token}"


@ifo_required
def room_qr(request, code):
    import qrcode
    room = get_object_or_404(Room, code=code)
    img = qrcode.make(_deep_link(room))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@ifo_required
def room_poster(request, code):
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    return render(request, "ifo/poster.html", {"room": room})
