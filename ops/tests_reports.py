"""Tests for the weekly report service + JOB-03 fill (RPT-02 / ENV-04 / NOTIF-00).

Exercises ops/reports.py and the filled scheduler slot against the shared
make_reporting_fixture (06-01): a two-department, multi-status object graph inside
the known Mon-Sun week beginning 2026-07-06. Storage assertions run against an
isolated temp MEDIA_ROOT so no real repo files are touched. ASCII-only.
"""
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from accounts.models import Role
from ops.models import Notification, WeeklyReport
from ops.notifications import WEEKLY_REPORT_READY
from ops.reports import (generate_weekly_report, notify_report_ready,
                         report_week_bounds)
from scheduling.models import SessionStatus
from scheduling.reporting import faculty_attendance
from scheduling.test_support import make_reporting_fixture

# One temp MEDIA_ROOT for the whole module; every storage-touching class overrides
# MEDIA_ROOT to it so default_storage writes here and never into the repo media/.
_MEDIA = tempfile.mkdtemp(prefix="fluxtrack-reports-test-")


def tearDownModule():  # noqa: N802 (Django/unittest hook name)
    shutil.rmtree(_MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=_MEDIA)
class IdempotencyTests(TestCase):
    """RPT-02: re-generating the same week+department upserts one row (no dup)."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_generate_twice_upserts_one_row_and_repopulates_paths(self):
        fx = self.fx
        r1 = generate_weekly_report(
            week_start=fx.week_start, week_end=fx.sun, department=fx.dept_a)
        r2 = generate_weekly_report(
            week_start=fx.week_start, week_end=fx.sun, department=fx.dept_a)

        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(
            WeeklyReport.objects.filter(
                week_start=fx.week_start, department=fx.dept_a).count(), 1)
        self.assertTrue(r2.csv_path)
        self.assertTrue(r2.pdf_path)
        self.assertTrue(default_storage.exists(r2.csv_path))
        self.assertTrue(default_storage.exists(r2.pdf_path))

    def test_all_rollup_department_none_is_idempotent(self):
        fx = self.fx
        r1 = generate_weekly_report(
            week_start=fx.week_start, week_end=fx.sun, department=None)
        r2 = generate_weekly_report(
            week_start=fx.week_start, week_end=fx.sun, department=None)

        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(
            WeeklyReport.objects.filter(
                week_start=fx.week_start, department__isnull=True).count(), 1)

    def test_storage_name_is_server_built_from_dept_code_and_week(self):
        fx = self.fx
        report = generate_weekly_report(
            week_start=fx.week_start, week_end=fx.sun, department=fx.dept_a)
        # Path is derived ONLY from department.code + week_start (T-06-05), never
        # from any request input, so it can never traverse out of the reports tree.
        self.assertTrue(report.csv_path.startswith(f"reports/{fx.week_start}/"))
        self.assertIn(fx.dept_a.code, report.csv_path)


@override_settings(MEDIA_ROOT=_MEDIA)
class NotifyTargetingTests(TestCase):
    """RPT-02 / T-06-06: IFO + only the report's department Dean are notified."""

    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_admin1", email="ifo1@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.dean_a = User.objects.create(
            username="dean_a1", email="deana@mcm.edu.ph",
            role=Role.DEAN, department=self.fx.dept_a, is_active=True)
        self.dean_b = User.objects.create(
            username="dean_b1", email="deanb@mcm.edu.ph",
            role=Role.DEAN, department=self.fx.dept_b, is_active=True)

    def _count(self, user):
        return Notification.objects.filter(
            user=user, type=WEEKLY_REPORT_READY).count()

    def test_dept_report_notifies_ifo_and_that_dept_dean_only(self):
        fx = self.fx
        notify_report_ready(fx.dept_a, fx.week_start, link="/reports/x/")

        self.assertEqual(self._count(self.ifo), 1)
        self.assertEqual(self._count(self.dean_a), 1)
        self.assertEqual(self._count(self.dean_b), 0)  # other dept Dean untouched

    def test_all_rollup_notifies_ifo_not_any_dean(self):
        notify_report_ready(None, self.fx.week_start, link="")

        self.assertEqual(self._count(self.ifo), 1)
        self.assertEqual(
            Notification.objects.filter(
                type=WEEKLY_REPORT_READY, user__role=Role.DEAN).count(), 0)

    def test_notification_written_only_through_notify_path(self):
        # No Notification row exists before generation; notify() creates them.
        self.assertEqual(Notification.objects.count(), 0)
        notify_report_ready(self.fx.dept_b, self.fx.week_start, link="")
        self.assertEqual(self._count(self.dean_b), 1)
        self.assertEqual(self._count(self.dean_a), 0)


class WeekBoundaryTests(TestCase):
    """RPT-02 / Pitfall 1: Monday..Sunday local bounds; no UTC edge drift."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_bounds_are_monday_to_sunday_local(self):
        # A Wednesday resolves to its own Mon..Sun week.
        start, end = report_week_bounds(date(2026, 7, 8))
        self.assertEqual(start, date(2026, 7, 6))   # Monday
        self.assertEqual(end, date(2026, 7, 12))    # Sunday

    def test_sunday_included_next_monday_excluded(self):
        fx = self.fx
        start, end = report_week_bounds(fx.week_start)

        base = next(r for r in faculty_attendance(
            start=start, end=end, department=fx.dept_a)
            if r.faculty_id == fx.faculty_a.id)
        base_scheduled = base.scheduled

        # A Sunday-of-week session must be counted; the following Monday must not.
        fx.add_session(fx.faculty_a, fx.sun, SessionStatus.ACTIVE)
        fx.add_session(fx.faculty_a, fx.next_monday, SessionStatus.ACTIVE)

        after = next(r for r in faculty_attendance(
            start=start, end=end, department=fx.dept_a)
            if r.faculty_id == fx.faculty_a.id)

        self.assertEqual(after.scheduled, base_scheduled + 1)
