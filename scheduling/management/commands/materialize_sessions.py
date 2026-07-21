"""Materialize dated Sessions from the authoritative ACTIVE academic term."""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from scheduling.materialization import MaterializationError, materialize_term
from scheduling.models import AcademicTerm, ScheduleStatus
from scheduling.term_scope import NoActiveTermError, require_active_term


class Command(BaseCommand):
    help = "Create dated sessions from active schedules (skips breaks)."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=7, help="Horizon in days (default 7)")
        p.add_argument("--from", dest="start", help="Start date YYYY-MM-DD (default today)")
        p.add_argument("--term", help="ACTIVE term primary key or exact name")

    def handle(self, *args, **o):
        term = self._resolve_term(o.get("term"))
        start = self._parse_start(o["start"])
        try:
            result = materialize_term(term, start=start, days=o["days"])
        except MaterializationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Materialized {start}: {result.created} new sessions "
            f"({result.existing} already existed, {result.skipped} skipped) "
            f"from {self._active_schedule_count(term)} active schedules "
            f"in term '{term.name}'."))

    def _parse_start(self, raw):
        return (
            datetime.strptime(raw, "%Y-%m-%d").date()
            if raw else timezone.localdate()
        )

    def _resolve_term(self, raw):
        if not raw:
            try:
                return require_active_term()
            except NoActiveTermError as exc:
                raise CommandError("No ACTIVE academic term.") from exc

        lookup = {"pk": int(raw)} if raw.isdigit() else {"name": raw}
        try:
            term = AcademicTerm.objects.get(**lookup)
        except AcademicTerm.DoesNotExist as exc:
            raise CommandError(f"No academic term matches '{raw}'.") from exc
        if term.status != AcademicTerm.Status.ACTIVE:
            raise CommandError("The selected term must be ACTIVE.")
        return term

    def _active_schedule_count(self, term):
        return term.schedules.filter(status=ScheduleStatus.ACTIVE).count()
