"""Guard surfaces (GRD-01 floor monitor, GRD-02 per-room schedule, GRD-03 locator).

READ-ONLY throughout, and read-only BY CONTRACT (GRD-05): every view carries
`@require_http_methods(["GET"])`, so a POST is refused with 405 rather than
merely having no write branch to reach. GuardReadOnlyTests asserts this per URL;
every Guard view added later must carry the decorator and join that list.

Floor scoping mirrors the checker's on-duty derivation exactly: the server is the
sole source of the guard's floors (GRD/CHK-01 rule), never the client.
"""
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.policy import get_policy
from scheduling.models import (AcademicTerm, Modality, Session, SessionStatus)
from verification import resolver as R
from verification.models import Assignment, AssignmentScope, DutyRole
from web.room_state import occupies, room_timetable, room_tile


def guard_required(view):
    """Per-view role guard (Convention rule #5), mirroring checker_required."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.GUARD and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _guard_floor_ids(user, now):
    """Floor pks the guard is posted to RIGHT NOW (GRD-01).

    Mirrors checker `_active_floor_ids` but for an active FLOOR-scoped GUARD
    assignment (standing posting, or a shift covering `now`). The server's sole
    source of the guard's floors -- the client never supplies its own.
    """
    local = timezone.localtime(now)
    today, now_t = local.date(), local.time()
    floor_ids = set()
    for a in (Assignment.objects
              .filter(user=user, role=DutyRole.GUARD,
                      scope=AssignmentScope.FLOOR, status="active")
              .prefetch_related("floors")):
        if R.assignment_covers_now(a, today, now_t):
            # `.all()` reads the prefetch cache; `.values_list()` on the related
            # manager would bypass it and re-query once per assignment, making
            # the prefetch above buy nothing.
            floor_ids.update(f.pk for f in a.floors.all())
    return floor_ids


def _poll_ms():
    # Through `get_policy`, not `settings.FLUXTRACK_POLICY` directly: only the
    # former honours a SystemSetting override, so an operator retuning the poll
    # interval used to silently miss the Guard monitor (Conventions #3).
    return int(get_policy("poll_interval_seconds")) * 1000


@guard_required
@require_http_methods(["GET"])
def monitor(request):
    """GRD-01 floor monitor shell (navy floor family). The polled body is
    guard/_monitor_rows.html; on-duty state is re-derived server-side per poll."""
    return render(request, "guard/monitor.html", {"poll_ms": _poll_ms()})


@guard_required
@require_http_methods(["GET"])
def monitor_rows(request):
    now = timezone.now()
    floor_ids = _guard_floor_ids(request.user, now)
    sessions = None
    if floor_ids:
        sessions = (Session.objects
                    .filter(date=timezone.localdate(), room__floor_id__in=floor_ids)
                    .select_related("room", "schedule", "faculty")
                    .order_by("scheduled_start"))
    return render(request, "guard/_monitor_rows.html",
                  {"sessions": sessions, "on_duty": bool(floor_ids),
                   "now": timezone.localtime(now)})


# --- GRD-02 per-room schedule ----------------------------------------------
# Server-computed presentation token per room state. Colour is NEVER the only
# signal (WCAG 1.4.1): every state also carries a Lucide icon and a text label,
# mapped here rather than branched on in the template -- the same discipline as
# `web/checker._CARD_STYLES`.
#
# The five states come from `web/room_state.room_tile`; the wording is
# deliberately about the ROOM, not about a person's attendance record. A Guard
# needs to know whether anyone is in the room; absence history and Checker flags
# stay on the HR/Dean/IFO surfaces (D-07 minimum access).
_ROOM_CARD_STYLES = {
    "absent": {"card": "ft-card--bad", "pill": "ft-pill ft-pill--absent",
               "icon": "user-x", "label": "Nobody checked in"},
    "starting": {"card": "ft-card--warn", "pill": "ft-pill ft-pill--late",
                 "icon": "clock", "label": "Class starting"},
    "in_session": {"card": "ft-card--ok", "pill": "ft-pill ft-pill--active",
                   "icon": "check-circle", "label": "In session"},
    "free": {"card": "ft-card--info", "pill": "ft-pill ft-pill--upcoming",
             "icon": "door-open", "label": "Free right now"},
    "idle": {"card": "ft-card--neutral", "pill": "ft-pill ft-pill--upcoming",
             "icon": "circle", "label": "Nothing scheduled today"},
}


@guard_required
@require_http_methods(["GET"])
def room_detail(request, code):
    """GRD-02: one room's live state, today's timeline and its weekly timetable.

    Authorization is the whole point of this view and has no IFO analog. The
    guard's floors are re-derived SERVER-SIDE on every request from their current
    assignments (`_guard_floor_ids`, which delegates the standing-vs-shift
    decision to `verification.resolver.assignment_covers_now`); the client never
    supplies a floor or a room scope that is trusted.

    An off-floor or off-shift room raises Http404, not PermissionDenied. A 403
    would confirm that the room code exists -- mirroring how `web/checker.py`
    refuses a non-owner online session, the room simply is not there for this
    guard right now.

    Everything else is derived from `web/room_state.py`, so the online-occupancy
    rule and the past-grace no-show rule behave identically to the IFO board
    because they ARE the IFO board's code.
    """
    room = get_object_or_404(
        Room.objects.select_related("floor__building"), code=code)
    now = timezone.now()
    if room.floor_id not in _guard_floor_ids(request.user, now):
        raise Http404("No such room on your posted floors.")

    grace = timedelta(minutes=int(get_policy("grace_minutes")))
    # MSSQL/pyodbc runs with MARS off: materialize each queryset before the next
    # one is issued (precedent: web/ifo.py room_panel).
    today = list(room.sessions.filter(date=timezone.localdate())
                 .select_related("schedule", "faculty")
                 .order_by("scheduled_start"))
    tile = room_tile(room, today, now, grace)
    # Same rule as the tile: an online class is not in this physical room, so it
    # is not in its day either. In a virtual room it is the whole timetable.
    today = [s for s in today if occupies(s, room)]

    term = AcademicTerm.objects.filter(is_active=True).first()
    return render(request, "guard/room.html", {
        "room": room, "tile": tile, "today": today, "term": term,
        "style": _ROOM_CARD_STYLES[tile["state"]],
        "timetable": room_timetable(room, term),
        "now": timezone.localtime(now),
    })


@guard_required
@require_http_methods(["GET"])
def locate(request):
    """GRD-03 faculty locator: find a professor's current room/course/end time, or
    report Online / not-in-a-class plus their next class today. Read-only search."""
    q = (request.GET.get("q") or "").strip()
    faculty = matches = current = nxt = None
    online_now = False
    if q:
        base = get_user_model().objects.filter(role=Role.FACULTY)
        matches = list(base.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)).order_by("last_name", "username")[:8])
        if len(matches) == 1:
            faculty = matches[0]
            now, today = timezone.now(), timezone.localdate()
            current = (Session.objects
                       .filter(faculty=faculty, date=today, status=SessionStatus.ACTIVE)
                       .select_related("room", "schedule").order_by("scheduled_start").first())
            if current is not None:
                eff = current.declared_modality or current.schedule.modality
                online_now = eff == Modality.ONLINE
            nxt = (Session.objects
                   .filter(faculty=faculty, date=today, scheduled_start__gte=now)
                   .exclude(status=SessionStatus.ABSENT)
                   .select_related("room", "schedule").order_by("scheduled_start").first())
    return render(request, "guard/locate.html", {
        "q": q, "faculty": faculty, "matches": matches,
        "current": current, "next": nxt, "online_now": online_now})
