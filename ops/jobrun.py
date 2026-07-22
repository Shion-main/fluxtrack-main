"""Observability and connection hygiene for every scheduled job."""
from django.db import close_old_connections, connections
from django.utils import timezone

from accounts.models import Role
from ops.models import JobRun
from ops.notify import notify


def _recycle_old_connections():
    """Recycle only when no caller owns an atomic transaction.

    A real scheduler tick is never inside ``atomic()``. Skipping there protects
    callers that deliberately wrap ``run_job`` in a transaction (including
    Django's TestCase harness), because closing that connection would destroy
    the caller-owned transaction rather than merely refresh an idle one.
    """
    if any(connection.in_atomic_block for connection in connections.all()):
        return
    close_old_connections()


def run_job(job_name, fn):
    """Record one run, alert on failure, and never kill the scheduler loop.

    The scheduler is long-lived, so Django gets a chance to discard unusable or
    expired ODBC connections at both boundaries of every job. This makes an RDS
    failover or idle connection recover on the next tick.
    """
    _recycle_old_connections()
    try:
        run = JobRun.objects.create(
            job_name=job_name, status="running", started_at=timezone.now())
        try:
            rows = fn() or 0
            run.status, run.rows_affected = "ok", int(rows)
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            run.status, run.detail = "failed", repr(exc)[:2000]
            notify(
                role=Role.SYSTEM_ADMIN,
                type="job_failed",
                title=f"Job failed: {job_name}",
                body=repr(exc)[:500],
            )
        finally:
            run.finished_at = timezone.now()
            run.save()
        return run
    finally:
        _recycle_old_connections()
