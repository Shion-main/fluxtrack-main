"""Scheduled-job observability wrapper (ENV-04; feeds SYS-04 in Phase 7).

`run_job(job_name, fn)` is the single wrapper every job registered on the
dedicated `runscheduler` BlockingScheduler runs through. It records exactly one
`JobRun` row per execution (status running -> ok|failed, rows_affected, started/
finished timestamps) so last-run status is queryable (ENV-04), and it notifies
System Admins via the shared `notify()` write path on FAILURE ONLY — success and
heartbeat runs never notify.

It catches broad `Exception` on purpose: a single bad job run must record
status=failed and alert, but must NEVER re-raise — otherwise one failing tick
would kill the long-lived BlockingScheduler process (T-02-13 denial of service).

Jobs here are short (a sweep/materialize pass), so per-run connection recycling
(`close_old_connections`, research Pitfall 6) is intentionally NOT used: it would
close the connection Django's per-test transaction holds, and short jobs never
outlive a pyodbc connection's server-side lifetime in practice.
"""
from django.utils import timezone

from accounts.models import Role
from ops.models import JobRun
from ops.notify import notify


def run_job(job_name, fn):
    """Run `fn` under observability: record a JobRun, notify SysAdmins on failure only.

    Records status="ok" + rows_affected=int(fn() or 0) on success; on any
    Exception records status="failed", detail=repr(exc) (truncated), and sends a
    single `job_failed` Notification to every active SYSTEM_ADMIN. Always stamps
    finished_at and saves. Returns the JobRun. Never re-raises (ENV-04 / T-02-13).
    """
    run = JobRun.objects.create(
        job_name=job_name, status="running", started_at=timezone.now())
    try:
        rows = fn() or 0
        run.status, run.rows_affected = "ok", int(rows)
    except Exception as exc:  # noqa: BLE001 — a bad run must not crash the scheduler
        run.status, run.detail = "failed", repr(exc)[:2000]
        notify(role=Role.SYSTEM_ADMIN, type="job_failed",
               title=f"Job failed: {job_name}", body=repr(exc)[:500])
    finally:
        run.finished_at = timezone.now()
        run.save()
    return run
