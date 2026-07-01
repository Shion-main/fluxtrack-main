"""
Materialize dated Sessions from active Schedules (JOB-01 core logic).

For the active term, create one Session per Schedule per matching weekday within
the window, skipping dates inside an AcademicBreak and outside the term bounds.
Idempotent: re-running only fills gaps.

Usage:
    py -3.12 manage.py materialize_sessions --days 7
    py -3.12 manage.py materialize_sessions --from 2026-07-06 --days 14
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from scheduling.models import (AcademicTerm, ScheduleStatus, Session,
                               SessionStatus)


class Command(BaseCommand):
    help = "Create dated sessions from active schedules (skips breaks)."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=7, help="Horizon in days (default 7)")
        p.add_argument("--from", dest="start", help="Start date YYYY-MM-DD (default today)")

    def handle(self, *args, **o):
        term = AcademicTerm.objects.filter(is_active=True).first()
        if not term:
            self.stderr.write(self.style.ERROR("No active term. Import first."))
            return

        start = (datetime.strptime(o["start"], "%Y-%m-%d").date()
                 if o["start"] else timezone.localdate())
        end = start + timedelta(days=o["days"])
        breaks = list(term.breaks.all())

        def in_break(d):
            return any(b.start_date <= d <= b.end_date for b in breaks)

        schedules = (term.schedules.filter(status=ScheduleStatus.ACTIVE)
                     .select_related("faculty", "room"))
        created = existing = 0
        d = start
        while d < end:
            in_term = term.start_date <= d <= term.end_date
            if in_term and not in_break(d):
                for sch in schedules:
                    if sch.day_of_week != d.weekday():
                        continue
                    ss = timezone.make_aware(datetime.combine(d, sch.start_time))
                    se = timezone.make_aware(datetime.combine(d, sch.end_time))
                    _, was_created = Session.objects.get_or_create(
                        schedule=sch, date=d,
                        defaults={"faculty": sch.faculty, "room": sch.room,
                                  "scheduled_start": ss, "scheduled_end": se,
                                  "status": SessionStatus.SCHEDULED})
                    created += was_created
                    existing += not was_created
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"Materialized {start} -> {end}: {created} new sessions "
            f"({existing} already existed) from {schedules.count()} active schedules "
            f"in term '{term.name}'."))
