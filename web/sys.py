"""System-admin operational surfaces (SYS-04): scheduled-job status monitor.

Read-only. The dedicated `runscheduler` process records one `ops.JobRun` per run
(ENV-04); this surface reads the latest row per job plus a short run history so a
System Admin can confirm the materialize / sweep / weekly-report / push-outbox
jobs are actually firing and see failures.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from accounts.models import Role
from ops.models import JobRun


def sysadmin_required(view):
    """Per-view role guard (Convention rule #5), mirroring ifo_required."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.SYSTEM_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _duration_s(run):
    if run.finished_at is None:
        return None
    return (run.finished_at - run.started_at).total_seconds()


@sysadmin_required
def jobs(request):
    """SYS-04: last-run status per scheduled job + recent run history (read-only)."""
    names = list(
        JobRun.objects.order_by("job_name").values_list("job_name", flat=True).distinct())
    latest = []
    for name in names:
        run = JobRun.objects.filter(job_name=name).first()  # Meta ordering: -started_at
        if run is not None:
            latest.append({"run": run, "duration": _duration_s(run)})
    recent = [{"run": r, "duration": _duration_s(r)} for r in JobRun.objects.all()[:25]]
    return render(request, "sys/jobs.html", {"latest": latest, "recent": recent})
