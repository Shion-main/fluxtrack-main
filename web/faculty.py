"""Faculty surfaces (mobile-first, §2.5): today/week schedule (FAC-01) and check-in."""
from datetime import timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from accounts.models import Role
from scheduling.models import Session


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
