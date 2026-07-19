"""Guard surfaces (GRD-01 floor monitor, GRD-03 faculty locator).

READ-ONLY throughout, and read-only BY CONTRACT (GRD-05): every view carries
`@require_http_methods(["GET"])`, so a POST is refused with 405 rather than
merely having no write branch to reach. GuardReadOnlyTests asserts this per URL;
every Guard view added later must carry the decorator and join that list.

Floor scoping mirrors the checker's on-duty derivation exactly: the server is the
sole source of the guard's floors (GRD/CHK-01 rule), never the client.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from scheduling.models import Modality, Session, SessionStatus
from verification import resolver as R
from verification.models import Assignment, AssignmentScope, DutyRole


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
            floor_ids.update(a.floors.values_list("pk", flat=True))
    return floor_ids


def _poll_ms():
    return settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000


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
