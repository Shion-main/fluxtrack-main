"""
Single dedicated FluxTrack scheduler process (ENV-04; JOB-01/02/03).

This command owns ALL scheduled work: materialize (JOB-01), the status sweep
(JOB-02 = no-show marking + room-conflict detection), and the weekly report slot
(JOB-03, body lands Phase 6). It runs ONE `BlockingScheduler` + the default
`MemoryJobStore`, started ONLY here — never inside a Gunicorn web worker or an
`AppConfig.ready()`, which would start one scheduler per worker and double-fire
every job (the exact failure ENV-04 prohibits; NoImplicitSchedulerTests guards it).

`build_scheduler()` is factored out (returns the configured, UNSTARTED scheduler)
so wiring is unit-testable via `get_jobs()` without launching the blocking loop
(SchedulerWiringTests). Every job callable is wrapped in `ops.jobrun.run_job`,
which records a JobRun row per run and alerts System Admins on failure only.

Dev:  a second terminal -> `py -3.12 manage.py runscheduler` (alongside runserver).
Prod: a second systemd unit on the same instance running this command.
Output is ASCII-only (Windows console is cp1252) per Conventions §4.
"""
from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.jobrun import run_job
from ops.policy import get_policy
from ops.push import send_push_outbox
from ops.reports import generate_week_reports, report_week_bounds
from scheduling.jobs import detect_room_conflicts, sweep_no_shows

# Materialize cadence (discretion): re-fill the session horizon every 6 hours.
# The sweep cadence, by contrast, is policy-driven (get_policy below), not a
# magic number, because it gates the no-show grace experience (Conventions §3).
_MATERIALIZE_INTERVAL_HOURS = 6


def _job_materialize():
    """JOB-01: extend the dated-session horizon. Reuses the command (not its logic)."""
    call_command("materialize_sessions")
    return 0  # session count is reported by the command; nothing to tally here


def _job_sweep():
    """JOB-02: mark F2F/Blended no-shows Absent, then flag room conflicts.

    Returns the combined count so JobRun.rows_affected reflects the run's impact.
    """
    marked = sweep_no_shows()
    flagged = detect_room_conflicts()
    return marked + flagged


def _job_weekly_report():
    """JOB-03: generate the PRIOR week's per-department reports + ALL roll-up.

    Fires Mon 06:00 (see build_scheduler). Computes the prior completed Mon-Sun on
    LOCAL Asia/Manila dates -- ``report_week_bounds(localdate() - 7 days)``, never a
    UTC boundary (Pitfall 1) -- and delegates to the shared ``generate_week_reports``
    service the on-demand command also uses, so auto-weekly and on-demand can never
    diverge. Returns the count of reports generated so JobRun.rows_affected is
    meaningful. This is a FILLED stub body: the job set (4 jobs) is unchanged
    (ENV-04 / SchedulerWiringTests).
    """
    week_start, week_end = report_week_bounds(timezone.localdate() - timedelta(days=7))
    return generate_week_reports(week_start, week_end)


def build_scheduler():
    """Return a configured, UNSTARTED BlockingScheduler with exactly 4 jobs (ENV-04).

    Constructing (not starting) here keeps wiring unit-testable and guarantees the
    scheduler exists in exactly one place. Each job is wrapped in run_job so every
    execution records a JobRun and failures alert System Admins. The push_outbox
    job (NOTIF-02, D-09) runs the web-push send/prune pass HERE -- never in a web
    worker -- so a hung push endpoint can never touch the triggering request
    (criterion #4).
    """
    sched = BlockingScheduler(timezone=settings.TIME_ZONE)  # Asia/Manila

    sched.add_job(
        lambda: run_job("materialize", _job_materialize),
        IntervalTrigger(hours=_MATERIALIZE_INTERVAL_HOURS),
        id="materialize", max_instances=1, coalesce=True,
        misfire_grace_time=3600, replace_existing=True)

    # Sweep cadence from policy (default 5 min) — never hardcoded (Conventions §3).
    sched.add_job(
        lambda: run_job("sweep", _job_sweep),
        IntervalTrigger(minutes=get_policy("sweep_interval_minutes")),
        id="sweep", max_instances=1, coalesce=True,
        misfire_grace_time=300, replace_existing=True)

    sched.add_job(
        lambda: run_job("weekly_report", _job_weekly_report),
        CronTrigger(day_of_week="mon", hour=6),
        id="weekly_report", max_instances=1, coalesce=True,
        replace_existing=True)

    # Push outbox cadence from policy (default 15s) — never hardcoded (Conventions
    # §3). Wrapped in run_job so a bad pass records a failed JobRun and NEVER
    # re-raises, keeping this BlockingScheduler alive (criterion #4). max_instances
    # =1 + coalesce prevent pile-up if a pass runs long (T-05-07).
    sched.add_job(
        lambda: run_job("push_outbox", send_push_outbox),
        IntervalTrigger(seconds=get_policy("push_outbox_interval_seconds")),
        id="push_outbox", max_instances=1, coalesce=True,
        misfire_grace_time=60, replace_existing=True)

    return sched


class Command(BaseCommand):
    help = "Run the single dedicated FluxTrack scheduler (JOB-01/02/03) (ENV-04)."

    def handle(self, *args, **o):
        sched = build_scheduler()
        interval = get_policy("sweep_interval_minutes")
        push_interval = get_policy("push_outbox_interval_seconds")
        self.stdout.write(self.style.SUCCESS(
            f"Scheduler started -> materialize (every {_MATERIALIZE_INTERVAL_HOURS}h), "
            f"sweep (every {interval} min), weekly_report (Mon 06:00), "
            f"push_outbox (every {push_interval} s). "
            "Ctrl-C to stop."))
        try:
            sched.start()  # blocks the process
        except (KeyboardInterrupt, SystemExit):
            sched.shutdown()
            self.stdout.write(self.style.SUCCESS("Scheduler stopped."))
