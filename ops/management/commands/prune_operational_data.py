"""Bound growth of high-frequency operational telemetry."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ops.models import JobRun


class Command(BaseCommand):
    help = "Delete JobRun telemetry older than its configured retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.JOB_RUN_RETENTION_DAYS,
            help="JobRun retention in days (default: JOB_RUN_RETENTION_DAYS).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be at least 1")
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = JobRun.objects.filter(started_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Pruned {deleted} JobRun row(s) older than {days} day(s)."))
