"""Retention behavior for high-volume operational records."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from django.contrib.auth import get_user_model
from ops.models import JobRun, Notification


class PruneOperationalDataTests(TestCase):
    def test_prunes_only_job_runs_older_than_the_retention_window(self):
        old = JobRun.objects.create(
            job_name="push_outbox", status="ok",
            started_at=timezone.now() - timedelta(days=31),
        )
        recent = JobRun.objects.create(
            job_name="push_outbox", status="ok",
            started_at=timezone.now() - timedelta(days=29),
        )

        output = StringIO()
        call_command("prune_operational_data", days=30, stdout=output)

        self.assertFalse(JobRun.objects.filter(pk=old.pk).exists())
        self.assertTrue(JobRun.objects.filter(pk=recent.pk).exists())
        self.assertIn("1 JobRun", output.getvalue())


class CheckSchedulerTests(TestCase):
    def setUp(self):
        get_user_model().objects.create(
            username="scheduler-admin", role=Role.SYSTEM_ADMIN, is_active=True)

    def test_fresh_completed_job_is_healthy(self):
        JobRun.objects.create(
            job_name="push_outbox", status="ok",
            started_at=timezone.now(), finished_at=timezone.now(),
        )
        call_command("checkscheduler", max_age_minutes=5, stdout=StringIO())
        self.assertFalse(Notification.objects.filter(
            type="scheduler_stale").exists())

    def test_missing_or_stale_scheduler_alerts_and_exits_nonzero(self):
        with self.assertRaises(CommandError):
            call_command("checkscheduler", max_age_minutes=5, stderr=StringIO())
        self.assertEqual(Notification.objects.filter(
            type="scheduler_stale").count(), 1)

        # Repeated timer ticks within an hour do not spam every administrator.
        with self.assertRaises(CommandError):
            call_command("checkscheduler", max_age_minutes=5, stderr=StringIO())
        self.assertEqual(Notification.objects.filter(
            type="scheduler_stale").count(), 1)
