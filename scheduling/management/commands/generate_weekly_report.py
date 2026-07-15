"""On-demand weekly consolidated report generation (RPT-02).

Mirrors the JOB-03 scheduler slot (runscheduler._job_weekly_report) for manual
runs, reusing the SAME ops.reports.generate_week_reports service so the auto-weekly
job and this command can never diverge (no duplicated generation logic). It does
NOT start a scheduler and adds NO job -- it is the ``_job_materialize -> call a
command`` indirection pattern in reverse: a thin CLI over the shared service.

Usage:
    py -3.12 manage.py generate_weekly_report            # prior completed week
    py -3.12 manage.py generate_weekly_report --week 2026-07-06

``--week`` accepts any date inside the target week (normalized to that week's
Monday via report_week_bounds). Output is ASCII-only (Windows console is cp1252)
per Conventions 4.
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ops.reports import generate_week_reports, report_week_bounds


class Command(BaseCommand):
    help = "Generate the weekly consolidated reports on demand (RPT-02)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week", dest="week", default=None,
            help="A date (YYYY-MM-DD) inside the target week; "
                 "defaults to the prior completed week.")

    def handle(self, *args, **options):
        raw = options.get("week")
        if raw:
            try:
                reference = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--week must be a date in YYYY-MM-DD format.")
        else:
            # Same reference JOB-03 uses: the prior completed week.
            reference = timezone.localdate() - timedelta(days=7)

        week_start, week_end = report_week_bounds(reference)
        count = generate_week_reports(week_start, week_end)

        self.stdout.write(self.style.SUCCESS(
            f"Generated {count} weekly report(s) -> week of {week_start} "
            f"({week_start} to {week_end})."))
