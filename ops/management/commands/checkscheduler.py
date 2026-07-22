"""External watchdog for the single long-lived scheduler process."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Role
from ops.models import JobRun, Notification
from ops.notify import notify


class Command(BaseCommand):
    help = "Fail and alert when no scheduler job has completed recently."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-minutes",
            type=int,
            default=settings.SCHEDULER_STALE_MINUTES,
        )

    def handle(self, *args, **options):
        minutes = options["max_age_minutes"]
        if minutes < 1:
            raise CommandError("--max-age-minutes must be at least 1")

        now = timezone.now()
        latest = JobRun.objects.filter(
            finished_at__isnull=False).order_by("-finished_at").first()
        if latest and latest.finished_at >= now - timedelta(minutes=minutes):
            self.stdout.write(self.style.SUCCESS(
                f"Scheduler healthy; last completion {latest.finished_at.isoformat()}."))
            return

        detail = (
            "No completed scheduler job was found."
            if latest is None
            else f"Last scheduler completion was {latest.finished_at.isoformat()}."
        )
        recently_alerted = Notification.objects.filter(
            type="scheduler_stale",
            created_at__gte=now - timedelta(hours=1),
        ).exists()
        if not recently_alerted:
            notify(
                role=Role.SYSTEM_ADMIN,
                type="scheduler_stale",
                title="Scheduler heartbeat is stale",
                body=f"{detail} Check fluxtrack-scheduler.service.",
            )
        raise CommandError(
            f"Scheduler stale (>{minutes} minutes). {detail}")
